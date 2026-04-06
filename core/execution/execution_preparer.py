"""Async remote preparation for tool executions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from shlex import quote
from typing import Any, Optional

from core.qt_compat import QObject, pyqtSignal

from core.execution.execution_backend import CommandBackend, ExecutionBackend
from core.execution.command_builder import CommandBuilder
from core.execution.task_runner import TaskRunner
from core.execution.workflow_uploader import get_local_workflow_dir, upload_workflow

logger = logging.getLogger(__name__)


@dataclass
class PreparationRequest:
    execution_id: str
    tool_id: str
    sample_id: str
    remote_base: str
    descriptor: dict[str, Any]
    merged_params: dict[str, Any]
    input_paths: dict[str, str]
    database_paths: Optional[dict[str, str]] = None
    conda_executable: str = ""


@dataclass
class PreparationResult:
    execution_id: str
    command: str
    descriptor: dict[str, Any]
    sample_id: str
    output_dir: str
    task_dir: str


class ExecutionPreparer(QObject):
    """Run remote preparation steps before job queue submission."""

    preparation_succeeded = pyqtSignal(str, object)
    preparation_failed = pyqtSignal(str, str)

    def __init__(
        self,
        ssh_service: Any,
        backend: ExecutionBackend | None = None,
        max_threads: int = 3,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ssh = ssh_service
        self._backend = backend or CommandBackend()
        self._task_runner = TaskRunner(max_threads=max_threads, parent=self)
        self._task_runner.task_succeeded.connect(self._on_task_succeeded)
        self._task_runner.task_failed.connect(self._on_task_failed)

    def set_ssh_service(self, ssh_service: Any) -> None:
        self._ssh = ssh_service

    def set_backend(self, backend: ExecutionBackend) -> None:
        self._backend = backend

    def prepare(self, request: PreparationRequest) -> None:
        self._task_runner.submit(self._prepare, request, task_id=request.execution_id)

    def wait_for_done(self, timeout_ms: int = 30000) -> bool:
        return self._task_runner.wait_for_done(timeout_ms)

    def _prepare(self, request: PreparationRequest) -> PreparationResult:
        return self._backend.prepare(self._ssh, request)

    def _on_task_succeeded(self, execution_id: str, result: object) -> None:
        self.preparation_succeeded.emit(execution_id, result)

    def _on_task_failed(self, execution_id: str, error: str) -> None:
        logger.error("Execution preparation failed: %s - %s", execution_id, error)
        self.preparation_failed.emit(execution_id, error)


def prepare_execution(ssh_service: Any, request: PreparationRequest) -> PreparationResult:
    """Run the remote preparation steps synchronously."""
    remote_base = request.remote_base
    if remote_base.startswith("~"):
        rc, expanded, err = ssh_service.run(f"echo {remote_base}", timeout=10)
        if rc != 0 or not expanded.strip():
            raise RuntimeError(err or f"Failed to expand remote base: {remote_base}")
        remote_base = expanded.strip()

    output_dir = (
        f"{remote_base}/intermediate/"
        f"{request.sample_id}/{request.tool_id}_{request.execution_id}"
    )
    rc, _, err = ssh_service.run(f"mkdir -p {quote(output_dir)}", timeout=15)
    if rc != 0:
        raise RuntimeError(err or f"Failed to create output dir: {output_dir}")

    output_paths = CommandBuilder.resolve_output_paths(
        request.descriptor,
        output_dir,
        request.sample_id,
    )
    all_paths = {**request.input_paths, **output_paths}

    workflow_dir = ""
    yaml_path = request.descriptor.get("_yaml_path", "")
    local_wf = get_local_workflow_dir(yaml_path) if yaml_path else None
    if local_wf is not None:
        workflow_dir = f"{output_dir}/workflow"
        upload_workflow(ssh_service, local_wf, workflow_dir)

    command = CommandBuilder.build(
        descriptor=request.descriptor,
        parameters=request.merged_params,
        input_paths=all_paths,
        output_dir=output_dir,
        sample_id=request.sample_id,
        database_paths=request.database_paths,
        conda_executable=request.conda_executable,
        workflow_dir=workflow_dir,
    )

    return PreparationResult(
        execution_id=request.execution_id,
        command=command,
        descriptor=request.descriptor,
        sample_id=request.sample_id,
        output_dir=output_dir,
        task_dir=output_dir,
    )
