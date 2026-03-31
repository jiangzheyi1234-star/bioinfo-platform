"""Execution backend seam for prepare/dispatch/wait responsibilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from core.execution.command_builder import CommandBuilder
from core.execution.job_dispatcher import JobDispatcher

if TYPE_CHECKING:
    from core.execution.execution_preparer import PreparationRequest, PreparationResult


class BackendCapabilityError(RuntimeError):
    """Raised when a backend capability is declared but not implemented."""


@dataclass(frozen=True)
class BackendDispatchResult:
    execution_id: str
    job_id: str
    task_dir: str


@dataclass(frozen=True)
class BackendResultLocation:
    output_dir: str
    task_dir: str


class SupportsRun(Protocol):
    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...


class ExecutionBackend(Protocol):
    backend_id: str
    supports_prepare: bool
    supports_dispatch: bool
    supports_waiting: bool
    supports_result_location: bool

    def prepare(self, ssh_service: Any, request: PreparationRequest) -> PreparationResult: ...

    def dispatch(
        self,
        execution_id: str,
        prepared_result: PreparationResult,
        ssh_service: Any,
    ) -> BackendDispatchResult: ...

    def start_waiting(
        self,
        execution_id: str,
        dispatch_result: BackendDispatchResult,
        ssh_service: Any,
        job_dispatcher: JobDispatcher,
    ) -> None: ...

    def describe_result_location(self, payload: PreparationResult | dict[str, Any]) -> BackendResultLocation: ...


class CommandBackend:
    """Default backend that preserves the current command-based execution journey."""

    backend_id = "command"
    supports_prepare = True
    supports_dispatch = True
    supports_waiting = True
    supports_result_location = True

    def prepare(self, ssh_service: Any, request: PreparationRequest) -> PreparationResult:
        from core.execution.execution_preparer import prepare_execution

        return prepare_execution(ssh_service, request)

    def dispatch(
        self,
        execution_id: str,
        prepared_result: PreparationResult,
        ssh_service: Any,
    ) -> BackendDispatchResult:
        wrapped = CommandBuilder.wrap(
            prepared_result.command,
            f"h2o_{execution_id}",
            prepared_result.task_dir,
        )
        job_id = JobDispatcher.submit(
            ssh_service=ssh_service,
            wrapped_script=wrapped,
            execution_id=execution_id,
            task_dir=prepared_result.task_dir,
        )
        return BackendDispatchResult(
            execution_id=execution_id,
            job_id=job_id,
            task_dir=prepared_result.task_dir,
        )

    def start_waiting(
        self,
        execution_id: str,
        dispatch_result: BackendDispatchResult,
        ssh_service: Any,
        job_dispatcher: JobDispatcher,
    ) -> None:
        job_dispatcher.start_waiting(
            ssh_service=ssh_service,
            execution_id=execution_id,
            job_id=dispatch_result.job_id,
            task_dir=dispatch_result.task_dir,
        )

    def describe_result_location(self, payload: PreparationResult | dict[str, Any]) -> BackendResultLocation:
        from core.execution.execution_preparer import PreparationResult

        if isinstance(payload, PreparationResult):
            output_dir = str(payload.output_dir or "").strip()
            task_dir = str(payload.task_dir or "").strip()
        else:
            output_dir = str(payload.get("output_dir") or "").strip()
            task_dir = str(payload.get("task_dir") or output_dir).strip()
        return BackendResultLocation(output_dir=output_dir, task_dir=task_dir)


class NextflowBackend:
    """Capability placeholder. It is intentionally not wired into the default path."""

    backend_id = "nextflow"
    supports_prepare = False
    supports_dispatch = False
    supports_waiting = False
    supports_result_location = True

    def _unsupported(self, capability: str) -> None:
        raise BackendCapabilityError(
            f"Execution backend '{self.backend_id}' does not support capability: {capability}"
        )

    def prepare(self, ssh_service: Any, request: PreparationRequest) -> PreparationResult:
        self._unsupported("prepare")

    def dispatch(
        self,
        execution_id: str,
        prepared_result: PreparationResult,
        ssh_service: Any,
    ) -> BackendDispatchResult:
        self._unsupported("dispatch")

    def start_waiting(
        self,
        execution_id: str,
        dispatch_result: BackendDispatchResult,
        ssh_service: Any,
        job_dispatcher: JobDispatcher,
    ) -> None:
        self._unsupported("start_waiting")

    def describe_result_location(self, payload: PreparationResult | dict[str, Any]) -> BackendResultLocation:
        from core.execution.execution_preparer import PreparationResult

        if isinstance(payload, PreparationResult):
            output_dir = str(payload.output_dir or "").strip()
        else:
            output_dir = str(payload.get("output_dir") or "").strip()
        return BackendResultLocation(output_dir=output_dir, task_dir=output_dir)
