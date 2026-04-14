"""Runtime service layer shared by API and desktop shell."""

from __future__ import annotations

import json
import logging
import shlex
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from config import CONFIG_VERSION, default_settings_schema, get_config, resolve_ssh_password, save_config
from . import workbench_runtime_ops, workflow_runtime_ops
from core.data.database_service import DatabaseService
from core.data.data_registry import DataRegistry
from core.data.execution_query_service import ExecutionQueryService
from core.data.project_manager import ProjectInfo, ProjectManager
from core.environment import env_batch_checker, env_detector, miniforge_bootstrap
from core.environment.env_installer import EnvInstaller
from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.plugins.runtime_metadata import derive_conda_env_name
from core.environment.server_preflight import MIN_FREE_DISK_GB, probe_preflight
from core.execution.artifact_store import ArtifactStore
from core.remote.server_capabilities import PreflightError
from core.remote.ssh_connector import run_diagnostics, ssh_connect
from core.remote.ssh_service import SSHService, TerminalSession
from core.service_locator import ServiceLocator
from core.utils import get_app_root
from core.workflow import (
    LaunchSpec,
    LocalSSHBackend,
    ServerProfile,
    SlurmSSHBackend,
    WorkflowEdge,
    WorkflowNode,
    WorkflowSpec,
    compile_workflow_bundle,
    create_workflow_backend,
)
from core.workflow.bootstrap_ops import (
    WORKFLOW_BOOTSTRAP_PREFIX,
    read_workflow_bootstrap_status,
    submit_workflow_runtime_bootstrap,
    workflow_bootstrap_task_dir,
)

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
    task_id: str
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
            self._connect_runtime_signals()
            self._initialized = True
            self._attempt_startup_auto_connect()

    def shutdown(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            self._close_all_terminal_sessions(message="终端会话已结束", drop_sessions=True)
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

    def compile_workflow(self, *, project_id: str, workflow: dict[str, Any], launch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            workflow_spec = self._build_workflow_spec(workflow)
            launch_spec = self._build_launch_spec(project_id=project_id, launch=launch)
            return compile_workflow_bundle(
                workflow_spec,
                launch_spec,
                plugin_registry=self._service_locator.plugin_registry,
            )

    def list_runs(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.list_runs(self, project_id=project_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_run(self, *, project_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_run(self, project_id=project_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def create_run(self, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.create_run(
                    self,
                    project_id=project_id,
                    task_id=task_id,
                    launch=launch,
                )
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def cancel_run(self, *, project_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.cancel_run(self, project_id=project_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_run_artifacts(self, *, project_id: str, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_run_artifacts(self, project_id=project_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_run_resolved_config(self, *, project_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_run_resolved_config(self, project_id=project_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def doctor_server(self, *, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            if str(server_id or "").strip() != "current":
                raise RuntimeServiceError("Only server_id='current' is supported during the workflow-first skeleton phase.")
            self._ensure_ssh_connected()
            preflight = self.get_ssh_preflight()
            env_status = self.get_remote_env_status()
            caps = probe_preflight(self._run_ssh_command)
            recommended_profile = self._profile_from_capabilities(caps)
            return {
                "server_id": "current",
                "doctor_phase": "workflow_runtime",
                "preflight": preflight,
                "env_status": env_status,
                "recommended_profile": recommended_profile["profile_id"],
                "recommended_profile_details": recommended_profile,
                "supported_profile_kinds": list(caps.supported_profile_kinds),
                "runtime_capabilities": self._runtime_capabilities_dict(caps),
            }

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

    def list_projects(self, *, sort_by: str = "created_at", include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            projects = self._project_manager.list_projects(sort_by=sort_by)
            if not include_archived:
                projects = [project for project in projects if project.status != "archived"]
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

    def update_project(self, *, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
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

    def list_tasks(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            rows = self._project_manager.db.execute(
                """
                SELECT
                    t.task_id,
                    t.project_id,
                    t.title,
                    t.description,
                    t.status,
                    t.created_at,
                    t.updated_at,
                    t.last_activity_at,
                    t.latest_execution_id,
                    t.summary,
                    t.result_snapshot,
                    COUNT(e.execution_id) AS execution_count,
                    SUM(CASE WHEN e.status = 'failed' THEN 1 ELSE 0 END) AS failed_execution_count,
                    MAX(e.created_at) AS latest_execution_created_at
                FROM tasks t
                LEFT JOIN executions e ON e.task_id = t.task_id
                WHERE t.project_id = ?
                GROUP BY t.task_id
                ORDER BY t.last_activity_at DESC, t.created_at DESC
                """,
                (project_id,),
            ).fetchall()
            return [self._normalize_task_row(dict(row)) for row in rows]

    def create_task(self, *, project_id: str, title: str, description: str = "") -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            normalized_title = str(title or "").strip()
            if not normalized_title:
                raise RuntimeServiceError("task title is required")
            now = time.time()
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            self._project_manager.db.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, title, description, status,
                    created_at, updated_at, last_activity_at,
                    latest_execution_id, summary, result_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    project_id,
                    normalized_title,
                    str(description or "").strip(),
                    "pending",
                    now,
                    now,
                    now,
                    None,
                    "",
                    "{}",
                ),
            )
            self._project_manager.db.commit()
            return self.get_task(project_id=project_id, task_id=task_id)

    def delete_task(self, *, project_id: str, task_id: str) -> dict[str, str]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            self._assert_task_exists(project_id=project_id, task_id=task_id)
            execution_count = self._project_manager.db.execute(
                "SELECT COUNT(*) FROM executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if execution_count and int(execution_count[0] or 0) > 0:
                raise RuntimeServiceError("cannot delete task with executions; archive/cleanup flow is not implemented yet")
            self._project_manager.db.execute(
                "DELETE FROM workflow_results WHERE project_id = ? AND task_id = ?",
                (project_id, task_id),
            )
            self._project_manager.db.execute(
                "DELETE FROM workflow_runs WHERE project_id = ? AND task_id = ?",
                (project_id, task_id),
            )
            self._project_manager.db.execute(
                "DELETE FROM workflow_snapshots WHERE project_id = ? AND task_id = ?",
                (project_id, task_id),
            )
            self._project_manager.db.execute(
                "DELETE FROM tasks WHERE project_id = ? AND task_id = ?",
                (project_id, task_id),
            )
            self._project_manager.db.commit()
            return {"task_id": task_id, "status": "deleted"}

    def get_task(self, *, project_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            row = self._project_manager.db.execute(
                """
                SELECT
                    t.task_id,
                    t.project_id,
                    t.title,
                    t.description,
                    t.status,
                    t.created_at,
                    t.updated_at,
                    t.last_activity_at,
                    t.latest_execution_id,
                    t.summary,
                    t.result_snapshot,
                    COUNT(e.execution_id) AS execution_count,
                    SUM(CASE WHEN e.status = 'failed' THEN 1 ELSE 0 END) AS failed_execution_count,
                    MAX(e.created_at) AS latest_execution_created_at
                FROM tasks t
                LEFT JOIN executions e ON e.task_id = t.task_id
                WHERE t.project_id = ? AND t.task_id = ?
                GROUP BY t.task_id
                """,
                (project_id, task_id),
            ).fetchone()
            if row is None:
                raise RuntimeServiceError(f"Task not found: {task_id}")
            return self._normalize_task_row(dict(row))

    def get_task_workflow(self, *, project_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_workflow(self, project_id=project_id, task_id=task_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def put_task_workflow(self, *, project_id: str, task_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.put_task_workflow(self, project_id=project_id, task_id=task_id, workflow=workflow)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def compile_task_workflow(self, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.compile_task_workflow(self, project_id=project_id, task_id=task_id, launch=launch)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_workflow_compatibility(self, *, project_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_workflow_compatibility(self, project_id=project_id, task_id=task_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def update_task(self, *, project_id: str, task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            if not isinstance(patch, dict):
                raise RuntimeServiceError("task patch must be an object")
            allowed_status = {"pending", "queued", "in_progress", "completed", "failed", "cancelled"}
            updates: list[str] = []
            values: list[Any] = []

            if "title" in patch:
                title = str(patch.get("title") or "").strip()
                if not title:
                    raise RuntimeServiceError("task title cannot be empty")
                updates.append("title = ?")
                values.append(title)
            if "description" in patch:
                updates.append("description = ?")
                values.append(str(patch.get("description") or "").strip())
            if "status" in patch:
                status = str(patch.get("status") or "").strip()
                if status not in allowed_status:
                    raise RuntimeServiceError(f"invalid task status: {status}")
                updates.append("status = ?")
                values.append(status)
            if "summary" in patch:
                updates.append("summary = ?")
                values.append(str(patch.get("summary") or "").strip())

            workflow_patch = patch.get("workflow")
            if workflow_patch is not None and not isinstance(workflow_patch, dict):
                raise RuntimeServiceError("workflow patch must be an object")

            if not updates and workflow_patch is None:
                raise RuntimeServiceError("task patch is empty")

            cursor = None
            if updates:
                now = time.time()
                updates.append("updated_at = ?")
                values.append(now)
                updates.append("last_activity_at = ?")
                values.append(now)
                values.extend([project_id, task_id])
                cursor = self._project_manager.db.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE project_id = ? AND task_id = ?",
                    tuple(values),
                )
                if cursor.rowcount <= 0:
                    raise RuntimeServiceError(f"Task not found: {task_id}")
            else:
                self._assert_task_exists(project_id=project_id, task_id=task_id)
            if isinstance(workflow_patch, dict):
                workflow_runtime_ops.upsert_task_workflow_snapshot(
                    self,
                    project_id=project_id,
                    task_id=task_id,
                    workflow_payload=self._build_workflow_spec(workflow_patch).to_dict(),
                )
                now = time.time()
                self._project_manager.db.execute(
                    """
                    UPDATE tasks
                    SET updated_at = ?, last_activity_at = ?
                    WHERE project_id = ? AND task_id = ?
                    """,
                    (now, now, project_id, task_id),
                )
            self._project_manager.db.commit()
            return self.get_task(project_id=project_id, task_id=task_id)

    def list_task_runs(self, *, project_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.list_task_runs(self, project_id=project_id, task_id=task_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_run(self, *, project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_run(self, project_id=project_id, task_id=task_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def create_task_run(self, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.create_task_run(self, project_id=project_id, task_id=task_id, launch=launch)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def cancel_task_run(self, *, project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.cancel_task_run(self, project_id=project_id, task_id=task_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def list_task_results(self, *, project_id: str, task_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.list_task_results(self, project_id=project_id, task_id=task_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_results_summary(self, *, project_id: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_results_summary(self, project_id=project_id, task_id=task_id, run_id=run_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_result(self, *, project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_result(self, project_id=project_id, task_id=task_id, result_id=result_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_result_content(self, *, project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_result_content(self, project_id=project_id, task_id=task_id, result_id=result_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

    def get_task_workspace(self, *, project_id: str, task_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            try:
                return workflow_runtime_ops.get_task_workspace(self, project_id=project_id, task_id=task_id)
            except (RuntimeError, ValueError) as exc:
                raise RuntimeServiceError(str(exc)) from exc

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
            raise RuntimeServiceError(
                "Legacy single-tool execution is disabled for new submissions. "
                "Use the workflow/run APIs from /workspace instead."
            )

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
            current = get_config()
            sanitized = dict(current)
            ssh = dict(current.get("ssh", {})) if isinstance(current.get("ssh"), dict) else {}
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
            ssh = dict(updated.get("ssh", {})) if isinstance(updated.get("ssh"), dict) else {}
            ssh["password"] = ""
            ssh.pop("password_ref", None)
            updated["ssh"] = ssh
            return updated

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
                    key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            ssh_service = SSHService(initial_client=result.client, connect_fn=_connect_fn)
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
            self._close_all_terminal_sessions(message="SSH 已断开，终端会话已结束", drop_sessions=False)
            self._service_locator.ssh_service = None
            self._auto_connect_failed = False
            self._auto_connect_error = ""
            self._auto_connect_notice_key = ""
            status = self.get_ssh_status()
            status["message"] = "SSH disconnected"
            return status

    def create_terminal_session(self, *, cols: int = 120, rows: int = 28) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
            session = ssh.open_terminal_session(cols=cols, rows=rows)
            self._terminal_sessions[session.session_id] = session
            return session.snapshot(cursor=0)

    def read_terminal_session(self, *, session_id: str, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._get_terminal_session(session_id)
            return session.snapshot(cursor=cursor)

    def send_terminal_input(self, *, session_id: str, data: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._get_terminal_session(session_id)
            session.send(data)
            return {"session_id": session_id, "accepted": True}

    def close_terminal_session(self, *, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            session = self._terminal_sessions.pop(session_id, None)
            if session is None:
                raise RuntimeServiceError(f"unknown terminal session: {session_id}")
            session.close(message="终端会话已结束", connected=False)
            return {"session_id": session_id, "closed": True}

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

    def get_ssh_preflight(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_ssh_connected()
            caps = probe_preflight(self._run_ssh_command)
            self._service_locator.server_capabilities = caps
            recommended_profile = self._profile_from_capabilities(caps)
            failures = caps.bootstrap_failures(min_free_disk_gb=MIN_FREE_DISK_GB)
            checks = [
                {
                    "key": "arch",
                    "label": "架构",
                    "status": "ok" if caps.arch in {"x86_64", "aarch64"} else "fail",
                    "value": caps.arch or "unknown",
                    "message": f"服务器架构: {caps.arch or 'unknown'}",
                },
                {
                    "key": "bash",
                    "label": "bash",
                    "status": "ok" if caps.has_bash else "fail",
                    "value": "available" if caps.has_bash else "missing",
                    "message": "bash 可用" if caps.has_bash else "缺少 bash，无法执行 workflow launcher",
                },
                {
                    "key": "downloader",
                    "label": "下载器",
                    "status": "ok" if caps.has_curl or caps.has_wget else "fail",
                    "value": "curl" if caps.has_curl else "wget" if caps.has_wget else "missing",
                    "message": "已检测到 curl/wget" if caps.has_curl or caps.has_wget else "缺少 curl/wget，无法下载运行时",
                },
                {
                    "key": "sha256sum",
                    "label": "sha256sum",
                    "status": "ok" if caps.has_sha256sum else "fail",
                    "value": "available" if caps.has_sha256sum else "missing",
                    "message": "支持下载校验" if caps.has_sha256sum else "缺少 sha256sum，无法校验下载内容",
                },
                {
                    "key": "home_writable",
                    "label": "HOME 可写",
                    "status": "ok" if caps.home_writable else "fail",
                    "value": "writable" if caps.home_writable else "read_only",
                    "message": "HOME 目录可写" if caps.home_writable else "HOME 目录不可写，无法创建 workflow 运行目录",
                },
                {
                    "key": "screen",
                    "label": "screen",
                    "status": "ok" if caps.has_screen else "warn",
                    "value": "available" if caps.has_screen else "missing",
                    "message": "screen 可用于旧后台安装流程" if caps.has_screen else "screen 缺失，但不会阻塞 workflow run",
                },
                {
                    "key": "disk",
                    "label": "磁盘空间",
                    "status": "ok" if caps.free_disk_gb >= MIN_FREE_DISK_GB else "fail",
                    "value": f"{caps.free_disk_gb:.1f} GB",
                    "message": f"可用磁盘空间 {caps.free_disk_gb:.1f} GB",
                },
            ]
            return {
                "ok": not failures,
                "arch": caps.arch,
                "free_disk_gb": caps.free_disk_gb,
                "recommended_profile": recommended_profile.profile_kind,
                "recommended_profile_details": recommended_profile.to_dict(),
                "supported_profile_kinds": list(caps.supported_profile_kinds),
                "runtime_capabilities": self._runtime_capabilities_dict(caps),
                "checks": checks,
                "failures": failures,
                "warnings": caps.warnings() + [item["message"] for item in checks if item["status"] == "warn"],
            }

    def get_remote_env_status(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_ssh_connected()

            conda_detect = env_detector.detect(self._run_ssh_command)
            conda_executable = str(conda_detect.executable or "").strip()
            if conda_detect.status == env_detector.CondaStatus.OK and conda_executable:
                self._remember_managed_conda(conda_executable)
            else:
                self._service_locator.conda_executable = ""

            miniforge_status = miniforge_bootstrap.check_status(self._run_ssh_command)
            miniforge_alive = miniforge_bootstrap.is_session_alive(self._run_ssh_command)
            miniforge_log = miniforge_bootstrap.read_log(self._run_ssh_command)
            miniforge_stage = self._normalize_job_stage(
                status=str(miniforge_status.get("status") or ""),
                exit_code=str(miniforge_status.get("exit_code") or ""),
                session_alive=miniforge_alive,
                heartbeat=str(miniforge_status.get("heartbeat") or ""),
            )

            tool_specs = self._collect_tool_env_specs()
            env_checks: dict[str, bool] = {}
            existing_env_paths: list[str] = []
            if conda_detect.status == env_detector.CondaStatus.OK and conda_executable:
                check_results, existing_env_paths = env_batch_checker.check_all_envs(
                    self._run_ssh_command,
                    [{"id": spec["tool_id"], "conda_env": spec["env_name"]} for spec in tool_specs],
                    conda_executable=conda_executable,
                )
                env_checks = {row.tool_id: bool(row.ok) for row in check_results}

            install_probe_rows = EnvInstaller.batch_probe(
                self._run_ssh_command,
                [spec["tool_id"] for spec in tool_specs if spec["installable"]],
            )
            install_probe_by_tool = {str(row.get("tool_id") or ""): row for row in install_probe_rows}

            tool_envs: list[dict[str, Any]] = []
            for spec in tool_specs:
                probe_row = install_probe_by_tool.get(spec["tool_id"], {})
                session_alive = bool(probe_row.get("session_alive"))
                install_stage = self._normalize_job_stage(
                    status=str(probe_row.get("status") or ""),
                    exit_code=str(probe_row.get("exit_code") or ""),
                    session_alive=session_alive,
                )
                installed = bool(env_checks.get(spec["tool_id"]))
                if install_stage == "running":
                    status = "installing"
                elif installed:
                    status = "installed"
                elif install_stage == "failed":
                    status = "failed"
                elif conda_detect.status != env_detector.CondaStatus.OK:
                    status = "blocked"
                else:
                    status = "not_installed"

                tool_envs.append(
                    {
                        "tool_id": spec["tool_id"],
                        "name": spec["name"],
                        "env_name": spec["env_name"],
                        "version": spec["version"],
                        "installed": installed,
                        "installable": spec["installable"],
                        "status": status,
                        "message": self._describe_tool_env_status(
                            status=status,
                            conda_message=conda_detect.message,
                            installable=spec["installable"],
                        ),
                        "job_id": f"h2o_install_{spec['tool_id']}" if spec["installable"] else "",
                        "log_text": str(probe_row.get("log_text") or ""),
                        "log_size": int(probe_row.get("log_size") or 0),
                        "shared_tool_ids": spec["shared_tool_ids"],
                    }
                )

            installed_envs = sum(1 for row in tool_envs if row["installed"])
            return {
                "miniforge": {
                    "installed": conda_detect.status == env_detector.CondaStatus.OK,
                    "status": "installed" if conda_detect.status == env_detector.CondaStatus.OK else miniforge_stage,
                    "version": str(conda_detect.version or ""),
                    "conda_executable": conda_executable,
                    "message": conda_detect.message,
                    "job_id": miniforge_bootstrap.JOB_ID,
                    "log_text": miniforge_log,
                    "task_status": miniforge_status,
                },
                "tool_envs": tool_envs,
                "summary": {
                    "total": len(tool_envs),
                    "installed": installed_envs,
                    "missing": max(len(tool_envs) - installed_envs, 0),
                    "env_paths": existing_env_paths,
                },
            }

    def install_remote_env(self, *, target: str, tool_id: str = "", profile_kind: str = "") -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_ssh_connected()
            caps = probe_preflight(self._run_ssh_command)
            self._service_locator.server_capabilities = caps

            normalized_target = str(target or "").strip()
            if normalized_target == "miniforge":
                item = miniforge_bootstrap.submit(caps, self._run_ssh_command)
                return {
                    "target": "miniforge",
                    "job_id": item["job_id"],
                    "task_dir": item["task_dir"],
                    "message": "已提交 Miniforge 后台安装任务",
                }

            if normalized_target == "workflow_runtime":
                normalized_profile_kind = str(profile_kind or "").strip()
                if not normalized_profile_kind:
                    raise RuntimeServiceError("profile_kind is required for workflow_runtime install")
                item = submit_workflow_runtime_bootstrap(
                    self._run_ssh_command,
                    profile_kind=normalized_profile_kind,
                )
                return {
                    "target": "workflow_runtime",
                    "profile_kind": normalized_profile_kind,
                    "job_id": item["job_id"],
                    "task_dir": item["task_dir"],
                    "message": f"已提交 {normalized_profile_kind} workflow runtime bootstrap 任务",
                }

            if normalized_target != "tool_env":
                raise RuntimeServiceError(f"unsupported env install target: {normalized_target}")

            normalized_tool_id = str(tool_id or "").strip()
            if not normalized_tool_id:
                raise RuntimeServiceError("tool_id is required for tool_env install")

            spec = self._get_tool_env_spec(normalized_tool_id)
            if not spec["installable"]:
                raise RuntimeServiceError(f"tool env is not installable: {normalized_tool_id}")

            conda_detect = env_detector.detect(self._run_ssh_command)
            if conda_detect.status != env_detector.CondaStatus.OK or not conda_detect.executable:
                raise RuntimeServiceError(conda_detect.message)
            self._remember_managed_conda(conda_detect.executable)

            item = EnvInstaller.submit(
                self._run_ssh_command,
                normalized_tool_id,
                spec["install_cmd"],
                conda_executable=conda_detect.executable,
                verify_cmd=spec["verify_cmd"],
                version_regex=spec["version_regex"],
            )
            return {
                "target": "tool_env",
                "tool_id": normalized_tool_id,
                "job_id": item["job_id"],
                "task_dir": item["task_dir"],
                "message": f"已提交 {spec['name']} 环境安装任务",
            }

    def get_remote_env_install_status(self, *, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_ssh_connected()
            normalized_job_id = str(job_id or "").strip()
            if not normalized_job_id:
                raise RuntimeServiceError("job_id is required")

            if normalized_job_id == miniforge_bootstrap.JOB_ID:
                raw_status = miniforge_bootstrap.check_status(self._run_ssh_command)
                session_alive = miniforge_bootstrap.is_session_alive(self._run_ssh_command)
                log_text = miniforge_bootstrap.read_log(self._run_ssh_command)
                stage = self._normalize_job_stage(
                    status=str(raw_status.get("status") or ""),
                    exit_code=str(raw_status.get("exit_code") or ""),
                    session_alive=session_alive,
                    heartbeat=str(raw_status.get("heartbeat") or ""),
                )
                if stage == "done":
                    conda_detect = env_detector.detect(self._run_ssh_command)
                    if conda_detect.status == env_detector.CondaStatus.OK and conda_detect.executable:
                        self._remember_managed_conda(conda_detect.executable)
                return self._build_job_snapshot(
                    job_id=normalized_job_id,
                    stage=stage,
                    raw_status=raw_status,
                    log_text=log_text,
                )

            if normalized_job_id.startswith(_WORKFLOW_BOOTSTRAP_PREFIX):
                profile_kind = normalized_job_id[len(_WORKFLOW_BOOTSTRAP_PREFIX):].strip()
                if not profile_kind:
                    raise RuntimeServiceError(f"invalid workflow bootstrap job_id: {normalized_job_id}")
                task_dir = workflow_bootstrap_task_dir(profile_kind)
                raw_status, session_alive, log_text = read_workflow_bootstrap_status(
                    self._run_ssh_command,
                    task_dir=task_dir,
                )
                stage = self._normalize_job_stage(
                    status=str(raw_status.get("status") or ""),
                    exit_code=str(raw_status.get("exit_code") or ""),
                    session_alive=session_alive,
                    heartbeat=str(raw_status.get("heartbeat") or ""),
                )
                progress = {
                    "profile_kind": profile_kind,
                    "pid": str(raw_status.get("pid") or ""),
                }
                if raw_status.get("log_preview"):
                    progress["log_preview"] = raw_status["log_preview"]
                return self._build_job_snapshot(
                    job_id=normalized_job_id,
                    stage=stage,
                    raw_status=raw_status,
                    log_text=log_text,
                    progress=progress,
                )

            prefix = "h2o_install_"
            if not normalized_job_id.startswith(prefix):
                raise RuntimeServiceError(f"unsupported env install job_id: {normalized_job_id}")

            tool_id = normalized_job_id[len(prefix):].strip()
            if not tool_id:
                raise RuntimeServiceError(f"invalid env install job_id: {normalized_job_id}")
            task_dir = f"{EnvInstaller.INSTALL_BASE}/{tool_id}"
            raw_status = EnvInstaller.check_status(self._run_ssh_command, task_dir)
            session_alive = EnvInstaller.is_session_alive(self._run_ssh_command, normalized_job_id)
            log_text = EnvInstaller.read_log(self._run_ssh_command, task_dir)
            stage = self._normalize_job_stage(
                status=str(raw_status.get("status") or ""),
                exit_code=str(raw_status.get("exit_code") or ""),
                session_alive=session_alive,
            )
            return self._build_job_snapshot(
                job_id=normalized_job_id,
                stage=stage,
                raw_status=raw_status,
                log_text=log_text,
            )

    def install_database(self, *, project_id: str, db_id: str, mirror_index: int = 0) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            self._ensure_ssh_connected()
            caps = probe_preflight(self._run_ssh_command)
            failures = caps.failures(min_free_disk_gb=MIN_FREE_DISK_GB)
            if failures:
                raise RuntimeServiceError("；".join(failures))
            config = get_config()
            databases_cfg = config.get("databases", {})
            if not isinstance(databases_cfg, dict):
                raise RuntimeServiceError("settings.databases must be an object")
            db_root = str(databases_cfg.get("db_root", "") or "")
            service = DatabaseService()
            item = service.submit_install(
                self._run_ssh_command,
                caps,
                str(db_id or "").strip(),
                db_root,
                conda_exe=self._service_locator.conda_executable,
                mirror_index=int(mirror_index),
            )
            return {
                "db_id": str(db_id or "").strip(),
                "job_id": item["job_id"],
                "task_dir": item["task_dir"],
                "message": "已提交数据库后台安装任务",
            }

    def get_database_install_status(self, *, project_id: str, db_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            self._ensure_ssh_connected()
            normalized_db_id = str(db_id or "").strip()
            if not normalized_db_id:
                raise RuntimeServiceError("db_id is required")
            service = DatabaseService()
            task_dir = f"{service.INSTALL_BASE}/{normalized_db_id}"
            raw_status = service.check_install_status(self._run_ssh_command, task_dir)
            stage = self._normalize_job_stage(
                status=str(raw_status.get("status") or ""),
                exit_code=str(raw_status.get("exit_code") or ""),
                session_alive=bool(raw_status.get("screen_running")),
                heartbeat=str(raw_status.get("heartbeat") or ""),
            )
            log_text = service.read_install_log(self._run_ssh_command, task_dir, tail=120)
            return self._build_job_snapshot(
                job_id=f"h2o_dbinstall_{normalized_db_id}",
                stage=stage,
                raw_status=raw_status,
                log_text=log_text,
                progress=service.parse_progress(log_text),
            )

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
                        install_status = service.check_install_status(
                            self._run_ssh_command,
                            f"{service.INSTALL_BASE}/{info.db_id}",
                        )
                        install_stage = self._normalize_job_stage(
                            status=str(install_status.get("status") or ""),
                            exit_code=str(install_status.get("exit_code") or ""),
                            session_alive=bool(install_status.get("screen_running")),
                            heartbeat=str(install_status.get("heartbeat") or ""),
                        )
                        if install_stage == "running":
                            item["status"] = "installing"
                            item["status_message"] = "数据库后台安装中"
                        else:
                            status = service.check_status(
                                self._run_ssh_command,
                                info.db_id,
                                db_root,
                                overrides=overrides,
                            )
                            item["status"] = status.status.value
                            item["status_message"] = status.message
                        item["install_job_id"] = f"h2o_dbinstall_{info.db_id}"
                        item["install_stage"] = install_stage
                    else:
                        item["status"] = "unknown"
                        item["status_message"] = "SSH disconnected"
                        item["install_job_id"] = f"h2o_dbinstall_{info.db_id}"
                        item["install_stage"] = "idle"
                items.append(item)
            return items

    def list_execution_history(self, *, project_id: str, limit: int = 50, task_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            query = ExecutionQueryService(self._project_manager.db)
            rows = query.get_execution_history_for_ui(limit=limit, task_id=task_id)
            return [self._normalize_execution_row(row) for row in rows]

    def list_execution_history_summary(self, *, project_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            query = ExecutionQueryService(self._project_manager.db)
            rows = query.get_execution_history_summary_for_ui(limit=limit)
            return [self._normalize_execution_row(row) for row in rows]

    def list_task_executions(self, *, project_id: str, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            self._assert_task_exists(project_id=project_id, task_id=task_id)
            query = ExecutionQueryService(self._project_manager.db)
            rows = query.get_execution_history_for_ui(limit=limit, task_id=task_id)
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

    def run_workbench_tool(
        self,
        *,
        project_id: str,
        task_id: str | None,
        tool_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            normalized_task_id = str(task_id or "").strip()
            if not normalized_task_id:
                raise RuntimeServiceError("task_id is required for workbench runs")
            self._assert_task_exists(project_id=project_id, task_id=normalized_task_id)
            try:
                return workbench_runtime_ops.run_workbench_tool(
                    self,
                    project_id=project_id,
                    task_id=normalized_task_id,
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

    def get_project_results(self, *, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            self._ensure_project_open(project_id)
            rows = self._project_manager.db.execute(
                """
                SELECT
                    t.task_id,
                    t.title,
                    t.status AS task_status,
                    t.summary,
                    t.last_activity_at,
                    t.latest_execution_id,
                    e.status AS latest_execution_status,
                    e.tool_id AS latest_tool_id,
                    e.error AS latest_error,
                    COUNT(all_exec.execution_id) AS execution_count,
                    SUM(CASE WHEN all_exec.status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN all_exec.status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM tasks t
                LEFT JOIN executions e ON e.execution_id = t.latest_execution_id
                LEFT JOIN executions all_exec ON all_exec.task_id = t.task_id
                WHERE t.project_id = ?
                GROUP BY t.task_id
                ORDER BY t.last_activity_at DESC, t.created_at DESC
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

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

    def _close_all_terminal_sessions(self, *, message: str, drop_sessions: bool) -> None:
        for session in list(self._terminal_sessions.values()):
            try:
                session.close(message=message, connected=False)
            except Exception:
                logger.debug("Failed to close terminal session %s", session.session_id, exc_info=True)
        if drop_sessions:
            self._terminal_sessions.clear()

    def _remember_managed_conda(self, conda_executable: str) -> None:
        normalized = str(conda_executable or "").strip()
        if not normalized or not is_managed_conda_executable(normalized):
            return
        self._service_locator.conda_executable = normalized
        current = get_config()
        linux = current.get("linux", {})
        current_value = str(linux.get("conda_executable", "") or "").strip() if isinstance(linux, dict) else ""
        if current_value == normalized:
            return
        merged = self._merge_settings_patch(current, {"linux": {"conda_executable": normalized}})
        save_config(merged)

    def _collect_tool_env_specs(self) -> list[dict[str, Any]]:
        registry = self._service_locator.plugin_registry
        grouped: dict[str, dict[str, Any]] = {}
        for tool_id in sorted(registry.list_all_ids()):
            descriptor = registry.get_descriptor(tool_id)
            env_name = derive_conda_env_name(descriptor)
            if not env_name:
                continue
            grouped_entry = grouped.get(env_name)
            if grouped_entry is None:
                grouped_entry = {
                    "tool_id": str(tool_id),
                    "name": str(descriptor.get("name", tool_id) or tool_id),
                    "env_name": env_name,
                    "version": str(descriptor.get("version", "") or ""),
                    "install_cmd": str(descriptor.get("install_cmd", "") or "").strip(),
                    "verify_cmd": str(descriptor.get("detection", {}).get("command", "") or "").strip()
                    if isinstance(descriptor.get("detection"), dict)
                    else "",
                    "version_regex": str(descriptor.get("detection", {}).get("version_regex", "") or "").strip()
                    if isinstance(descriptor.get("detection"), dict)
                    else "",
                    "shared_tool_ids": [str(tool_id)],
                    "installable": bool(str(descriptor.get("install_cmd", "") or "").strip()),
                }
                grouped[env_name] = grouped_entry
                continue
            grouped_entry["shared_tool_ids"].append(str(tool_id))
            install_cmd = str(descriptor.get("install_cmd", "") or "").strip()
            if install_cmd and not grouped_entry["install_cmd"]:
                grouped_entry["tool_id"] = str(tool_id)
                grouped_entry["name"] = str(descriptor.get("name", tool_id) or tool_id)
                grouped_entry["version"] = str(descriptor.get("version", "") or "")
                grouped_entry["install_cmd"] = install_cmd
                grouped_entry["installable"] = True
                if isinstance(descriptor.get("detection"), dict):
                    grouped_entry["verify_cmd"] = str(descriptor["detection"].get("command", "") or "").strip()
                    grouped_entry["version_regex"] = str(descriptor["detection"].get("version_regex", "") or "").strip()
        return list(grouped.values())

    def _get_tool_env_spec(self, tool_id: str) -> dict[str, Any]:
        normalized_tool_id = str(tool_id or "").strip()
        if not normalized_tool_id:
            raise RuntimeServiceError("tool_id is required")
        for spec in self._collect_tool_env_specs():
            if spec["tool_id"] == normalized_tool_id:
                return spec
        raise RuntimeServiceError(f"tool env not found: {normalized_tool_id}")

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
            "message": "" if ok else (log_lines[-1] if log_lines else ""),
        }

    @staticmethod
    def _describe_tool_env_status(*, status: str, conda_message: str, installable: bool) -> str:
        if status == "installed":
            return "环境已就绪"
        if status == "installing":
            return "后台安装中"
        if status == "failed":
            return "最近一次安装失败，请展开日志查看原因"
        if status == "blocked":
            return conda_message or "Miniforge 未就绪"
        if not installable:
            return "当前工具未声明自动安装命令"
        return "尚未安装"

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
    def _normalize_task_row(row: dict[str, Any]) -> dict[str, Any]:
        task_id = str(row.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeServiceError("Invalid task row: missing task_id")
        result_snapshot = row.get("result_snapshot")
        if isinstance(result_snapshot, str):
            try:
                parsed_snapshot = json.loads(result_snapshot) if result_snapshot.strip() else {}
            except json.JSONDecodeError as exc:
                raise RuntimeServiceError(f"Task {task_id} has invalid result snapshot: {exc}") from exc
        elif isinstance(result_snapshot, dict):
            parsed_snapshot = result_snapshot
        else:
            parsed_snapshot = {}
        return {
            "task_id": task_id,
            "project_id": str(row.get("project_id") or ""),
            "title": str(row.get("title") or task_id),
            "description": str(row.get("description") or ""),
            "status": str(row.get("status") or "pending"),
            "created_at": float(row.get("created_at") or 0.0),
            "updated_at": float(row.get("updated_at") or 0.0),
            "last_activity_at": float(row.get("last_activity_at") or 0.0),
            "latest_execution_id": str(row.get("latest_execution_id") or ""),
            "summary": str(row.get("summary") or ""),
            "result_snapshot": parsed_snapshot,
            "execution_count": int(row.get("execution_count") or 0),
            "failed_execution_count": int(row.get("failed_execution_count") or 0),
            "latest_execution_created_at": float(row.get("latest_execution_created_at") or 0.0),
        }

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
            merged.pop("password_ref", None)

        host = str(merged.get("host", "") or "").strip()
        user = str(merged.get("user", "") or "").strip()
        key_file = str(merged.get("key_file", "") or "").strip()
        password = str(patch.get("password", "") or "") if isinstance(patch, dict) and "password" in patch else resolve_ssh_password(merged)
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
                    key_file=ssh_settings["key_file"] if ssh_settings["use_key"] else "",
                    timeout=timeout,
                )
                if not reconnect.ok or reconnect.client is None:
                    raise RuntimeError(reconnect.message)
                return reconnect.client

            self._service_locator.ssh_service = SSHService(initial_client=result.client, connect_fn=_connect_fn)
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
        return int(code), str(getattr(result, "stdout", "")), str(getattr(result, "stderr", ""))

    def _connect_runtime_signals(self) -> None:
        if self._signals_connected:
            return
        self._service_locator.execution_started.connect(self._on_execution_started)
        self._service_locator.execution_completed.connect(self._on_execution_completed)
        self._service_locator.execution_failed.connect(self._on_execution_failed)
        self._service_locator.ssh_changed.connect(self._on_ssh_changed)
        self._signals_connected = True

    def _build_workflow_spec(self, payload: dict[str, Any]) -> WorkflowSpec:
        if not isinstance(payload, dict):
            raise RuntimeServiceError("workflow payload must be an object")
        workflow_id = str(payload.get("workflow_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not workflow_id or not name:
            raise RuntimeServiceError("workflow_id and name are required")
        raw_nodes = payload.get("nodes", [])
        raw_edges = payload.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise RuntimeServiceError("workflow nodes/edges must be arrays")
        nodes = [
            WorkflowNode(
                node_id=str(item.get("node_id") or "").strip(),
                tool_id=str(item.get("tool_id") or "").strip(),
                label=str(item.get("label") or "").strip(),
                params=item.get("params", {}) if isinstance(item.get("params", {}), dict) else {},
            )
            for item in raw_nodes
        ]
        edges = [
            WorkflowEdge(
                edge_id=str(item.get("edge_id") or "").strip(),
                source_node_id=str(item.get("source_node_id") or "").strip(),
                target_node_id=str(item.get("target_node_id") or "").strip(),
                output_name=str(item.get("output_name") or "").strip(),
                input_name=str(item.get("input_name") or "").strip(),
            )
            for item in raw_edges
        ]
        for node in nodes:
            if not node.node_id or not node.tool_id or not node.label:
                raise RuntimeServiceError("workflow node requires node_id, tool_id, and label")
        if len({node.node_id for node in nodes}) != len(nodes):
            raise RuntimeServiceError("workflow node_id must be unique")
        for edge in edges:
            if not edge.edge_id or not edge.source_node_id or not edge.target_node_id:
                raise RuntimeServiceError("workflow edge requires edge_id, source_node_id, and target_node_id")
        if len({edge.edge_id for edge in edges}) != len(edges):
            raise RuntimeServiceError("workflow edge_id must be unique")
        params_schema = payload.get("params_schema", {})
        if not isinstance(params_schema, dict):
            raise RuntimeServiceError("workflow params_schema must be an object")
        return WorkflowSpec(
            workflow_id=workflow_id,
            name=name,
            version=str(payload.get("version") or "0.1.0").strip() or "0.1.0",
            nodes=nodes,
            edges=edges,
            params_schema=params_schema,
        )

    def _build_launch_spec(self, *, project_id: str, launch: dict[str, Any]) -> LaunchSpec:
        if not isinstance(launch, dict):
            raise RuntimeServiceError("launch payload must be an object")
        raw_profile = launch.get("profile", {})
        if not isinstance(raw_profile, dict):
            raise RuntimeServiceError("launch.profile must be an object")
        profile_id = str(raw_profile.get("profile_id") or "").strip()
        server_id = str(raw_profile.get("server_id") or "").strip()
        profile_kind = str(raw_profile.get("profile_kind") or "").strip()
        executor = str(raw_profile.get("executor") or "").strip()
        packaging_mode = str(raw_profile.get("packaging_mode") or "").strip()
        if not profile_id or not server_id or not profile_kind or not executor or not packaging_mode:
            raise RuntimeServiceError("launch.profile is incomplete")
        profile = ServerProfile(
            profile_id=profile_id,
            server_id=server_id,
            profile_kind=profile_kind,  # type: ignore[arg-type]
            executor=executor,
            packaging_mode=packaging_mode,  # type: ignore[arg-type]
            container_runtime=str(raw_profile.get("container_runtime") or "").strip(),
            work_dir=str(raw_profile.get("work_dir") or "").strip(),
            output_dir=str(raw_profile.get("output_dir") or "").strip(),
            cache_dir=str(raw_profile.get("cache_dir") or "").strip(),
        )
        params = launch.get("params", {})
        data_refs = launch.get("data_refs", [])
        if not isinstance(params, dict) or not isinstance(data_refs, list):
            raise RuntimeServiceError("launch params/data_refs have invalid format")
        return LaunchSpec(
            project_id=project_id,
            profile=profile,
            params=params,
            data_refs=[str(item) for item in data_refs],
            resume=bool(launch.get("resume", True)),
        )

    def _workflow_backend_for_row(self, row: dict[str, Any]) -> LocalSSHBackend | SlurmSSHBackend:
        profile_payload = row.get("profile", {})
        if isinstance(profile_payload, dict) and profile_payload:
            profile = ServerProfile(
                profile_id=str(profile_payload.get("profile_id") or row.get("profile_id") or "").strip(),
                server_id=str(profile_payload.get("server_id") or "current").strip(),
                profile_kind=str(profile_payload.get("profile_kind") or "personal_conda").strip(),  # type: ignore[arg-type]
                executor=str(profile_payload.get("executor") or row.get("executor") or "").strip(),
                packaging_mode=str(profile_payload.get("packaging_mode") or row.get("packaging_mode") or "conda").strip(),  # type: ignore[arg-type]
                container_runtime=str(profile_payload.get("container_runtime") or row.get("container_runtime") or "").strip(),
                work_dir=str(profile_payload.get("work_dir") or row.get("remote_work_dir") or "").strip(),
                output_dir=str(profile_payload.get("output_dir") or row.get("remote_output_dir") or "").strip(),
                cache_dir=str(profile_payload.get("cache_dir") or "").strip(),
            )
        else:
            profile = ServerProfile(
                profile_id=str(row.get("profile_id") or "").strip(),
                server_id="current",
                profile_kind="personal_conda",
                executor=str(row.get("executor") or "").strip(),
                packaging_mode=str(row.get("packaging_mode") or "conda").strip(),  # type: ignore[arg-type]
                container_runtime=str(row.get("container_runtime") or "").strip(),
                work_dir=str(row.get("remote_work_dir") or "").strip(),
                output_dir=str(row.get("remote_output_dir") or "").strip(),
                cache_dir="",
            )
        return create_workflow_backend(profile)

    def _profile_from_capabilities(self, caps: Any) -> dict[str, Any]:
        profile_id = caps.recommended_profile_kind
        base_dir = "~/.bioflow"
        return {
            "profile_id": profile_id,
            "server_id": "current",
            "profile_kind": profile_id,
            "executor": caps.recommended_executor,
            "packaging_mode": caps.recommended_packaging_mode,
            "container_runtime": caps.recommended_container_runtime,
            "work_dir": f"{base_dir}/runs/work",
            "output_dir": f"{base_dir}/runs/output",
            "cache_dir": f"{base_dir}/cache/containers"
            if caps.recommended_packaging_mode == "container"
            else f"{base_dir}/cache/conda",
        }

    def _runtime_capabilities_dict(self, caps: Any) -> dict[str, Any]:
        return {
            "java": {"available": caps.has_java, "version": caps.java_version},
            "nextflow": {"available": caps.has_nextflow, "version": caps.nextflow_version},
            "docker": {"available": caps.has_docker},
            "podman": {"available": caps.has_podman},
            "apptainer": {"available": caps.has_apptainer},
            "micromamba": {"available": caps.has_micromamba},
            "conda": {"available": caps.has_conda},
            "sbatch": {"available": caps.has_sbatch},
        }

    def _remote_command_available(self, command: str) -> bool:
        try:
            rc, stdout, _stderr = self._run_ssh_command(f"command -v {shlex.quote(command)}", 10)
            return rc == 0 and bool(stdout.strip())
        except Exception:
            return False

    def _remote_runtime_ok(self, command: str) -> bool:
        try:
            rc, _stdout, _stderr = self._run_ssh_command(command, 15)
            return rc == 0
        except Exception:
            return False

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
