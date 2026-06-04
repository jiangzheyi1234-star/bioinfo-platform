from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from config import normalize_ssh_config
from core.app_runtime import runtime_config
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.server_health import (
    build_runner_ensure_failure_snapshot,
)
from core.app_runtime.server_payloads import (
    build_primary_server_identity,
    compose_runner_payload,
    compose_server_payload,
    get_saved_readiness_snapshot,
)
from core.remote.ssh_service import SSHService

logger = logging.getLogger(__name__)


class RuntimeServerStateMixin:
    _build_runner_ensure_failure_snapshot = staticmethod(build_runner_ensure_failure_snapshot)
    _build_primary_server_identity = staticmethod(build_primary_server_identity)
    _get_saved_readiness_snapshot = staticmethod(get_saved_readiness_snapshot)
    _compose_server_payload = staticmethod(compose_server_payload)
    _compose_runner_payload = staticmethod(compose_runner_payload)

    def _save_runner_preparing_snapshot(
        self,
        *,
        server_id: str,
        message: str,
        state: str = "preparing",
    ) -> None:
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save_server_registry_entry(
            server_id,
            {
                "last_health_snapshot": {
                    "serverId": server_id,
                    "state": state,
                    "startup": {"ok": False, "message": message},
                    "live": {"ok": False, "message": "Remote runner is starting."},
                    "ready": {"ok": False, "message": message},
                    "reasonCode": "",
                    "checkedAt": checked_at,
                }
            },
        )

    def _refresh_runner_status_or_recover(
        self,
        *,
        status: dict[str, Any],
        server_id: str,
        ssh,
        manager,
        registry_entry: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = registry_entry.get("last_health_snapshot")
        if isinstance(snapshot, dict):
            reason_code = str(snapshot.get("reasonCode") or "")
            if reason_code in {"RUNNER_STOPPED", "RUNNER_SETUP_FAILED", "RUNNER_NOT_READY"}:
                return status
        try:
            if ssh is None or not getattr(ssh, "is_connected", False):
                return status
            health = self._call_remote_runner(
                manager.get_health,
                server_id=server_id,
                ssh_service=ssh,
                server_record=registry_entry,
            )
        except RuntimeServiceError:
            with self._lock:
                self._save_runner_preparing_snapshot(
                    server_id=server_id,
                    message="远程服务正在恢复...",
                    state="recovering",
                )
            self._ensure_runner_ready_in_background(server_id)
            with self._lock:
                return self._get_ssh_status_unlocked()
        with self._lock:
            self._save_server_registry_entry(server_id, {"last_health_snapshot": health})
            return self._get_ssh_status_unlocked()

    def _ensure_runner_ready_in_background(self, server_id: str) -> None:
        with self._lock:
            if server_id in self._runner_ensure_inflight:
                return
            self._runner_ensure_inflight.add(server_id)

        def _worker() -> None:
            try:
                self.ensure_remote_runner_ready(server_id)
            except RuntimeServiceError as exc:
                logger.warning("Startup remote runner ensure failed for %s: %s", server_id, exc)
            finally:
                with self._lock:
                    self._runner_ensure_inflight.discard(server_id)

        thread = threading.Thread(
            target=_worker,
            name=f"h2ometa-ensure-runner-{server_id}",
            daemon=True,
        )
        thread.start()

    def _get_server_registry(self) -> dict[str, dict[str, Any]]:
        current = runtime_config.get_runtime_config()
        raw = current.get("servers", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _get_server_registry_entry(self, server_id: str) -> dict[str, Any]:
        registry = self._get_server_registry()
        entry = registry.get(server_id, {})
        return dict(entry) if isinstance(entry, dict) else {}

    def _save_server_registry_entry(self, server_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = runtime_config.get_runtime_config()
        registry = self._get_server_registry()
        entry = dict(registry.get(server_id, {}) or {})
        entry.update({key: value for key, value in patch.items() if value is not None})
        registry[server_id] = entry
        runtime_config.save_runtime_config(
            runtime_config.merge_runtime_config_patch(current, {"servers": registry})
        )
        return entry

    def _require_runner_ready(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ) -> tuple[str, SSHService, dict[str, Any]]:
        ssh_status = self._get_ssh_status_unlocked()
        server = self._build_primary_server_identity(ssh_status=ssh_status)
        if server is None:
            raise RuntimeServiceError("No server configured")
        server_id = str(preferred_server_id or server["serverId"] or "").strip() or server["serverId"]
        if server_id != server["serverId"]:
            raise RuntimeServiceError(f"Server not found: {server_id}")
        ssh = self._ensure_ssh_connected()
        manager = self._service_locator.remote_runner_manager
        record = self._get_server_registry_entry(server_id)
        if record.get("bootstrap_version"):
            health = self._call_remote_runner(
                manager.get_health,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
            )
            if bool((health.get("ready") or {}).get("ok")):
                return server_id, ssh, record
        self.ensure_remote_runner_ready(server_id)
        record = self._get_server_registry_entry(server_id)
        return server_id, ssh, record

    def _build_server_health(
        self,
        *,
        server_id: str,
        ssh_status: dict[str, Any],
        registry_entry: dict[str, Any],
        ssh: Optional[SSHService],
    ) -> dict[str, Any]:
        connected = bool(ssh_status.get("connected"))
        configured = bool(ssh_status.get("host") or ssh_status.get("ssh_host_alias"))
        startup = {
            "ok": configured,
            "message": "Local backend has server configuration." if configured else "No SSH target configured.",
        }
        live = {
            "ok": connected,
            "message": "SSH tunnel reachable." if connected else "SSH connection is not active.",
        }
        reason_code = ""
        ready_ok = False
        ready_message = "Remote runner is not ready."
        workflow_runtime: dict[str, Any] = {}
        pipeline_registry: dict[str, Any] = {}
        if not configured or not connected:
            reason_code = "SSH_NOT_CONNECTED"
            ready_message = "Connect to the remote server before submitting runs."
        elif not registry_entry.get("bootstrap_version"):
            snapshot = self._get_saved_readiness_snapshot(
                server_id=server_id,
                registry_entry=registry_entry,
            )
            if snapshot is not None:
                startup = snapshot["startup"]
                live = snapshot["live"]
                ready_ok = bool(snapshot["ready"]["ok"])
                ready_message = str(snapshot["ready"]["message"])
                reason_code = str(snapshot.get("reasonCode", "") or "RUNNER_NOT_READY")
                workflow_runtime = dict(snapshot.get("workflowRuntime") or {})
                pipeline_registry = dict(snapshot.get("pipelineRegistry") or {})
            else:
                reason_code = "RUNNER_NOT_READY"
                ready_message = "Prepare the remote workspace before using this server."
        else:
            try:
                if ssh is None or not getattr(ssh, "is_connected", False):
                    raise RuntimeServiceError("SSH disconnected")
                remote_health = self._call_remote_runner(
                    self._service_locator.remote_runner_manager.get_health,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=registry_entry,
                )
                startup = remote_health["startup"]
                live = remote_health["live"]
                ready_ok = bool(remote_health["ready"]["ok"])
                ready_message = str(remote_health["ready"]["message"])
                reason_code = str(remote_health.get("reasonCode", "") or "")
                workflow_runtime = dict(remote_health.get("workflowRuntime") or {})
                pipeline_registry = dict(remote_health.get("pipelineRegistry") or {})
                with self._lock:
                    self._save_server_registry_entry(server_id, {"last_health_snapshot": remote_health})
            except RuntimeServiceError as exc:
                snapshot = self._get_saved_readiness_snapshot(
                    server_id=server_id,
                    registry_entry=registry_entry,
                )
                if snapshot is not None:
                    startup = snapshot["startup"]
                    live = snapshot["live"]
                    ready_ok = bool(snapshot["ready"]["ok"])
                    ready_message = str(snapshot["ready"]["message"])
                    reason_code = str(snapshot.get("reasonCode", "") or "RUNNER_NOT_READY")
                    workflow_runtime = dict(snapshot.get("workflowRuntime") or {})
                    pipeline_registry = dict(snapshot.get("pipelineRegistry") or {})
                else:
                    reason_code = "RUNNER_NOT_READY"
                    ready_message = str(exc) or "Remote runner control plane is not reachable."
        return {
            "serverId": server_id,
            "startup": startup,
            "live": live,
            "ready": {"ok": ready_ok, "message": ready_message},
            "workflowRuntime": workflow_runtime,
            "pipelineRegistry": pipeline_registry,
            "reasonCode": reason_code,
            "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _get_ssh_status_unlocked(self) -> dict[str, Any]:
        ssh = self._service_locator.ssh_service
        connected = ssh is not None and getattr(ssh, "is_connected", False)
        cfg = normalize_ssh_config(runtime_config.get_runtime_config().get("ssh", {}))
        auth_mode = str(cfg.get("auth_mode", "password_ref") or "password_ref")
        identity_ref = str(cfg.get("identity_ref", "") or "").strip()
        status = {
            "connected": connected,
            "host": cfg.get("host", ""),
            "port": cfg.get("port", 22),
            "user": cfg.get("user", ""),
            "auth_mode": auth_mode,
            "ssh_host_alias": cfg.get("ssh_host_alias", ""),
            "identity_ref": identity_ref,
            "remember_auth": bool(cfg.get("remember_auth", True)),
            "has_password": bool(cfg.get("password_ref")),
            "timeout_sec": cfg.get("timeout_sec", 5),
            "auto_connect_on_startup": bool(cfg.get("auto_connect_on_startup", False)),
            "auto_connect_attempted": self._auto_connect_attempted,
            "auto_connect_in_progress": self._auto_connect_in_progress,
            "auto_connect_failed": self._auto_connect_failed,
            "auto_connect_error": self._auto_connect_error,
            "connecting": self._connect_in_progress,
            "message": "SSH connecting" if self._connect_in_progress or self._auto_connect_in_progress else ("SSH connected" if connected else "SSH disconnected"),
        }
        server = self._build_primary_server_identity(ssh_status=status)
        if connected and server is not None:
            registry_entry = self._get_server_registry_entry(str(server["serverId"]))
            snapshot = registry_entry.get("last_health_snapshot")
            if isinstance(snapshot, dict):
                status["runner"] = self._compose_runner_payload(registry_entry=registry_entry, health=snapshot)
        return status
