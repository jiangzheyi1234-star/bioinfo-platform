"""Runtime service layer shared by API and desktop shell."""

import logging
import threading
import time
from typing import Any, Optional

from config import get_config, resolve_ssh_password, save_config
from core.data.project_manager import ProjectInfo, ProjectManager
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHService, TerminalSession

logger = logging.getLogger(__name__)


class RuntimeServiceError(RuntimeError):
    pass


class ServiceLocator:
    def __init__(self, ssh_service: Optional[SSHService] = None):
        self._ssh = ssh_service

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


class RuntimeService:
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
        self._auto_connect_attempted = False
        self._auto_connect_failed = False
        self._auto_connect_error = ""
        self._auto_connect_notice_key = ""

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._service_locator.initialize()
            self._initialized = True
            self._attempt_startup_auto_connect()

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
                ssh = {**ssh_current}
                ssh["password"] = ""
                cfg["ssh"] = ssh
            return cfg

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            self._ensure_initialized()
            current = get_config()
            merged = self._merge_patch(current, patch)
            save_config(merged)
            return self.get_settings()

    def get_ssh_status(self) -> dict:
        with self._lock:
            self._ensure_initialized()
            ssh = self._service_locator.ssh_service
            connected = ssh is not None and getattr(ssh, "is_connected", False)
            cfg = get_config().get("ssh", {})
            return {
                "connected": connected,
                "host": cfg.get("host", ""),
                "port": cfg.get("port", 22),
                "user": cfg.get("user", ""),
                "use_key": cfg.get("use_key", False),
                "key_file": cfg.get("key_file", ""),
                "has_password": bool(cfg.get("password")),
                "timeout_sec": cfg.get("timeout_sec", 5),
                "auto_connect_on_startup": bool(cfg.get("auto_connect_on_startup", False)),
                "auto_connect_attempted": self._auto_connect_attempted,
                "auto_connect_failed": self._auto_connect_failed,
                "auto_connect_error": self._auto_connect_error,
                "message": "SSH connected" if connected else "SSH disconnected",
            }

    def connect_ssh(self, patch: Optional[dict] = None) -> dict:
        with self._lock:
            self._ensure_initialized()
            cfg = get_config().get("ssh", {})
            if isinstance(cfg, dict):
                merged = dict(cfg)
            else:
                merged = {}

            if patch:
                for k in (
                    "host",
                    "port",
                    "user",
                    "password",
                    "use_key",
                    "key_file",
                    "timeout_sec",
                ):
                    if k in patch and patch[k] is not None:
                        merged[k] = patch[k]

            host = str(merged.get("host", "")).strip()
            port = int(merged.get("port", 22))
            user = str(merged.get("user", "")).strip()
            password = (
                str(patch.get("password", ""))
                if patch and "password" in patch
                else resolve_ssh_password(merged)
            )
            use_key = bool(merged.get("use_key", False))
            key_file = str(merged.get("key_file", "")).strip()
            timeout = int(merged.get("timeout_sec", 5))

            if not host or not user:
                raise RuntimeServiceError("ssh.host and ssh.user required")

            result = ssh_connect(
                ip=host,
                port=port,
                user=user,
                password=password,
                key_file=key_file,
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
                    key_file=key_file,
                    timeout=timeout,
                )
                if not r.ok:
                    raise RuntimeError(r.message)
                return r.client

            self._service_locator.ssh_service = SSHService(
                initial_client=result.client, connect_fn=_reconnect
            )
            current = get_config()
            persisted = {
                **merged,
                "host": host,
                "port": port,
                "user": user,
                "password": "",
                "use_key": use_key,
                "key_file": key_file,
                "timeout_sec": timeout,
                "auto_connect_on_startup": bool(use_key and key_file),
            }
            save_config(self._merge_patch(current, {"ssh": persisted}))
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            return self.get_ssh_status()

    def disconnect_ssh(self) -> dict:
        with self._lock:
            self._ensure_initialized()
            self._close_all_terminal_sessions()
            self._service_locator.ssh_service = None
            current = get_config()
            ssh_cfg = dict(current.get("ssh", {})) if isinstance(current.get("ssh", {}), dict) else {}
            ssh_cfg["auto_connect_on_startup"] = False
            save_config(self._merge_patch(current, {"ssh": ssh_cfg}))
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            return self.get_ssh_status()

    def test_ssh_connection(self, patch: Optional[dict] = None) -> dict:
        with self._lock:
            self._ensure_initialized()
            cfg = get_config().get("ssh", {})
            merged = dict(cfg) if isinstance(cfg, dict) else {}
            if patch:
                for k in ("host", "port", "user", "password", "use_key", "key_file"):
                    if k in patch and patch[k] is not None:
                        merged[k] = patch[k]

            steps = run_diagnostics(
                ip=merged.get("host", ""),
                port=int(merged.get("port", 22)),
                user=merged.get("user", ""),
                password=merged.get("password", "")
                if not merged.get("use_key")
                else "",
                key_file=merged.get("key_file", "") if merged.get("use_key") else "",
            )
            ok = all(s.status == "ok" for s in steps)
            return {
                "ok": ok,
                "message": "SSH diagnostics passed" if ok else "SSH diagnostics failed",
                "steps": [
                    {"name": s.name, "status": s.status, "message": s.message}
                    for s in steps
                ],
                "status": self.get_ssh_status(),
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

        cfg = get_config().get("ssh", {})
        merged = dict(cfg) if isinstance(cfg, dict) else {}
        host = str(merged.get("host", "")).strip()
        user = str(merged.get("user", "")).strip()
        use_key = bool(merged.get("use_key", False))
        key_file = str(merged.get("key_file", "")).strip()
        if not host or not user or not use_key or not key_file:
            return
        if not bool(merged.get("auto_connect_on_startup", False)):
            return

        port = int(merged.get("port", 22))
        password = ""
        timeout = int(merged.get("timeout_sec", 5))

        try:
            result = ssh_connect(
                ip=host,
                port=port,
                user=user,
                password=password,
                key_file=key_file,
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
                    key_file=key_file,
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            self._service_locator.ssh_service = SSHService(
                initial_client=result.client, connect_fn=_reconnect
            )
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
