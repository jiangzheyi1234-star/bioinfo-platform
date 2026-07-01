from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from core.app_runtime import runtime_config
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.server_health import (
    build_runner_ensure_failure_snapshot,
)
from core.app_runtime.server_health_projection import build_server_health_projection
from core.app_runtime import runner_stop_state
from core.app_runtime.server_payloads import (
    build_primary_server_identity,
    compose_ssh_status,
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
    _compose_ssh_status = staticmethod(compose_ssh_status)
    _compose_server_payload = staticmethod(compose_server_payload)
    _compose_runner_payload = staticmethod(compose_runner_payload)

    @staticmethod
    def _local_tunnel_snapshots(ssh: Optional[SSHService]) -> list[dict[str, Any]]:
        if ssh is None or not getattr(ssh, "is_connected", False):
            return []
        snapshotter = getattr(ssh, "local_tunnel_snapshots", None)
        if not callable(snapshotter):
            return [
                {
                    "schemaVersion": "local-ssh-tunnel.v1",
                    "name": "unavailable",
                    "localHost": "",
                    "localPort": 0,
                    "remoteHost": "",
                    "remotePort": 0,
                    "active": False,
                }
            ]
        return snapshotter()

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

    def _save_runner_health_snapshot(self, *, server_id: str, health: dict[str, Any]) -> dict[str, Any]:
        patch: dict[str, Any] = {"last_health_snapshot": health}
        runtime_state = health.get("runtimeState")
        runtime_bind_port = runtime_state.get("bindPort") if isinstance(runtime_state, dict) else None
        service_port = self._coerce_positive_port(health.get("servicePort") or runtime_bind_port)
        tunnel_port = self._coerce_positive_port(health.get("tunnelPort"))
        if service_port is not None:
            patch["service_port"] = service_port
        if tunnel_port is not None:
            patch["tunnel_port"] = tunnel_port
        return self._save_server_registry_entry(server_id, patch)

    @staticmethod
    def _coerce_positive_port(value: Any) -> int | None:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return None
        if port <= 0 or port > 65535:
            return None
        return port

    def _save_runner_connection_metadata_from_detail(
        self,
        *,
        server_id: str,
        detail: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(detail, dict):
            return None
        runtime_state = detail.get("runtimeState")
        runtime_bind_port = runtime_state.get("bindPort") if isinstance(runtime_state, dict) else None
        service_port = self._coerce_positive_port(detail.get("servicePort") or runtime_bind_port)
        tunnel_port = self._coerce_positive_port(detail.get("tunnelPort"))
        patch: dict[str, Any] = {}
        if service_port is not None:
            patch["service_port"] = service_port
        if tunnel_port is not None:
            patch["tunnel_port"] = tunnel_port
        if not patch:
            return None
        return self._save_server_registry_entry(server_id, patch)

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
        if runner_stop_state.requires_explicit_runner_start(registry_entry):
            return status
        if isinstance(snapshot, dict):
            reason_code = str(snapshot.get("reasonCode") or "")
            if reason_code == "RUNNER_SETUP_FAILED":
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
        except RuntimeServiceError as exc:
            with self._lock:
                self._save_runner_connection_metadata_from_detail(
                    server_id=server_id,
                    detail=exc.detail,
                )
                self._save_runner_preparing_snapshot(
                    server_id=server_id,
                    message="远程服务正在恢复...",
                    state="recovering",
                )
            self._ensure_runner_ready_in_background(server_id)
            with self._lock:
                return self._get_ssh_status_unlocked()
        with self._lock:
            self._save_runner_health_snapshot(server_id=server_id, health=health)
            return self._get_ssh_status_unlocked()

    def _ensure_runner_ready_in_background(self, server_id: str) -> None:
        with self._lock:
            if server_id in self._runner_ensure_inflight:
                return
            record = self._get_server_registry_entry(server_id)
            if runner_stop_state.requires_explicit_runner_start(record):
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

    def _replace_server_registry_entry(self, server_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        current = runtime_config.get_runtime_config()
        registry = self._get_server_registry()
        replacement = {key: value for key, value in entry.items() if value is not None}
        registry[server_id] = replacement
        runtime_config.save_runtime_config(
            runtime_config.merge_runtime_config_patch(current, {"servers": registry})
        )
        return replacement

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
        runner_stop_state.raise_if_runner_manually_stopped(server_id=server_id, record=record)
        if record.get("bootstrap_version"):
            health = self._call_remote_runner(
                manager.get_health,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
            )
            if bool((health.get("ready") or {}).get("ok")):
                with self._lock:
                    record = self._save_runner_health_snapshot(server_id=server_id, health=health)
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
        return build_server_health_projection(
            self,
            server_id=server_id,
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )

    def _get_ssh_status_unlocked(self) -> dict[str, Any]:
        ssh = self._service_locator.ssh_service
        connected = ssh is not None and getattr(ssh, "is_connected", False)
        status = self._compose_ssh_status(
            ssh_config=runtime_config.get_runtime_config().get("ssh", {}),
            connected=connected,
            connect_in_progress=self._connect_in_progress,
            auto_connect_attempted=self._auto_connect_attempted,
            auto_connect_in_progress=self._auto_connect_in_progress,
            auto_connect_failed=self._auto_connect_failed,
            auto_connect_error=self._auto_connect_error,
        )
        server = self._build_primary_server_identity(ssh_status=status)
        if server is not None:
            status["serverId"] = server["serverId"]
        if connected and server is not None:
            registry_entry = self._get_server_registry_entry(str(server["serverId"]))
            snapshot = registry_entry.get("last_health_snapshot")
            if runner_stop_state.has_unsupported_runner_stop_snapshot(registry_entry):
                snapshot = runner_stop_state.unsupported_runner_stop_health(
                    str(server["serverId"]),
                    registry_entry,
                    self._get_saved_readiness_snapshot,
                )
            if isinstance(snapshot, dict):
                status["runner"] = self._compose_runner_payload(
                    registry_entry=registry_entry,
                    health=snapshot,
                    local_tunnels=self._local_tunnel_snapshots(ssh),
                )
        return status
