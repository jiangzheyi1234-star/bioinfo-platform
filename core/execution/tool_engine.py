"""Tool execution orchestration and persistence."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Any, Callable, Optional, Protocol

from core.qt_compat import QObject, pyqtSignal

from core.data.data_registry import DataRegistry
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.execution.artifact_store import ArtifactStore
from core.execution.command_builder import CommandBuilder
from core.execution.execution_preparer import PreparationRequest, prepare_execution

logger = logging.getLogger(__name__)


class PluginRegistryProtocol(Protocol):
    def get_descriptor(self, tool_id: str) -> dict[str, Any]: ...


class ProjectManagerProtocol(Protocol):
    @property
    def current_project(self) -> Any: ...

    @property
    def db(self) -> Any: ...

    @property
    def current_project_dir(self) -> Any: ...


class SSHServiceProtocol(Protocol):
    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...

    def download(self, remote_path: str, local_path: str) -> None: ...


class JobQueueProtocol(Protocol):
    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Any = None,
        metadata: Any = None,
    ) -> str: ...


@dataclass
class ExecutionRecord:
    execution_id: str
    sample_id: str
    tool_id: str
    tool_version: str
    parameters: dict[str, Any]
    status: str
    triggered_by: str
    created_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    retry_of: Optional[str] = None
    remote_job_id: Optional[str] = None
    is_final_version: int = 0
    archived_at: Optional[float] = None


class ToolEngine(QObject):
    """Unified entrypoint for tool execution lifecycle."""

    execution_started = pyqtSignal(str)
    execution_completed = pyqtSignal(str)
    execution_failed = pyqtSignal(str, str)

    _EXTRA_RESULT_ARTIFACTS = {
        "primer_design": [
            "primer_result_final_2.txt",
            "primer_result_final.txt",
            "primer_result.txt",
            "dimer_score.txt",
        ],
        "multiplex_primer_panel": [
            "multiplex_panel.txt",
            "synthesis_order.txt",
            "pool_cross_dimer.txt",
            "insilico_pcr_result.txt",
            "optimization_log.txt",
        ],
    }

    def __init__(
        self,
        ssh_service: SSHServiceProtocol,
        plugin_registry: PluginRegistryProtocol,
        project_manager: ProjectManagerProtocol,
        data_registry: DataRegistry,
        job_queue: JobQueueProtocol,
        schedule_preparation_fn: Optional[Callable[[PreparationRequest], None]] = None,
        conda_executable: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._ssh = ssh_service
        self._plugins = plugin_registry
        self._projects = project_manager
        self._registry = data_registry
        self._queue = job_queue
        self._schedule_preparation_fn = schedule_preparation_fn
        self._conda_executable = conda_executable

    def execute(
        self,
        tool_id: str,
        input_data_ids: list[str],
        parameters: dict[str, Any],
        sample_id: str,
        triggered_by: str = "manual",
        database_paths: Optional[dict[str, str]] = None,
    ) -> str:
        project = self._projects.current_project
        if project is None:
            raise ValueError("请先选择或创建项目")

        descriptor = self._plugins.get_descriptor(tool_id)
        conda_env = str(descriptor.get("conda_env", "") or "").strip()
        if conda_env and not is_managed_conda_executable(self._conda_executable):
            logger.warning(
                "Execution blocked: conda runtime not ready (tool=%s, conda_env=%s, conda_executable=%r)",
                tool_id,
                conda_env,
                self._conda_executable,
            )
            raise ValueError("运行环境未就绪，请先在系统设置完成运行环境初始化")

        merged_params = self._merge_defaults(descriptor, parameters)
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        input_paths = self._resolve_inputs(descriptor, input_data_ids)

        record = ExecutionRecord(
            execution_id=execution_id,
            sample_id=sample_id,
            tool_id=tool_id,
            tool_version=descriptor.get("version", "unknown"),
            parameters=merged_params,
            status="pending",
            triggered_by=triggered_by,
            created_at=time.time(),
        )
        db = self._projects.db
        try:
            self._save_record(record, commit=False)
            for data_id in input_data_ids:
                self._registry.add_execution_io(execution_id, data_id, "input", commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise

        request = PreparationRequest(
            execution_id=execution_id,
            tool_id=tool_id,
            sample_id=sample_id,
            remote_base=project.remote_base,
            descriptor=descriptor,
            merged_params=merged_params,
            input_paths=input_paths,
            database_paths=database_paths,
            conda_executable=self._conda_executable,
        )
        if self._schedule_preparation_fn is not None:
            self._schedule_preparation_fn(request)
        else:
            result = prepare_execution(self._ssh, request)
            self._queue.submit(
                execution_id=execution_id,
                command=result.command,
                metadata={"tool_id": tool_id, "sample_id": sample_id},
            )
            self.mark_execution_running(execution_id)

        self.execution_started.emit(execution_id)
        logger.info(
            "Execution submitted for preparation: %s (tool=%s, sample=%s, triggered_by=%s)",
            execution_id,
            tool_id,
            sample_id,
            triggered_by,
        )
        return execution_id

    def mark_execution_running(self, execution_id: str) -> None:
        self._update_execution_fields(execution_id, status="running")

    def on_job_completed(
        self,
        execution_id: str,
        descriptor: dict[str, Any],
        sample_id: str,
        output_dir: str,
    ) -> None:
        try:
            resolved_paths = CommandBuilder.resolve_output_paths(
                descriptor,
                output_dir,
                sample_id,
            )
            registered_outputs: list[dict[str, str]] = []

            for output_def in descriptor.get("outputs", []):
                name = output_def["name"]
                file_path = resolved_paths.get(name, "")
                data_type = output_def.get("type", "unknown")
                tier = output_def.get("tier", "result")

                if not file_path:
                    logger.warning("Output path could not be resolved: %s (%s)", name, execution_id)
                    continue

                try:
                    rc, _, _ = self._ssh.run(f"test -f {quote(file_path)}", timeout=10)
                    if rc != 0:
                        logger.warning("Output file missing, skipping registration: %s", file_path)
                        continue
                except Exception:
                    logger.debug("Could not verify output file existence, continuing: %s", file_path)

                data_id = self._registry.register_output(
                    execution_id=execution_id,
                    file_path=file_path,
                    data_type=data_type,
                    sample_id=sample_id,
                    tier=tier,
                    commit=False,
                )
                registered_outputs.append(
                    {"data_id": data_id, "remote_path": file_path}
                )

            self._download_execution_artifacts(
                execution_id=execution_id,
                descriptor=descriptor,
                output_dir=output_dir,
                registered_outputs=registered_outputs,
            )
            self._update_execution_fields(
                execution_id=execution_id,
                status="completed",
                completed_at=time.time(),
                error=None,
                commit=False,
            )
            self._projects.db.commit()

            logger.info("Execution completed: %s", execution_id)
            self.execution_completed.emit(execution_id)
        except Exception as exc:
            try:
                self._projects.db.rollback()
            except Exception:
                logger.debug("Rollback after completion failure failed", exc_info=True)
            logger.exception("Error while handling completion: %s", execution_id)
            self.on_job_failed(execution_id, str(exc))

    def on_job_failed(self, execution_id: str, error: str) -> None:
        self._update_execution_fields(
            execution_id=execution_id,
            status="failed",
            error=error,
        )

        logger.error("Execution failed: %s - %s", execution_id, error)
        self.execution_failed.emit(execution_id, error)

    def _download_execution_artifacts(
        self,
        execution_id: str,
        descriptor: dict[str, Any],
        output_dir: str,
        registered_outputs: list[dict[str, str]],
    ) -> None:
        project_dir = getattr(self._projects, "current_project_dir", None)
        if project_dir is None:
            logger.warning("Current project dir unavailable, skipping artifact download: %s", execution_id)
            return

        results_dir = Path(project_dir) / "results" / execution_id
        results_dir.mkdir(parents=True, exist_ok=True)

        tool_id = str(descriptor.get("id", "") or "")
        remote_by_name = {
            Path(item["remote_path"]).name: item["remote_path"]
            for item in registered_outputs
            if item.get("remote_path")
        }
        data_id_by_name = {
            Path(item["remote_path"]).name: item["data_id"]
            for item in registered_outputs
            if item.get("remote_path") and item.get("data_id")
        }
        artifact_names = list(remote_by_name.keys())
        artifact_names.extend(self._EXTRA_RESULT_ARTIFACTS.get(tool_id, []))

        ordered_names: list[str] = []
        seen: set[str] = set()
        for name in artifact_names:
            normalized = str(name or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered_names.append(normalized)

        manifest: list[dict[str, Any]] = []
        metadata_updates: list[tuple[str, dict[str, Any]]] = []
        for name in ordered_names:
            remote_path = remote_by_name.get(name) or f"{output_dir.rstrip('/')}/{name}"
            local_path = results_dir / name
            available = False
            error = ""
            try:
                self._ssh.download(remote_path, str(local_path))
                available = local_path.exists()
            except Exception as exc:
                error = str(exc)
                logger.warning(
                    "Artifact download failed: %s -> %s (%s)",
                    remote_path,
                    local_path,
                    exc,
                )

            artifact = {
                "name": name,
                "remote_path": remote_path,
                "local_path": str(local_path),
                "available": available,
                **ArtifactStore.infer_artifact_metadata(name),
            }
            if error:
                artifact["error"] = error
            manifest.append(artifact)

            data_id = data_id_by_name.get(name)
            if data_id:
                metadata_updates.append(
                    (
                        data_id,
                        {
                            "local_path": str(local_path),
                            "artifact_available": available,
                        },
                    )
                )

        for data_id, metadata in metadata_updates:
            self._registry.update_item_metadata(
                data_id,
                metadata,
                commit=False,
            )

        manifest_path = results_dir / "artifacts_manifest.json"
        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "execution_id": execution_id,
                        "tool_id": tool_id,
                        "output_dir": output_dir,
                        "artifacts": manifest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write artifact manifest: %s", manifest_path)

    def get_record(self, execution_id: str) -> Optional[ExecutionRecord]:
        db = self._projects.db
        row = db.execute(
            "SELECT * FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _merge_defaults(
        descriptor: dict[str, Any],
        user_params: dict[str, Any],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for param_def in descriptor.get("parameters", []):
            name = param_def["name"]
            if name in user_params:
                merged[name] = user_params[name]
            elif "default" in param_def:
                merged[name] = param_def["default"]
        for key, value in user_params.items():
            if key not in merged:
                merged[key] = value
        return merged

    def _resolve_inputs(
        self,
        descriptor: dict[str, Any],
        input_data_ids: list[str],
    ) -> dict[str, str]:
        inputs_def = descriptor.get("inputs", [])
        paths: dict[str, str] = {}

        for index, inp_def in enumerate(inputs_def):
            inp_name = inp_def["name"]
            required = inp_def.get("required", True)

            if index < len(input_data_ids):
                item = self._registry.get_item(input_data_ids[index])
                if item is None:
                    raise ValueError(f"输入数据不存在: {input_data_ids[index]}")
                paths[inp_name] = item.file_path
            elif required:
                raise ValueError(f"缺少必需的输入: {inp_name}")

        return paths

    def _save_record(self, record: ExecutionRecord, *, commit: bool = True) -> None:
        db = self._projects.db
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at, completed_at, error, "
            "retry_count, retry_of, remote_job_id, is_final_version, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.execution_id,
                record.sample_id,
                record.tool_id,
                record.tool_version,
                json.dumps(record.parameters, ensure_ascii=False),
                record.status,
                record.triggered_by,
                record.created_at,
                record.completed_at,
                record.error,
                record.retry_count,
                record.retry_of,
                record.remote_job_id,
                record.is_final_version,
                record.archived_at,
            ),
        )
        if commit:
            db.commit()

    def _update_execution_fields(
        self,
        execution_id: str,
        *,
        status: Optional[str] = None,
        completed_at: Optional[float] = None,
        error: Optional[str] = None,
        commit: bool = True,
    ) -> None:
        updates: list[str] = []
        values: list[Any] = []

        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if completed_at is not None:
            updates.append("completed_at = ?")
            values.append(completed_at)
        # Completed execution should clear previous error.
        if error is not None or status == "completed":
            updates.append("error = ?")
            values.append(error)

        if not updates:
            return

        values.append(execution_id)
        db = self._projects.db
        db.execute(
            f"UPDATE executions SET {', '.join(updates)} WHERE execution_id = ?",
            tuple(values),
        )
        if commit:
            db.commit()

    @staticmethod
    def _row_to_record(row: Any) -> ExecutionRecord:
        params_str = row["parameters"]
        parameters = json.loads(params_str) if params_str else {}

        try:
            is_final_version = row["is_final_version"]
        except (KeyError, IndexError):
            is_final_version = 0

        try:
            archived_at = row["archived_at"]
        except (KeyError, IndexError):
            archived_at = None

        return ExecutionRecord(
            execution_id=row["execution_id"],
            sample_id=row["sample_id"],
            tool_id=row["tool_id"],
            tool_version=row["tool_version"],
            parameters=parameters,
            status=row["status"],
            triggered_by=row["triggered_by"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            retry_count=row["retry_count"],
            retry_of=row["retry_of"],
            remote_job_id=row["remote_job_id"],
            is_final_version=is_final_version,
            archived_at=archived_at,
        )
