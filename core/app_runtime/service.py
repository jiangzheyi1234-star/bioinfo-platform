"""Runtime service layer shared by API and desktop shell."""

from __future__ import annotations

import json
import logging
import shlex
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from config import (
    CONFIG_VERSION,
    default_settings_schema,
    get_config,
    resolve_ssh_password,
    save_config,
)
from core.data.project_manager import ProjectInfo, ProjectManager
from core.runtime_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHService, TerminalSession
from core.service_locator import ServiceLocator
from core.utils import get_app_root

logger = logging.getLogger(__name__)


class RuntimeServiceError(RuntimeError):
    """Raised when runtime actions cannot be completed safely."""


def _parse_json_field(field_name: str, raw_value: Any, *, execution_id: str) -> Any:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeServiceError(
            f"Execution {execution_id} has invalid JSON field '{field_name}': {exc}"
        ) from exc


class RuntimeService:
    """Thread-safe facade around ProjectManager + ServiceLocator."""

    def __init__(
        self,
        project_manager: Optional[ProjectManager] = None,
        service_locator: Optional[ServiceLocator] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._project_manager = project_manager or ProjectManager()
        self._service_locator = service_locator or ServiceLocator()
        self._initialized = False
        self._events: deque[dict[str, Any]] = deque(maxlen=2000)
        self._event_seq = 0
        self._auto_connect_attempted = False
        self._auto_connect_failed = False
        self._auto_connect_error = ""
        self._auto_connect_notice_key = ""
        self._terminal_sessions: dict[str, TerminalSession] = {}

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
            self._close_all_terminal_sessions(
                message="终端会话已结束", drop_sessions=True
            )
            self._service_locator.shutdown()
            self._initialized = False

    def list_projects(
        self, *, sort_by: str = "created_at", include_archived: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            projects = self._project_manager.list_projects(sort_by=sort_by)
            if not include_archived:
                projects = [
                    project for project in projects if project.status != "archived"
                ]
            return [self._project_to_dict(project) for project in projects]

    def get_current_project(self) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            project = self._project_manager.current_project
            if project is None:
                return None
            return self._project_to_dict(project)

    def create_project(
        self, *, name: str, description: str = "", open_after_create: bool = True
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            project_id = self._project_manager.create_project(
                name=name, description=description
            )
            if open_after_create:
                project = self._project_manager.open_project(project_id)
            else:
                matches = [
                    p
                    for p in self._project_manager.list_projects()
                    if p.project_id == project_id
                ]
                if not matches:
                    raise RuntimeServiceError(
                        f"Created project cannot be found: {project_id}"
                    )
                project = matches[0]
            return self._project_to_dict(project)

    def update_project(
        self, *, project_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if not isinstance(patch, dict):
                raise RuntimeServiceError("project patch must be an object")

            updates: dict[str, Any] = {}
            if "name" in patch:
                name = str(patch.get("name") or "").strip()
                if not name:
                    raise RuntimeServiceError("project name cannot be empty")
                updates["name"] = name
            if "description" in patch:
                updates["description"] = str(patch.get("description") or "").strip()
            if not updates:
                raise RuntimeServiceError("project patch is empty")

            project = self._project_manager.update_project(project_id, **updates)
            return self._project_to_dict(project)

    def archive_project(self, *, project_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            self._project_manager.archive_project(project_id)
            return {"project_id": project_id, "status": "archived"}

    def restore_project(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            project = self._project_manager.restore_project(project_id)
            return self._project_to_dict(project)

    def delete_project(self, *, project_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            self._project_manager.delete_project(project_id)
            return {"project_id": project_id, "status": "deleted"}

    def open_project(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            project = self._project_manager.open_project(project_id)
            return self._project_to_dict(project)

    def read_app_log(self, *, tail_lines: int = 200) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            log_path = get_app_root() / "logs" / "app.log"
            if not log_path.exists():
                return {"path": str(log_path), "lines": []}

            lines = self._tail_file(log_path, max_lines=tail_lines)
            return {"path": str(log_path), "lines": lines}

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            current = get_config()
            sanitized = dict(current)
            ssh = (
                dict(current.get("ssh", {}))
                if isinstance(current.get("ssh"), dict)
                else {}
            )
            ssh["password"] = ""
            ssh.pop("password_ref", None)
            sanitized["ssh"] = ssh
            return sanitized

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if not isinstance(patch, dict):
                raise RuntimeServiceError("settings patch must be an object")
            current = get_config()
            merged = self._merge_settings_patch(current, patch)
            save_config(merged)
            updated = get_config()
            ssh = (
                dict(updated.get("ssh", {}))
                if isinstance(updated.get("ssh"), dict)
                else {}
            )
            ssh["password"] = ""
            ssh.pop("password_ref", None)
            updated["ssh"] = ssh
            return updated

    def get_resolved_runtime_state(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            current = get_config()
            runtime = (
                current.get("runtime", {})
                if isinstance(current.get("runtime"), dict)
                else {}
            )
            resolved = (
                runtime.get("resolved", {})
                if isinstance(runtime.get("resolved"), dict)
                else {}
            )
            return dict(resolved)

    def update_resolved_runtime_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if not isinstance(patch, dict):
                raise RuntimeServiceError("runtime.resolved patch must be an object")
            current = get_config()
            merged = self._merge_settings_patch(
                current, {"runtime": {"resolved": patch}}
            )
            save_config(merged)
            updated = get_config()
            runtime = (
                updated.get("runtime", {})
                if isinstance(updated.get("runtime"), dict)
                else {}
            )
            resolved = (
                runtime.get("resolved", {})
                if isinstance(runtime.get("resolved"), dict)
                else {}
            )
            return dict(resolved)

    def get_ssh_status(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_settings = self._resolve_ssh_settings()
            ssh_service = self._service_locator.ssh_service
            connected = bool(
                ssh_service is not None and getattr(ssh_service, "is_connected", False)
            )
            configured = bool(ssh_settings["host"] and ssh_settings["user"])
            return {
                "configured": configured,
                "connected": connected,
                "host": ssh_settings["host"],
                "port": ssh_settings["port"],
                "user": ssh_settings["user"],
                "use_key": ssh_settings["use_key"],
                "key_file": ssh_settings["key_file"],
                "has_password": bool(ssh_settings["password"]),
                "message": "SSH connected" if connected else "SSH disconnected",
                "auto_connect_attempted": self._auto_connect_attempted,
                "auto_connect_failed": self._auto_connect_failed,
                "auto_connect_error": self._auto_connect_error,
                "auto_connect_notice_key": self._auto_connect_notice_key,
            }

    def connect_ssh(self, patch: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_settings = self._resolve_ssh_settings(patch)
            timeout = self._resolve_ssh_timeout(patch)
            result = ssh_connect(
                ip=ssh_settings["host"],
                port=ssh_settings["port"],
                user=ssh_settings["user"],
                password=ssh_settings["password"],
                key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                timeout=timeout,
            )
            if not result.ok or result.client is None:
                raise RuntimeServiceError(result.message)

            def _connect_fn() -> Any:
                reconnect = ssh_connect(
                    ip=ssh_settings["host"],
                    port=ssh_settings["port"],
                    user=ssh_settings["user"],
                    password=ssh_settings["password"],
                    key_file=ssh_settings["key_file"]
                    if ssh_settings["use_key"]
                    else "",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            ssh_service = SSHService(
                initial_client=result.client, connect_fn=_connect_fn
            )
            self._service_locator.ssh_service = ssh_service
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            status = self.get_ssh_status()
            status["message"] = result.message
            return status

    def disconnect_ssh(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._close_all_terminal_sessions(
                message="SSH 已断开，终端会话已结束", drop_sessions=False
            )
            self._service_locator.ssh_service = None
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            status = self.get_ssh_status()
            status["message"] = "SSH disconnected"
            return status

    def create_terminal_session(
        self, *, cols: int = 120, rows: int = 28
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
            session = ssh.open_terminal_session(cols=cols, rows=rows)
            self._terminal_sessions[session.session_id] = session
            return session.snapshot(cursor=0)

    def get_terminal_session(self, *, session_id: str) -> TerminalSession:
        with self._lock:
            self._ensure_initialized()
            return self._get_terminal_session(session_id)

    def send_terminal_input(self, *, session_id: str, data: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._get_terminal_session(session_id)
            session.send(data)
            return {"session_id": session_id, "accepted": True}

    def resize_terminal_session(
        self, *, session_id: str, cols: int, rows: int
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._get_terminal_session(session_id)
            session.resize(cols=cols, rows=rows)
            return {
                "session_id": session_id,
                "accepted": True,
                "cols": cols,
                "rows": rows,
            }

    def close_terminal_session(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._terminal_sessions.pop(session_id, None)
            if session is None:
                raise RuntimeServiceError(f"unknown terminal session: {session_id}")
            session.close(message="终端会话已结束", connected=False)
            return {"session_id": session_id, "closed": True}

    def test_ssh_connection(
        self, patch: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_settings = self._resolve_ssh_settings(patch)
            steps = run_diagnostics(
                ip=ssh_settings["host"],
                port=ssh_settings["port"],
                user=ssh_settings["user"],
                password=ssh_settings["password"]
                if not ssh_settings["use_key"]
                else "",
                key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                existing_client=getattr(
                    self._service_locator.ssh_service, "_client", lambda: None
                )(),
            )
            ok = all(step.status == "ok" for step in steps)
            return {
                "ok": ok,
                "message": "SSH diagnostics passed" if ok else "SSH diagnostics failed",
                "steps": [
                    {"name": step.name, "status": step.status, "message": step.message}
                    for step in steps
                ],
                "status": self.get_ssh_status(),
            }

    def list_runtime_events(
        self, *, after_seq: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if limit <= 0:
                raise RuntimeServiceError("limit must be positive")
            if limit > 1000:
                raise RuntimeServiceError("limit too large; max is 1000")
            items = [evt for evt in self._events if int(evt.get("seq", 0)) > after_seq]
            sliced = items[:limit]
            return {
                "items": sliced,
                "latest_seq": self._event_seq,
            }

    def _ensure_ssh_connected(self) -> SSHService:
        ssh = self._service_locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            raise RuntimeServiceError("SSH disconnected")
        return ssh

    def _get_terminal_session(self, session_id: str) -> TerminalSession:
        session = self._terminal_sessions.get(session_id)
        if session is None:
            raise RuntimeServiceError(f"unknown terminal session: {session_id}")
        return session

    def _close_all_terminal_sessions(
        self, *, message: str, drop_sessions: bool
    ) -> None:
        for session in list(self._terminal_sessions.values()):
            try:
                session.close(message=message, connected=False)
            except Exception:
                logger.debug(
                    "Failed to close terminal session %s",
                    session.session_id,
                    exc_info=True,
                )
        if drop_sessions:
            self._terminal_sessions.clear()

    def _remember_managed_conda(self, conda_executable: str) -> None:
        normalized = str(conda_executable or "").strip()
        if not normalized or not is_managed_conda_executable(normalized):
            return
        self._service_locator.conda_executable = normalized
        current = get_config()
        linux = current.get("linux", {})
        current_value = (
            str(linux.get("conda_executable", "") or "").strip()
            if isinstance(linux, dict)
            else ""
        )
        if current_value == normalized:
            return
        merged = self._merge_settings_patch(
            current, {"linux": {"conda_executable": normalized}}
        )
        save_config(merged)

    @staticmethod
    def _normalize_job_stage(
        *,
        status: str,
        exit_code: str,
        session_alive: bool,
        heartbeat: str = "",
    ) -> str:
        normalized = str(status or "").strip().upper()
        normalized_exit = str(exit_code or "").strip()
        if normalized == "DONE" or normalized_exit == "0":
            return "done"
        if normalized == "FAILED":
            return "failed"
        if normalized == "RUNNING" or session_alive:
            return "running"
        if normalized_exit and normalized_exit != "0":
            return "failed"
        if heartbeat.strip():
            return "running"
        return "idle"

    @staticmethod
    def _build_job_snapshot(
        *,
        job_id: str,
        stage: str,
        raw_status: dict[str, Any],
        log_text: str,
        progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log_lines = [line for line in str(log_text or "").splitlines() if line.strip()]
        ok = stage == "done"
        message = "" if ok else RuntimeService._extract_job_failure_message(log_lines)
        return {
            "job_id": job_id,
            "status": stage,
            "done": stage in {"done", "failed"},
            "ok": ok,
            "exit_code": str(raw_status.get("exit_code") or ""),
            "heartbeat": str(raw_status.get("heartbeat") or ""),
            "log_text": str(log_text or ""),
            "log_lines": log_lines,
            "progress": progress or {},
            "message": message,
        }

    @staticmethod
    def _extract_job_failure_message(log_lines: list[str]) -> str:
        for line in log_lines:
            stripped = str(line or "").strip()
            if not stripped:
                continue
            if stripped.startswith("STEP="):
                continue
            if "=" in stripped:
                key, value = stripped.split("=", 1)
                normalized_key = key.strip().upper()
                if normalized_key in {
                    "FORMAT",
                    "PROFILE_KIND",
                    "STATUS",
                    "MODE",
                    "PRESENT",
                    "INSTALLED",
                    "NEEDS_SYSTEM",
                    "SKIPPED",
                    "PREPARED_DIRS",
                }:
                    continue
                if value.strip():
                    return value.strip()
                continue
            return stripped
        return log_lines[-1] if log_lines else ""

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeServiceError("RuntimeService is not initialized")

    def _ensure_project_open(self, project_id: str) -> None:
        if not str(project_id or "").strip():
            raise RuntimeServiceError("project_id is required")
        current = self._project_manager.current_project
        if current is not None and current.project_id == project_id:
            return
        self._project_manager.open_project(project_id)

    def _assert_task_exists(self, *, project_id: str, task_id: str) -> None:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise RuntimeServiceError("task_id is required")
        row = self._project_manager.db.execute(
            "SELECT task_id FROM tasks WHERE project_id = ? AND task_id = ?",
            (project_id, normalized_task_id),
        ).fetchone()
        if row is None:
            raise RuntimeServiceError(f"Task not found: {normalized_task_id}")

    @staticmethod
    def _project_to_dict(project: ProjectInfo) -> dict[str, Any]:
        return {
            "project_id": project.project_id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "created_at": project.created_at,
            "last_opened_at": project.last_opened_at,
            "remote_base": project.remote_base,
        }

    @staticmethod
    def _normalize_execution_row(row: dict[str, Any]) -> dict[str, Any]:
        execution_id = str(row.get("execution_id") or "")
        if not execution_id:
            raise RuntimeServiceError("Invalid execution row: missing execution_id")

        normalized = dict(row)
        normalized["parameters"] = _parse_json_field(
            "parameters",
            normalized.get("parameters"),
            execution_id=execution_id,
        )
        return normalized

    @staticmethod
    def _tail_file(path: Path, *, max_lines: int) -> list[str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if max_lines <= 0:
            return []
        lines = text.splitlines()
        return lines[-max_lines:]

    @staticmethod
    def _merge_settings_patch(
        current: dict[str, Any], patch: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(current)
        defaults = default_settings_schema()
        allowed_sections = {"ssh", "linux", "databases", "blast", "ncbi", "runtime"}
        for section, value in patch.items():
            if section == "version":
                continue
            if section not in allowed_sections:
                raise RuntimeServiceError(f"unknown settings section: {section}")
            if not isinstance(value, dict):
                raise RuntimeServiceError(
                    f"settings section '{section}' must be an object"
                )
            allowed_keys = set(defaults[section].keys())
            for key in value:
                if key not in allowed_keys:
                    raise RuntimeServiceError(f"unknown settings key: {section}.{key}")
            existing = merged.get(section, {})
            if not isinstance(existing, dict):
                existing = {}
            next_section = dict(existing)
            if section == "runtime" and "resolved" in value:
                resolved_defaults = defaults["runtime"].get("resolved", {})
                resolved_patch = value.get("resolved")
                if not isinstance(resolved_patch, dict):
                    raise RuntimeServiceError(
                        "settings key runtime.resolved must be an object"
                    )
                unknown_runtime_resolved = set(resolved_patch.keys()) - set(
                    resolved_defaults.keys()
                )
                if unknown_runtime_resolved:
                    bad = sorted(str(item) for item in unknown_runtime_resolved)
                    raise RuntimeServiceError(
                        f"unknown settings key: runtime.resolved.{bad[0]}"
                    )
                existing_resolved = next_section.get("resolved", {})
                if not isinstance(existing_resolved, dict):
                    existing_resolved = {}
                next_resolved = dict(existing_resolved)
                next_resolved.update(resolved_patch)
                next_section["resolved"] = next_resolved
                value = {k: v for k, v in value.items() if k != "resolved"}
            next_section.update(value)
            merged[section] = next_section

        if "version" in patch:
            try:
                version = int(patch["version"])
            except (TypeError, ValueError) as exc:
                raise RuntimeServiceError(
                    f"invalid settings version: {patch['version']}"
                ) from exc
            if version != CONFIG_VERSION:
                raise RuntimeServiceError(
                    f"unsupported settings version: {patch['version']}, expected {CONFIG_VERSION}"
                )
        merged["version"] = CONFIG_VERSION
        return merged

    @staticmethod
    def _resolve_ssh_timeout(patch: Optional[dict[str, Any]] = None) -> int:
        raw_timeout = 5 if patch is None else patch.get("timeout_sec", 5)
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise RuntimeServiceError(f"invalid ssh timeout: {raw_timeout}") from exc
        if timeout <= 0:
            raise RuntimeServiceError("ssh timeout must be positive")
        return timeout

    @staticmethod
    def _resolve_ssh_settings(patch: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        config = get_config()
        current = config.get("ssh", {})
        if not isinstance(current, dict):
            raise RuntimeServiceError("settings.ssh must be an object")

        merged = dict(current)
        if isinstance(patch, dict):
            for key in ("host", "port", "user", "password", "use_key", "key_file"):
                if key in patch and patch[key] is not None:
                    merged[key] = patch[key]
            merged.pop("password_ref", None)

        host = str(merged.get("host", "") or "").strip()
        user = str(merged.get("user", "") or "").strip()
        key_file = str(merged.get("key_file", "") or "").strip()
        password = (
            str(patch.get("password", "") or "")
            if isinstance(patch, dict) and "password" in patch
            else resolve_ssh_password(merged)
        )
        use_key = bool(merged.get("use_key", False))
        try:
            port = int(merged.get("port", 22))
        except (TypeError, ValueError) as exc:
            raise RuntimeServiceError(
                f"invalid ssh port: {merged.get('port')}"
            ) from exc

        if not host:
            raise RuntimeServiceError("ssh.host is required")
        if not user:
            raise RuntimeServiceError("ssh.user is required")
        if port <= 0 or port > 65535:
            raise RuntimeServiceError(f"invalid ssh port: {port}")
        if use_key and not key_file:
            raise RuntimeServiceError(
                "ssh.key_file is required when ssh.use_key is true"
            )

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": "" if use_key else password,
            "use_key": use_key,
            "key_file": key_file,
        }

    def _attempt_startup_auto_connect(self) -> None:
        if self._auto_connect_attempted:
            return
        self._auto_connect_attempted = True

        try:
            ssh_settings = self._resolve_ssh_settings()
        except RuntimeServiceError:
            return

        existing_ssh = self._service_locator.ssh_service
        if existing_ssh is not None and getattr(existing_ssh, "is_connected", False):
            return

        timeout = self._resolve_ssh_timeout(None)
        try:
            result = ssh_connect(
                ip=ssh_settings["host"],
                port=ssh_settings["port"],
                user=ssh_settings["user"],
                password=ssh_settings["password"],
                key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                timeout=timeout,
            )
            if not result.ok or result.client is None:
                raise RuntimeServiceError(result.message)

            def _connect_fn() -> Any:
                reconnect = ssh_connect(
                    ip=ssh_settings["host"],
                    port=ssh_settings["port"],
                    user=ssh_settings["user"],
                    password=ssh_settings["password"],
                    key_file=ssh_settings["key_file"]
                    if ssh_settings["use_key"]
                    else "",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            self._service_locator.ssh_service = SSHService(
                initial_client=result.client, connect_fn=_connect_fn
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

    def _run_ssh_command(self, cmd: str, timeout: int) -> tuple[int, str, str]:
        ssh = self._service_locator.ssh_service
        if ssh is None:
            raise RuntimeServiceError("SSH service is not available")
        result = ssh.run(cmd, timeout=timeout)
        if isinstance(result, tuple):
            code, stdout, stderr = result
            return int(code), str(stdout), str(stderr)
        code = getattr(result, "exit_code", None)
        if code is None:
            raise RuntimeServiceError("SSH run result is invalid")
        return (
            int(code),
            str(getattr(result, "stdout", "")),
            str(getattr(result, "stderr", "")),
        )

    def _run_ssh_command_interactive(
        self, cmd: str, timeout: int
    ) -> tuple[int, str, str]:
        ssh = self._service_locator.ssh_service
        if ssh is None:
            raise RuntimeServiceError("SSH service is not available")
        if not hasattr(ssh, "run_interactive"):
            raise RuntimeServiceError(
                "SSH service does not support interactive invoke_shell execution"
            )
        result = ssh.run_interactive(cmd, timeout=timeout)
        if isinstance(result, tuple):
            code, stdout, stderr = result
            return int(code), str(stdout), str(stderr)
        code = getattr(result, "exit_code", None)
        if code is None:
            raise RuntimeServiceError("SSH interactive run result is invalid")
        return (
            int(code),
            str(getattr(result, "stdout", "")),
            str(getattr(result, "stderr", "")),
        )

    def _remote_runtime_ok(self, command: str) -> bool:
        try:
            rc, _stdout, _stderr = self._run_ssh_command(command, 15)
            return rc == 0
        except Exception:
            return False

    def _remote_runtime_ok_interactive(self, command: str) -> bool:
        try:
            rc, _stdout, _stderr = self._run_ssh_command_interactive(command, 15)
            return rc == 0
        except Exception:
            return False

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._event_seq += 1
        self._events.append(
            {
                "seq": self._event_seq,
                "event_type": event_type,
                "timestamp": time.time(),
                "payload": payload,
            }
        )
