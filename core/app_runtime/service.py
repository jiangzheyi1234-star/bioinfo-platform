"""Runtime service layer shared by API and desktop shell."""

import logging
import threading
import time
import uuid
from typing import Any, Optional

from config import (
    delete_ssh_password,
    get_config,
    normalize_ssh_config,
    resolve_ssh_config_target,
    resolve_ssh_password,
    save_config,
    store_runner_token,
    store_ssh_password,
)
from core.data.project_manager import ProjectInfo, ProjectManager
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHService, TerminalSession
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.runner_ops import RunnerOperationsMixin

logger = logging.getLogger(__name__)


class ServiceLocator:
    def __init__(
        self,
        ssh_service: Optional[SSHService] = None,
        remote_runner_manager: Optional[RemoteRunnerManager] = None,
    ):
        self._ssh = ssh_service
        self.remote_runner_manager = remote_runner_manager or RemoteRunnerManager()

    def initialize(self):
        return 0

    @property
    def ssh_service(self):
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh):
        if self._ssh and self._ssh is not ssh:
            self._ssh.close()
        self._ssh = ssh

    def shutdown(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None


class RuntimeService(RunnerOperationsMixin):
    def __init__(
        self,
        project_manager: Optional[ProjectManager] = None,
        service_locator: Optional[ServiceLocator] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._project_manager = project_manager or ProjectManager()
        self._service_locator = service_locator or ServiceLocator()
        self._initialized = False
        self._terminal_sessions: dict[str, TerminalSession] = {}
        self._runner_ensure_mutex = threading.Lock()
        self._runner_ensure_inflight: set[str] = set()
        self._connect_in_progress = False
        self._auto_connect_attempted = False
        self._auto_connect_in_progress = False
        self._auto_connect_failed = False
        self._auto_connect_error = ""
        self._auto_connect_notice_key = ""
        self._server_action_state: dict[str, dict[str, Any]] = {}

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._service_locator.initialize()
            self._initialized = True
            self._attempt_startup_auto_connect_in_background()

    def shutdown(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            self._close_all_terminal_sessions()
            self._service_locator.shutdown()
            self._initialized = False

    def list_projects(
        self, sort_by: str = "created_at", include_archived: bool = False
    ) -> list[dict]:
        with self._lock:
            self._ensure_initialized()
            projects = self._project_manager.list_projects()
            if not include_archived:
                projects = [p for p in projects if p.status != "archived"]
            return [self._project_to_dict(p) for p in projects]

    def get_current_project(self) -> Optional[dict]:
        with self._lock:
            self._ensure_initialized()
            p = self._project_manager.current_project
            return self._project_to_dict(p) if p else None

    def get_project(self, project_id: str) -> dict:
        with self._lock:
            self._ensure_initialized()
            project = next((p for p in self._project_manager.list_projects() if p.project_id == project_id), None)
            if project is None:
                raise RuntimeServiceError(f"Project not found: {project_id}")
            return self._project_to_dict(project)

    def create_project(
        self, name: str, description: str = "", open_after_create: bool = True
    ) -> dict:
        with self._lock:
            self._ensure_initialized()
            project_id = self._project_manager.create_project(name, description)
            if open_after_create:
                p = self._project_manager.open_project(project_id)
            else:
                p = [
                    p
                    for p in self._project_manager.list_projects()
                    if p.project_id == project_id
                ][0]
            return self._project_to_dict(p)

    def open_project(self, project_id: str) -> dict:
        with self._lock:
            self._ensure_initialized()
            p = self._project_manager.open_project(project_id)
            return self._project_to_dict(p)

    def update_project(self, project_id: str, patch: dict) -> dict:
        with self._lock:
            self._ensure_initialized()
            name = patch.get("name")
            desc = patch.get("description")
            p = self._project_manager.update_project(
                project_id, name=name, description=desc
            )
            return self._project_to_dict(p)

    def archive_project(self, project_id: str) -> dict:
        with self._lock:
            self._ensure_initialized()
            self._project_manager.archive_project(project_id)
            return {"project_id": project_id, "status": "archived"}

    def restore_project(self, project_id: str) -> dict:
        with self._lock:
            self._ensure_initialized()
            p = self._project_manager.restore_project(project_id)
            return self._project_to_dict(p)

    def delete_project(self, project_id: str) -> dict:
        with self._lock:
            self._ensure_initialized()
            self._project_manager.delete_project(project_id)
            return {"project_id": project_id, "status": "deleted"}

    def get_settings(self) -> dict:
        with self._lock:
            self._ensure_initialized()
            current = get_config()
            cfg = {**current}
            ssh_current = current.get("ssh", {})
            if isinstance(ssh_current, dict):
                ssh = normalize_ssh_config(ssh_current)
                cfg["ssh"] = ssh
            return cfg

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None:
                return []
            registry_entry = self._get_server_registry_entry(server["serverId"])
            ssh = self._service_locator.ssh_service if server["connected"] else None
        health = self._build_server_health(
            server_id=server["serverId"],
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )
        return [self._compose_server_payload(server=server, registry_entry=registry_entry, health=health)]

    def get_server(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            registry_entry = self._get_server_registry_entry(server_id)
            ssh = self._service_locator.ssh_service if server["connected"] else None
        health = self._build_server_health(
            server_id=server_id,
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )
        return self._compose_server_payload(server=server, registry_entry=registry_entry, health=health)

    def get_server_health(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            registry_entry = self._get_server_registry_entry(server_id)
            ssh = self._service_locator.ssh_service if server["connected"] else None
        return self._build_server_health(
            server_id=server_id,
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )

    def refresh_server_health(self, server_id: str) -> dict[str, Any]:
        return {"data": self.get_server_health(server_id)}

    def list_remote_listening_ports(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
        command = (
            "if command -v ss >/dev/null 2>&1; then "
            "printf 'COMMAND ss -lntup\\n'; ss -lntup 2>/dev/null || ss -lntu; "
            "elif command -v lsof >/dev/null 2>&1; then "
            "printf 'COMMAND lsof -nP -iTCP -iUDP\\n'; lsof -nP -iTCP -iUDP 2>/dev/null; "
            "elif command -v netstat >/dev/null 2>&1; then "
            "printf 'COMMAND netstat -tulpen\\n'; netstat -tulpen 2>/dev/null || netstat -tuln; "
            "else "
            "printf 'No ss, lsof, or netstat command is available on the remote host.\\n'; exit 127; "
            "fi"
        )
        try:
            exit_code, stdout, stderr = ssh.run(command, timeout=15)
        except Exception as exc:
            raise RuntimeServiceError(str(exc) or "failed to list remote listening ports") from exc
        output = (stdout or stderr or "").strip()
        return {
            "data": {
                "exitCode": exit_code,
                "ok": exit_code == 0,
                "output": output,
            }
        }

    def ensure_remote_runner_ready(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            ssh = self._ensure_ssh_connected()
            manager = self._service_locator.remote_runner_manager
            server_record = self._get_server_registry_entry(server_id)
        try:
            with self._runner_ensure_mutex:
                result = self._call_remote_runner(
                    manager.bootstrap,
                    server_id=server_id,
                    server=server,
                    ssh_service=ssh,
                    server_record=server_record,
                )
        except RuntimeServiceError as exc:
            bootstrap_metadata = {}
            cause = exc.__cause__
            if isinstance(cause, RemoteRunnerManagerError) and isinstance(cause.bootstrap_metadata, dict):
                bootstrap_metadata = dict(cause.bootstrap_metadata)
            failure_snapshot = self._build_runner_ensure_failure_snapshot(
                server_id=server_id,
                detail=str(exc),
            )
            with self._lock:
                self._save_server_registry_entry(
                    server_id,
                    {
                        "last_health_snapshot": failure_snapshot,
                        "bootstrap_metadata": bootstrap_metadata or None,
                    },
                )
            raise
        health = result["health"]
        ensured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            self._save_server_registry_entry(
                server_id,
                {
                    "bootstrap_version": result["bootstrap_version"],
                    "runner_mode": result["runner_mode"],
                    "tunnel_port": result["tunnel_port"],
                    "service_port": result["service_port"],
                    "token_ref": result["token_ref"],
                    "last_health_snapshot": health,
                    "bootstrap_metadata": dict(result.get("bootstrap_metadata") or {}),
                    "runner_ensured_at": ensured_at,
                },
            )
        if not bool((health.get("ready") or {}).get("ok")):
            raise RuntimeServiceError(
                str((health.get("ready") or {}).get("message") or "Remote runner control plane is not ready.")
            )
        runner = self._compose_runner_payload(
            registry_entry={
                "bootstrap_version": result["bootstrap_version"],
                "runner_mode": result["runner_mode"],
                "tunnel_port": result["tunnel_port"],
                "service_port": result["service_port"],
                "bootstrap_metadata": dict(result.get("bootstrap_metadata") or {}),
            },
            health=health,
        )
        return {"data": {"serverId": server_id, "runner": runner, "health": health}}

    def accept_server_host_key(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            state = self._server_action_state.setdefault(server_id, {})
            state["host_key_trusted"] = True
            return {"data": {"serverId": server_id, "hostKeyTrusted": True}}

    def rotate_server_token(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            record = self._get_server_registry_entry(server_id)
            if record.get("bootstrap_version"):
                ssh = self._ensure_ssh_connected()
                manager = self._service_locator.remote_runner_manager
            else:
                ssh = None
                manager = None
        rotated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if record.get("bootstrap_version"):
            result = self._call_remote_runner(
                manager.rotate_token,
                server_id=server_id,
                server=server,
                ssh_service=ssh,
                server_record=record,
            )
            token_ref = result["token_ref"]
        else:
            token_ref = store_runner_token(server_id=server_id, token=uuid.uuid4().hex)
        with self._lock:
            self._save_server_registry_entry(
                server_id,
                {
                    "token_ref": token_ref,
                    "token_rotated_at": rotated_at,
                },
            )
        return {"data": {"serverId": server_id, "tokenRotated": True, "rotatedAt": rotated_at}}

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            self._ensure_initialized()
            current = get_config()
            merged = self._merge_patch(current, patch)
            if isinstance(merged.get("ssh"), dict):
                normalized_ssh = normalize_ssh_config(merged["ssh"])
                merged["ssh"] = normalized_ssh
            save_config(merged)
            return self.get_settings()

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
            merged = normalize_ssh_config(get_config().get("ssh", {}))

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

            current = get_config()
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
                    raise RuntimeError(r.message)
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
                save_config(self._merge_patch(current, {"ssh": persisted}))
                self._auto_connect_failed = False
                self._auto_connect_error = ""
                self._auto_connect_notice_key = ""
                status = self._get_ssh_status_unlocked()
                server = self._build_primary_server_identity(ssh_status=status)
                if server is not None:
                    server_id = str(server["serverId"])
                    self._save_runner_preparing_snapshot(
                        server_id=server_id,
                        message="Checking remote runner...",
                    )
                    status = self._get_ssh_status_unlocked()
            if server is not None:
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
            current = get_config()
            ssh_cfg = normalize_ssh_config(current.get("ssh", {}))
            ssh_cfg["auto_connect_on_startup"] = False
            save_config(self._merge_patch(current, {"ssh": ssh_cfg}))
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            return self._get_ssh_status_unlocked()

    def test_ssh_connection(self, patch: Optional[dict] = None) -> dict:
        with self._lock:
            self._ensure_initialized()
            merged = normalize_ssh_config(get_config().get("ssh", {}))
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
        ok = all(s.status == "ok" for s in steps)
        status = self.get_ssh_status()
        return {
            "ok": ok,
            "message": "SSH diagnostics passed" if ok else "SSH diagnostics failed",
            "steps": [
                {"name": s.name, "status": s.status, "message": s.message}
                for s in steps
            ],
            "status": status,
        }

    def create_terminal_session(self, cols: int = 120, rows: int = 28) -> dict:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
            session = ssh.open_terminal_session(cols=cols, rows=rows)
            self._terminal_sessions[session.session_id] = session
            return session.snapshot(cursor=0)

    def get_terminal_session(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            return session

    def send_terminal_input(self, session_id: str, data: str) -> dict:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.send(data)
            return {"session_id": session_id, "accepted": True}

    def resize_terminal_session(self, session_id: str, cols: int, rows: int) -> dict:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.resize(cols, rows)
            return {"session_id": session_id, "cols": cols, "rows": rows}

    def close_terminal_session(self, session_id: str) -> dict:
        with self._lock:
            session = self._terminal_sessions.pop(session_id, None)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.close(message="终端会话已结束")
            return {"session_id": session_id, "closed": True}

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeServiceError("not initialized")

    def _ensure_ssh_connected(self) -> SSHService:
        ssh = self._service_locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            raise RuntimeServiceError("SSH disconnected")
        return ssh

    def _attempt_startup_auto_connect(self) -> None:
        if self._auto_connect_attempted:
            return
        self._auto_connect_attempted = True

        merged = normalize_ssh_config(get_config().get("ssh", {}))
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
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            self._service_locator.ssh_service = SSHService(
                initial_client=result.client, connect_fn=_reconnect
            )
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is not None:
                server_id = str(server["serverId"])
                self._save_runner_preparing_snapshot(
                    server_id=server_id,
                    message="Checking remote runner...",
                )
                self._ensure_runner_ready_in_background(server_id)
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
        except Exception as exc:
            message = str(exc).strip() or "SSH 自动连接失败"
            self._auto_connect_failed = True
            self._auto_connect_error = message
            self._auto_connect_notice_key = f"auto-connect-{int(time.time() * 1000)}"
            logger.warning("Startup SSH auto-connect failed: %s", message)

    def _close_all_terminal_sessions(self) -> None:
        for session in list(self._terminal_sessions.values()):
            try:
                session.close(message="终端会话已结束")
            except Exception:
                pass
        self._terminal_sessions.clear()

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
            except Exception as exc:
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

    @staticmethod
    def _project_to_dict(p: ProjectInfo) -> dict:
        return {
            "project_id": p.project_id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "created_at": p.created_at,
            "last_opened_at": getattr(p, "last_opened_at", 0),
            "remote_base": getattr(p, "remote_base", ""),
        }

    def _get_server_registry(self) -> dict[str, dict[str, Any]]:
        current = get_config()
        raw = current.get("servers", {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _get_server_registry_entry(self, server_id: str) -> dict[str, Any]:
        registry = self._get_server_registry()
        entry = registry.get(server_id, {})
        return dict(entry) if isinstance(entry, dict) else {}

    def _save_server_registry_entry(self, server_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = get_config()
        registry = self._get_server_registry()
        entry = dict(registry.get(server_id, {}) or {})
        entry.update({key: value for key, value in patch.items() if value is not None})
        registry[server_id] = entry
        current["servers"] = registry
        save_config(current)
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
            try:
                health = self._call_remote_runner(
                    manager.get_health,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
                if bool((health.get("ready") or {}).get("ok")):
                    return server_id, ssh, record
            except RuntimeServiceError:
                pass
        self.ensure_remote_runner_ready(server_id)
        record = self._get_server_registry_entry(server_id)
        return server_id, ssh, record

    def _build_primary_server_identity(self, *, ssh_status: dict[str, Any]) -> Optional[dict[str, Any]]:
        host = str(ssh_status.get("host", "") or "").strip()
        alias = str(ssh_status.get("ssh_host_alias", "") or "").strip()
        user = str(ssh_status.get("user", "") or "").strip()
        port = int(ssh_status.get("port", 22) or 22)
        if not host and not alias:
            return None
        stable_key = f"{host or alias}:{port}:{user or 'unknown'}"
        server_id = f"srv_{uuid.uuid5(uuid.NAMESPACE_DNS, stable_key).hex[:12]}"
        return {
            "serverId": server_id,
            "label": alias or host,
            "host": host,
            "port": port,
            "user": user,
            "connected": bool(ssh_status.get("connected")),
        }

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

    @staticmethod
    def _get_saved_readiness_snapshot(
        *,
        server_id: str,
        registry_entry: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        snapshot = registry_entry.get("last_health_snapshot")
        if not isinstance(snapshot, dict):
            return None
        reason_code = str(snapshot.get("reasonCode") or "").strip()
        ready = snapshot.get("ready")
        startup = snapshot.get("startup")
        live = snapshot.get("live")
        if not reason_code or not isinstance(ready, dict) or not isinstance(startup, dict) or not isinstance(live, dict):
            return None
        return {
            "serverId": str(snapshot.get("serverId") or server_id),
            "startup": startup,
            "live": live,
            "ready": ready,
            "workflowRuntime": snapshot.get("workflowRuntime") if isinstance(snapshot.get("workflowRuntime"), dict) else {},
            "pipelineRegistry": snapshot.get("pipelineRegistry") if isinstance(snapshot.get("pipelineRegistry"), dict) else {},
            "reasonCode": reason_code,
            "checkedAt": str(snapshot.get("checkedAt") or ""),
        }

    @classmethod
    def _build_runner_ensure_failure_snapshot(
        cls,
        *,
        server_id: str,
        detail: str,
    ) -> dict[str, Any]:
        reason_code, ready_message, live_message, workflow_runtime, pipeline_registry = cls._classify_runner_ensure_failure(
            detail
        )
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "serverId": server_id,
            "startup": {"ok": False, "message": ready_message},
            "live": {"ok": False, "message": live_message},
            "ready": {"ok": False, "message": ready_message},
            "workflowRuntime": workflow_runtime,
            "pipelineRegistry": pipeline_registry,
            "reasonCode": reason_code,
            "checkedAt": checked_at,
        }

    @staticmethod
    def _classify_runner_ensure_failure(detail: str) -> tuple[str, str, str, dict[str, Any], dict[str, Any]]:
        message = str(detail or "").strip() or "remote runner ensure failed"
        lowered = message.lower()
        workflow_runtime: dict[str, Any] = {}
        pipeline_registry: dict[str, Any] = {}
        if (
            "verify workflow runtime prerequisites" in lowered
            or "workflow runtime" in lowered
            or "conda/mamba is required" in lowered
            or "micromamba" in lowered
            or "snakemake command not configured" in lowered
        ):
            ready_message = f"Remote workflow runtime is unavailable: {message}"
            workflow_runtime = {"ok": False, "message": ready_message}
            return "WORKFLOW_RUNTIME_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        if "pipeline registry" in lowered or "registered pipeline snakefile is missing" in lowered:
            ready_message = f"Remote pipeline registry is unavailable: {message}"
            pipeline_registry = {"ok": False, "message": ready_message}
            return "PIPELINE_REGISTRY_NOT_READY", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        if "bootstrap canary failed" in lowered or "canary failed" in lowered:
            ready_message = f"Remote runner bootstrap canary failed: {message}"
            return "RUNNER_CANARY_FAILED", ready_message, "Remote runner process failed post-start validation.", workflow_runtime, pipeline_registry
        if "rollback did not restore previous release" in lowered or "rollback failed" in lowered:
            ready_message = f"Remote runner rollback failed after activation error: {message}"
            return "RUNNER_ROLLBACK_FAILED", ready_message, "Remote runner process failed during rollback recovery.", workflow_runtime, pipeline_registry
        if "python3 required" in lowered:
            ready_message = f"Remote host is missing python3 required for runner setup: {message}"
            return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        if "install remote runner dependencies" in lowered:
            if "python3" in lowered and (
                "not found" in lowered or "command not found" in lowered or "no such file" in lowered
            ):
                ready_message = f"Remote host is missing python3 required for runner setup: {message}"
                return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
            ready_message = (
                "Remote runner dependency installation failed while setting up the Python environment: "
                f"{message}"
            )
            return "SERVICE_RUNTIME_SETUP_FAILED", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        if "start remote runner service" in lowered or "service failed to start" in lowered:
            ready_message = f"Remote runner service failed to start: {message}"
            return "SERVICE_START_FAILED", ready_message, "Remote runner process failed to stay alive.", workflow_runtime, pipeline_registry
        if "python3" in lowered and ("not found" in lowered or "command not found" in lowered):
            ready_message = f"Remote host is missing python3 required for runner setup: {message}"
            return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        ready_message = f"Remote runner setup failed: {message}"
        return "RUNNER_SETUP_FAILED", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry

    def _compose_server_payload(
        self,
        *,
        server: dict[str, Any],
        registry_entry: dict[str, Any],
        health: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **server,
            "ready": bool(health["ready"]["ok"]),
            "reasonCode": health.get("reasonCode", ""),
            "message": health["ready"]["message"],
            "health": health,
            "runner": self._compose_runner_payload(registry_entry=registry_entry, health=health),
            "runnerVersion": registry_entry.get("bootstrap_version", ""),
            "runnerMode": registry_entry.get("runner_mode", ""),
        }

    @staticmethod
    def _compose_runner_payload(
        *,
        registry_entry: dict[str, Any],
        health: dict[str, Any],
    ) -> dict[str, Any]:
        ready = bool((health.get("ready") or {}).get("ok"))
        metadata = registry_entry.get("bootstrap_metadata") if isinstance(registry_entry.get("bootstrap_metadata"), dict) else {}
        deployment_action = str((metadata or {}).get("deployment_action") or "")
        reason_code = str(health.get("reasonCode") or "")
        if ready:
            state = "ready"
        elif str(health.get("state") or "") in {"preparing", "recovering"}:
            state = str(health.get("state") or "")
        elif reason_code:
            state = "repair_needed"
        else:
            state = "preparing"
        return {
            "state": state,
            "ready": ready,
            "message": str((health.get("ready") or {}).get("message") or ""),
            "reasonCode": reason_code,
            "version": registry_entry.get("bootstrap_version", ""),
            "runnerMode": registry_entry.get("runner_mode", ""),
            "deploymentAction": deployment_action,
            "servicePort": registry_entry.get("service_port"),
            "tunnelPort": registry_entry.get("tunnel_port"),
            "bootstrapMetadata": metadata,
        }

    def _get_ssh_status_unlocked(self) -> dict[str, Any]:
        ssh = self._service_locator.ssh_service
        connected = ssh is not None and getattr(ssh, "is_connected", False)
        cfg = normalize_ssh_config(get_config().get("ssh", {}))
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

    @staticmethod
    def _merge_patch(current: dict, patch: dict) -> dict:
        merged = dict(current)
        for section, value in patch.items():
            if section == "version":
                continue
            if (
                section in merged
                and isinstance(merged[section], dict)
                and isinstance(value, dict)
            ):
                merged[section] = {**merged[section], **value}
            else:
                merged[section] = value
        return merged
