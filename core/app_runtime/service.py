"""Runtime service layer shared by API and desktop shell."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from config import CONFIG_VERSION, default_settings_schema, get_config, save_config
from . import workbench_runtime_ops
from core.data.database_service import DatabaseService
from core.data.data_registry import DataRegistry
from core.data.execution_query_service import ExecutionQueryService
from core.data.project_manager import ProjectInfo, ProjectManager
from core.execution.artifact_store import ArtifactStore
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHService
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


@dataclass(frozen=True)
class ExecutionSubmitRequest:
    project_id: str
    tool_id: str
    input_data_ids: list[str]
    parameters: dict[str, Any]
    sample_id: str = ""
    sample_name: str = ""
    sample_source: str = ""
    sample_metadata: Optional[dict[str, Any]] = None
    triggered_by: str = "api"
    database_paths: Optional[dict[str, str]] = None


class RuntimeService:
    """Thread-safe facade around ProjectManager + ServiceLocator."""

    def __init__(
        self,
        project_manager: Optional[ProjectManager] = None,
        service_locator: Optional[ServiceLocator] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._project_manager = project_manager or ProjectManager()
        self._service_locator = service_locator or ServiceLocator(project_manager=self._project_manager)
        self._initialized = False
        self._signals_connected = False
        self._events: deque[dict[str, Any]] = deque(maxlen=2000)
        self._event_seq = 0
        self._tool_bridge_service: Optional[Any] = None

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._service_locator.initialize()
            self._connect_runtime_signals()
            self._initialized = True

    def shutdown(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            self._disconnect_runtime_signals()
            self._service_locator.shutdown()
            self._tool_bridge_service = None
            self._initialized = False

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            registry = self._service_locator.plugin_registry
            ids = sorted(registry.list_all_ids())
            return [registry.get_index_entry(tool_id) for tool_id in ids]

    def get_tool_descriptor(self, *, tool_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            normalized_tool_id = str(tool_id or "").strip()
            if not normalized_tool_id:
                raise RuntimeServiceError("tool_id is required")
            descriptor = self._service_locator.plugin_registry.get_descriptor(normalized_tool_id)
            if not isinstance(descriptor, dict) or not descriptor:
                raise RuntimeServiceError(f"Tool descriptor not found: {normalized_tool_id}")
            return descriptor

    def list_projects(self, *, sort_by: str = "created_at") -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            projects = self._project_manager.list_projects(sort_by=sort_by)
            return [self._project_to_dict(project) for project in projects]

    def get_current_project(self) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            project = self._project_manager.current_project
            if project is None:
                return None
            return self._project_to_dict(project)

    def create_project(self, *, name: str, description: str = "", open_after_create: bool = True) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            project_id = self._project_manager.create_project(name=name, description=description)
            if open_after_create:
                project = self._project_manager.open_project(project_id)
            else:
                matches = [p for p in self._project_manager.list_projects() if p.project_id == project_id]
                if not matches:
                    raise RuntimeServiceError(f"Created project cannot be found: {project_id}")
                project = matches[0]
            return self._project_to_dict(project)

    def open_project(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            project = self._project_manager.open_project(project_id)
            return self._project_to_dict(project)

    def list_samples(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            registry = DataRegistry(self._project_manager.db)
            return [sample.__dict__ for sample in registry.list_samples()]

    def create_sample(
        self,
        *,
        project_id: str,
        name: str,
        source: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            registry = DataRegistry(self._project_manager.db)
            sample_id = registry.add_sample(name=name, source=source or None, metadata=metadata or {})
            sample = registry.get_sample(sample_id)
            if sample is None:
                raise RuntimeServiceError(f"Sample created but cannot be reloaded: {sample_id}")
            return sample.__dict__

    def list_executions(
        self,
        *,
        project_id: str,
        limit: int = 50,
        archived: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            query = ExecutionQueryService(self._project_manager.db)
            rows = query.list_recent_executions(limit=limit, archived=archived)
            return [self._normalize_execution_row(row) for row in rows]

    def get_execution(self, *, project_id: str, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            row = self._project_manager.db.execute(
                """
                SELECT execution_id, sample_id, tool_id, status, parameters,
                       created_at, completed_at, error, archived_at
                FROM executions
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
            if row is None:
                raise RuntimeServiceError(f"Execution not found: {execution_id}")

            execution = self._normalize_execution_row(dict(row))
            execution["artifacts"] = self.get_execution_artifacts(
                project_id=project_id,
                execution_id=execution_id,
            )
            return execution

    def submit_execution(self, request: ExecutionSubmitRequest) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(request.project_id)
            sample_id = self._resolve_sample_id(request)
            tool_engine = self._service_locator.tool_engine
            if tool_engine is None:
                raise RuntimeServiceError("Tool engine is not ready; open a project first")

            execution_id = tool_engine.execute(
                tool_id=request.tool_id,
                input_data_ids=request.input_data_ids,
                parameters=request.parameters,
                sample_id=sample_id,
                triggered_by=request.triggered_by,
                database_paths=request.database_paths or None,
            )
            return {"execution_id": execution_id, "status": "pending"}

    def get_execution_artifacts(self, *, project_id: str, execution_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            store = ArtifactStore(lambda: self._project_manager.current_project_dir)
            return store.list_local_execution_artifacts(execution_id)

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
            return get_config()

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if not isinstance(patch, dict):
                raise RuntimeServiceError("settings patch must be an object")
            current = get_config()
            merged = self._merge_settings_patch(current, patch)
            save_config(merged)
            return get_config()

    def get_ssh_status(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_settings = self._resolve_ssh_settings()
            ssh_service = self._service_locator.ssh_service
            connected = bool(ssh_service is not None and getattr(ssh_service, "is_connected", False))
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
                    key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            ssh_service = SSHService(initial_client=result.client, connect_fn=_connect_fn)
            self._service_locator.ssh_service = ssh_service
            status = self.get_ssh_status()
            status["message"] = result.message
            return status

    def disconnect_ssh(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._service_locator.ssh_service = None
            status = self.get_ssh_status()
            status["message"] = "SSH disconnected"
            return status

    def test_ssh_connection(self, patch: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_settings = self._resolve_ssh_settings(patch)
            steps = run_diagnostics(
                ip=ssh_settings["host"],
                port=ssh_settings["port"],
                user=ssh_settings["user"],
                password=ssh_settings["password"] if not ssh_settings["use_key"] else "",
                key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                existing_client=getattr(self._service_locator.ssh_service, "_client", lambda: None)(),
            )
            ok = all(step.status == "ok" for step in steps)
            return {
                "ok": ok,
                "message": "SSH diagnostics passed" if ok else "SSH diagnostics failed",
                "steps": [{"name": step.name, "status": step.status, "message": step.message} for step in steps],
                "status": self.get_ssh_status(),
            }

    def list_databases(self, *, project_id: str, include_status: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            config = get_config()
            databases_cfg = config.get("databases", {})
            if not isinstance(databases_cfg, dict):
                raise RuntimeServiceError("settings.databases must be an object")
            db_root = str(databases_cfg.get("db_root", "") or "")
            raw_overrides = databases_cfg.get("overrides", {})
            overrides: dict[str, str] = {}
            if isinstance(raw_overrides, dict):
                overrides = {
                    str(key): str(value)
                    for key, value in raw_overrides.items()
                    if str(value or "").strip()
                }

            service = DatabaseService()
            ssh = self._service_locator.ssh_service
            status_enabled = bool(include_status and ssh is not None and getattr(ssh, "is_connected", False))

            items: list[dict[str, Any]] = []
            for info in service.list_all():
                resolved_path = service.resolve_binding_value(info.db_id, db_root, overrides=overrides)
                item = {
                    "db_id": info.db_id,
                    "name": info.name,
                    "description": info.description,
                    "category": info.category,
                    "size_mb": info.size_mb,
                    "tools": info.tools,
                    "binding_mode": info.binding_mode,
                    "binding_leaf": info.binding_leaf,
                    "resolved_path": resolved_path,
                    "configured_override": overrides.get(info.db_id, ""),
                    "installable": service.is_installable(info.db_id),
                }
                if include_status:
                    if status_enabled:
                        status = service.check_status(
                            self._run_ssh_command,
                            info.db_id,
                            db_root,
                            overrides=overrides,
                        )
                        item["status"] = status.status.value
                        item["status_message"] = status.message
                    else:
                        item["status"] = "unknown"
                        item["status_message"] = "SSH disconnected"
                items.append(item)
            return items

    def list_execution_history(self, *, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            query = ExecutionQueryService(self._project_manager.db)
            rows = query.get_execution_history_for_ui(limit=limit)
            return [self._normalize_execution_row(row) for row in rows]

    def archive_execution(self, *, project_id: str, execution_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            query = ExecutionQueryService(self._project_manager.db)
            result = query.archive_execution(execution_id)
            if result.get("status") != "ok":
                raise RuntimeServiceError(str(result.get("message") or "archive failed"))
            return {
                "status": "ok",
                "message": str(result.get("message") or ""),
            }

    def list_workbench_tools(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.list_workbench_tools(self, project_id=project_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_workbench_config(self, *, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.get_workbench_config(self, project_id=project_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_workbench_history(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.get_workbench_history(self, project_id=project_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_workbench_result(self, *, project_id: str, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.get_workbench_result(
                    self,
                    project_id=project_id,
                    execution_id=execution_id,
                )
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_workbench_remote_status(self, *, project_id: str, execution_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.get_workbench_remote_status(
                    self,
                    project_id=project_id,
                    execution_id=execution_id,
                )
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def run_workbench_tool(self, *, project_id: str, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.run_workbench_tool(
                    self,
                    project_id=project_id,
                    tool_id=tool_id,
                    params=params,
                )
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_workbench_remote_primer_results(
        self,
        *,
        project_id: str,
        remote_result_dir: str,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workbench_runtime_ops.get_workbench_remote_primer_results(
                    self,
                    project_id=project_id,
                    remote_result_dir=remote_result_dir,
                )
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def list_runtime_events(self, *, after_seq: int = 0, limit: int = 200) -> dict[str, Any]:
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

    def _resolve_sample_id(self, request: ExecutionSubmitRequest) -> str:
        registry = DataRegistry(self._project_manager.db)
        sample_id = str(request.sample_id or "").strip()
        if sample_id:
            sample = registry.get_sample(sample_id)
            if sample is None:
                raise RuntimeServiceError(f"Sample not found: {sample_id}")
            return sample_id

        sample_name = str(request.sample_name or "").strip()
        if not sample_name:
            raise RuntimeServiceError("sample_id or sample_name is required")
        return registry.add_sample(
            name=sample_name,
            source=request.sample_source or None,
            metadata=request.sample_metadata or {},
        )

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
    def _merge_settings_patch(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        defaults = default_settings_schema()
        allowed_sections = {"ssh", "linux", "databases", "blast", "ncbi", "runtime"}
        for section, value in patch.items():
            if section == "version":
                continue
            if section not in allowed_sections:
                raise RuntimeServiceError(f"unknown settings section: {section}")
            if not isinstance(value, dict):
                raise RuntimeServiceError(f"settings section '{section}' must be an object")
            allowed_keys = set(defaults[section].keys())
            for key in value:
                if key not in allowed_keys:
                    raise RuntimeServiceError(f"unknown settings key: {section}.{key}")
            existing = merged.get(section, {})
            if not isinstance(existing, dict):
                existing = {}
            next_section = dict(existing)
            next_section.update(value)
            merged[section] = next_section

        if "version" in patch:
            try:
                version = int(patch["version"])
            except (TypeError, ValueError) as exc:
                raise RuntimeServiceError(f"invalid settings version: {patch['version']}") from exc
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

        host = str(merged.get("host", "") or "").strip()
        user = str(merged.get("user", "") or "").strip()
        key_file = str(merged.get("key_file", "") or "").strip()
        password = str(merged.get("password", "") or "")
        use_key = bool(merged.get("use_key", False))
        try:
            port = int(merged.get("port", 22))
        except (TypeError, ValueError) as exc:
            raise RuntimeServiceError(f"invalid ssh port: {merged.get('port')}") from exc

        if not host:
            raise RuntimeServiceError("ssh.host is required")
        if not user:
            raise RuntimeServiceError("ssh.user is required")
        if port <= 0 or port > 65535:
            raise RuntimeServiceError(f"invalid ssh port: {port}")
        if use_key and not key_file:
            raise RuntimeServiceError("ssh.key_file is required when ssh.use_key is true")

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "use_key": use_key,
            "key_file": key_file,
        }

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
        return int(code), str(getattr(result, "stdout", "")), str(getattr(result, "stderr", ""))

    def _connect_runtime_signals(self) -> None:
        if self._signals_connected:
            return
        self._service_locator.execution_started.connect(self._on_execution_started)
        self._service_locator.execution_completed.connect(self._on_execution_completed)
        self._service_locator.execution_failed.connect(self._on_execution_failed)
        self._service_locator.ssh_changed.connect(self._on_ssh_changed)
        self._signals_connected = True

    def _disconnect_runtime_signals(self) -> None:
        if not self._signals_connected:
            return
        try:
            self._service_locator.execution_started.disconnect(self._on_execution_started)
        except (TypeError, RuntimeError):
            pass
        try:
            self._service_locator.execution_completed.disconnect(self._on_execution_completed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._service_locator.execution_failed.disconnect(self._on_execution_failed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._service_locator.ssh_changed.disconnect(self._on_ssh_changed)
        except (TypeError, RuntimeError):
            pass
        self._signals_connected = False

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

    def _on_execution_started(self, execution_id: str) -> None:
        with self._lock:
            self._append_event("execution_started", {"execution_id": execution_id})

    def _on_execution_completed(self, execution_id: str) -> None:
        with self._lock:
            self._append_event("execution_completed", {"execution_id": execution_id})

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        with self._lock:
            self._append_event(
                "execution_failed",
                {"execution_id": execution_id, "error": str(error or "")},
            )

    def _on_ssh_changed(self, connected: bool) -> None:
        with self._lock:
            self._append_event("ssh_changed", {"connected": bool(connected)})
