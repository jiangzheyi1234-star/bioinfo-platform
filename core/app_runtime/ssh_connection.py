from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from config import (
    delete_ssh_password,
    normalize_ssh_config,
    resolve_ssh_config_target,
    resolve_ssh_password,
    store_ssh_password,
)
from core.app_runtime import runtime_config
from core.app_runtime.runner_stop_state import is_runner_manually_stopped
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHReconnectError, SSHService

from .errors import RuntimeServiceError


logger = logging.getLogger(__name__)


class RuntimeSshConnectionMixin:
    def get_ssh_status(self) -> dict:
        with self._lock:
            self._ensure_initialized()
            status = self._get_ssh_status_unlocked()
            if not bool(status.get("connected")):
                return status
            server = self._build_primary_server_identity(ssh_status=status)
            if server is None:
                return status
            server_id = str(server["serverId"])
            registry_entry = self._get_server_registry_entry(server_id)
            if not registry_entry.get("bootstrap_version"):
                return status
            ssh = self._service_locator.ssh_service
            manager = self._service_locator.remote_runner_manager
            if not hasattr(manager, "get_health"):
                return status
        return self._refresh_runner_status_or_recover(
            status=status,
            server_id=server_id,
            ssh=ssh,
            manager=manager,
            registry_entry=registry_entry,
        )

    def connect_ssh(self, patch: Optional[dict] = None) -> dict:
        with self._lock:
            self._ensure_initialized()
            merged = normalize_ssh_config(runtime_config.get_runtime_config().get("ssh", {}))

            if patch:
                for k in (
                    "auth_mode",
                    "ssh_host_alias",
                    "identity_ref",
                    "remember_auth",
                    "auto_connect_on_startup",
                    "host",
                    "port",
                    "user",
                    "timeout_sec",
                ):
                    if k in patch and patch[k] is not None:
                        merged[k] = patch[k]

            merged = normalize_ssh_config(merged)
            auth_mode = str(merged.get("auth_mode", "password_ref") or "password_ref")
            if auth_mode == "ssh_config":
                resolved = resolve_ssh_config_target(merged)
            else:
                resolved = merged

            host = str(resolved.get("host", "")).strip()
            port = int(resolved.get("port", 22))
            user = str(resolved.get("user", "")).strip()
            password = (
                str(patch.get("password", ""))
                if patch and "password" in patch
                else resolve_ssh_password({"ssh": merged})
            )
            identity_ref = str(resolved.get("identity_ref", "") or "").strip()
            timeout = int(resolved.get("timeout_sec", 5))

            if not host or not user:
                raise RuntimeServiceError("ssh.host and ssh.user required")

            current = runtime_config.get_runtime_config()
            previous_password_ref = str(merged.get("password_ref", "") or "").strip()
            remember_auth = bool(merged.get("remember_auth", True))
            auto_connect_requested = bool(merged.get("auto_connect_on_startup", False))
            self._connect_in_progress = True

        try:
            use_agent = auth_mode == "agent"
            result = ssh_connect(
                ip=host,
                port=port,
                user=user,
                password=password,
                key_file=identity_ref if auth_mode in {"key_file", "ssh_config"} else "",
                use_agent=use_agent,
                timeout=timeout,
            )
            if not result.ok or result.client is None:
                result_code = str(getattr(result, "code", "") or "")
                if result_code == "SSH_HOST_KEY_UNTRUSTED":
                    raise RuntimeServiceError(
                        f"{result_code}: {result.message}",
                        status_code=409,
                    )
                raise RuntimeServiceError(result.message)

            def _reconnect():
                r = ssh_connect(
                    ip=host,
                    port=port,
                    user=user,
                    password=password,
                    key_file=identity_ref if auth_mode in {"key_file", "ssh_config"} else "",
                    use_agent=use_agent,
                    timeout=timeout,
                )
                if not r.ok:
                    raise SSHReconnectError(r.message)
                return r.client

            with self._lock:
                self._service_locator.ssh_service = SSHService(
                    initial_client=result.client, connect_fn=_reconnect
                )
                next_password_ref = previous_password_ref
                if auth_mode in {"key_file", "ssh_config", "agent"}:
                    delete_ssh_password(previous_password_ref)
                    next_password_ref = ""
                elif patch and "password" in patch:
                    if password:
                        next_password_ref = store_ssh_password(
                            host=host,
                            port=port,
                            user=user,
                            password=password,
                        )
                    else:
                        delete_ssh_password(previous_password_ref)
                        next_password_ref = ""
                persisted = {
                    **merged,
                    "auth_mode": auth_mode,
                    "ssh_host_alias": str(merged.get("ssh_host_alias", "") or "").strip(),
                    "remember_auth": remember_auth,
                    "password_ref": next_password_ref,
                    "identity_ref": identity_ref if auth_mode in {"key_file", "ssh_config"} else "",
                    "host": host if auth_mode != "ssh_config" else "",
                    "port": port if auth_mode != "ssh_config" else 22,
                    "user": user if auth_mode != "ssh_config" else "",
                    "timeout_sec": timeout,
                    "auto_connect_on_startup": bool(remember_auth and auto_connect_requested),
                }
                if not persisted["remember_auth"]:
                    persisted["password_ref"] = ""
                    persisted["identity_ref"] = ""
                    persisted["ssh_host_alias"] = ""
                    persisted["auto_connect_on_startup"] = False
                runtime_config.save_runtime_config(
                    runtime_config.merge_runtime_config_patch(current, {"ssh": persisted})
                )
                self._auto_connect_failed = False
                self._auto_connect_error = ""
                self._auto_connect_notice_key = ""
                self._connect_in_progress = False
                status = self._get_ssh_status_unlocked()
                server = self._build_primary_server_identity(ssh_status=status)
                if server is not None:
                    server_id = str(server["serverId"])
                    registry_entry = self._get_server_registry_entry(server_id)
                    runner_stopped = is_runner_manually_stopped(registry_entry)
                    snapshot = registry_entry.get("last_health_snapshot")
                    runner_ready = bool(
                        isinstance(snapshot, dict)
                        and (snapshot.get("ready") or {}).get("ok") is True
                    )
                    if not runner_stopped and not runner_ready:
                        self._save_runner_preparing_snapshot(
                            server_id=server_id,
                            message="Checking remote runner...",
                        )
                        status = self._get_ssh_status_unlocked()
            if server is not None and not runner_stopped:
                self._ensure_runner_ready_in_background(server_id)
            return status
        finally:
            with self._lock:
                self._connect_in_progress = False

    def _attempt_startup_auto_connect_in_background(self) -> None:
        if self._auto_connect_attempted or self._auto_connect_in_progress:
            return
        self._auto_connect_in_progress = True

        def _worker() -> None:
            try:
                self._attempt_startup_auto_connect()
            finally:
                with self._lock:
                    self._auto_connect_in_progress = False

        thread = threading.Thread(
            target=_worker,
            name="h2ometa-startup-auto-connect",
            daemon=True,
        )
        thread.start()

    def disconnect_ssh(self) -> dict:
        with self._lock:
            self._ensure_initialized()
            self._close_all_terminal_sessions()
            self._service_locator.ssh_service = None
            current = runtime_config.get_runtime_config()
            ssh_cfg = normalize_ssh_config(current.get("ssh", {}))
            ssh_cfg["auto_connect_on_startup"] = False
            runtime_config.save_runtime_config(
                runtime_config.merge_runtime_config_patch(current, {"ssh": ssh_cfg})
            )
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            return self._get_ssh_status_unlocked()

    def test_ssh_connection(self, patch: Optional[dict] = None) -> dict:
        with self._lock:
            self._ensure_initialized()
            merged = normalize_ssh_config(runtime_config.get_runtime_config().get("ssh", {}))
            if patch:
                for k in ("auth_mode", "ssh_host_alias", "identity_ref", "remember_auth", "host", "port", "user", "timeout_sec"):
                    if k in patch and patch[k] is not None:
                        merged[k] = patch[k]
            merged = normalize_ssh_config(merged)
            auth_mode = str(merged.get("auth_mode", "password_ref") or "password_ref")
            resolved = resolve_ssh_config_target(merged) if auth_mode == "ssh_config" else merged
            diagnostics_kwargs = {
                "ip": resolved.get("host", ""),
                "port": int(resolved.get("port", 22)),
                "user": resolved.get("user", ""),
                "password": str(patch.get("password", ""))
                if patch and "password" in patch
                else (resolve_ssh_password({"ssh": merged}) if auth_mode == "password_ref" else ""),
                "key_file": resolved.get("identity_ref", "") if auth_mode in {"key_file", "ssh_config"} else "",
                "use_agent": auth_mode == "agent",
            }
        steps = run_diagnostics(**diagnostics_kwargs)
        ok = all(step["status"] == "ok" for step in steps)
        status = self.get_ssh_status()
        return {
            "ok": ok,
            "message": "SSH diagnostics passed" if ok else "SSH diagnostics failed",
            "steps": [
                {"name": step["name"], "status": step["status"], "message": step["message"]}
                for step in steps
            ],
            "status": status,
        }

    def _ensure_ssh_connected(self) -> SSHService:
        ssh = self._service_locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            raise RuntimeServiceError("SSH disconnected")
        return ssh

    def _attempt_startup_auto_connect(self) -> None:
        if self._auto_connect_attempted:
            return
        self._auto_connect_attempted = True

        merged = normalize_ssh_config(runtime_config.get_runtime_config().get("ssh", {}))
        auth_mode = str(merged.get("auth_mode", "password_ref") or "password_ref")
        resolved = resolve_ssh_config_target(merged) if auth_mode == "ssh_config" else merged
        host = str(resolved.get("host", "")).strip()
        user = str(resolved.get("user", "")).strip()
        key_file = str(resolved.get("identity_ref", "")).strip()
        if not host or not user:
            return
        if not bool(merged.get("auto_connect_on_startup", False)):
            return
        password = resolve_ssh_password({"ssh": merged}) if auth_mode == "password_ref" else ""
        if auth_mode == "password_ref" and not password:
            return
        if auth_mode in {"key_file", "ssh_config"} and not key_file:
            return

        port = int(resolved.get("port", 22))
        timeout = int(resolved.get("timeout_sec", 5))

        try:
            result = ssh_connect(
                ip=host,
                port=port,
                user=user,
                password=password,
                key_file=key_file if auth_mode in {"key_file", "ssh_config"} else "",
                use_agent=auth_mode == "agent",
                timeout=timeout,
            )
            if not result.ok or result.client is None:
                if result.code == "SSH_HOST_KEY_UNTRUSTED":
                    raise RuntimeServiceError(
                        f"{result.code}: {result.message}",
                        status_code=409,
                    )
                raise RuntimeServiceError(result.message)

            def _reconnect():
                reconnect = ssh_connect(
                    ip=host,
                    port=port,
                    user=user,
                    password=password,
                    key_file=key_file if auth_mode in {"key_file", "ssh_config"} else "",
                    use_agent=auth_mode == "agent",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise SSHReconnectError(reconnect.message)
                return reconnect.client

            self._service_locator.ssh_service = SSHService(
                initial_client=result.client, connect_fn=_reconnect
            )
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is not None:
                server_id = str(server["serverId"])
                registry_entry = self._get_server_registry_entry(server_id)
                if not is_runner_manually_stopped(registry_entry):
                    self._save_runner_preparing_snapshot(
                        server_id=server_id,
                        message="Checking remote runner...",
                    )
                    self._ensure_runner_ready_in_background(server_id)
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
        except RuntimeServiceError as exc:
            message = str(exc).strip() or "SSH 自动连接失败"
            self._auto_connect_failed = True
            self._auto_connect_error = message
            self._auto_connect_notice_key = f"auto-connect-{int(time.time() * 1000)}"
            logger.warning("Startup SSH auto-connect failed: %s", message)
