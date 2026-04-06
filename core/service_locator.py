"""Service locator wiring the execution pipeline together."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core.qt_compat import QObject, pyqtSignal

from config import get_config
from core.data.data_registry import DataRegistry
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.data.project_manager import ProjectManager
from core.execution.execution_backend import BackendDispatchResult, CommandBackend, ExecutionBackend
from core.execution.execution_preparer import ExecutionPreparer, PreparationRequest, PreparationResult
from core.execution.job_dispatcher import JobDispatcher
from core.execution.job_queue import JobQueue
from core.execution.retry_manager import RetryManager
from core.execution.task_runner import TaskRunner
from core.execution.tool_engine import ToolEngine
from core.plugins.plugin_registry import PluginRegistry
from core.remote.ssh_service import SSHService
from core.remote.server_capabilities import ServerCapabilities
from core.utils import get_app_root

logger = logging.getLogger(__name__)

_DEFAULT_PLUGINS_DIR = get_app_root() / "plugins"


class ServiceLocator(QObject):
    """Connect core services into a runnable application graph."""

    execution_started = pyqtSignal(str)
    execution_completed = pyqtSignal(str)
    execution_failed = pyqtSignal(str, str)
    ssh_changed = pyqtSignal(bool)

    def __init__(
        self,
        ssh_service: Optional[SSHService] = None,
        plugins_dir: Optional[Path] = None,
        project_manager: Optional[ProjectManager] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self._ssh: Optional[SSHService] = ssh_service
        self._plugins_dir = plugins_dir or _DEFAULT_PLUGINS_DIR
        self._plugin_registry = PluginRegistry(self._plugins_dir)
        self._project_manager = project_manager or ProjectManager()
        self._job_queue = JobQueue()
        self._job_dispatcher = JobDispatcher()
        self._execution_backend: ExecutionBackend = CommandBackend()
        self._execution_preparer = ExecutionPreparer(self._ssh or _NullSSH(), backend=self._execution_backend, parent=self)
        self._task_runner = TaskRunner(max_threads=3, parent=self)
        self._retry_manager = RetryManager(retry_callback=self._retry_execution)
        self._data_registry: Optional[DataRegistry] = None
        self._tool_engine: Optional[ToolEngine] = None
        self._execution_ctx: dict[str, dict[str, Any]] = {}
        self._task_dirs: dict[str, str] = {}
        self._conda_executable: str = ""
        self._server_capabilities: Optional[ServerCapabilities] = None
        self._server_capability_error: str = ""
        self._shutting_down = False

    def initialize(self) -> int:
        self._hydrate_conda_executable_from_config()
        count = self._plugin_registry.scan()
        logger.info("ServiceLocator initialized: scanned %d plugins", count)
        self._connect_signals()

        if hasattr(self._project_manager, "project_opened"):
            self._project_manager.project_opened.connect(self._on_project_opened)

        if self._project_manager.current_project is not None:
            self._rebuild_registry_and_engine()

        return count

    def _hydrate_conda_executable_from_config(self) -> None:
        """Load managed conda path from config early to avoid startup empty window."""
        if self._conda_executable:
            return
        try:
            cfg = get_config()
            linux = cfg.get("linux", {}) if isinstance(cfg, dict) else {}
            conda_path = str(linux.get("conda_executable", "") or "").strip()
        except Exception:
            logger.exception("Failed to read conda path from config")
            return

        if not conda_path:
            return

        if not is_managed_conda_executable(conda_path):
            logger.warning("Ignoring non-managed conda path from config: %s", conda_path)
            return

        self.conda_executable = conda_path

    @property
    def ssh_service(self) -> Optional[SSHService]:
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh: SSHService) -> None:
        self._ssh = ssh
        self._execution_preparer.set_ssh_service(ssh)
        self._execution_preparer.set_backend(self._execution_backend)
        if self._data_registry is not None:
            self._rebuild_engine()
        self.ssh_changed.emit(ssh is not None)
        logger.info("SSH service updated")

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    @property
    def project_manager(self) -> ProjectManager:
        return self._project_manager

    @property
    def job_queue(self) -> JobQueue:
        return self._job_queue

    @property
    def retry_manager(self) -> RetryManager:
        return self._retry_manager

    @property
    def data_registry(self) -> Optional[DataRegistry]:
        return self._data_registry

    @property
    def tool_engine(self) -> Optional[ToolEngine]:
        return self._tool_engine

    @property
    def conda_executable(self) -> str:
        return self._conda_executable

    @conda_executable.setter
    def conda_executable(self, path: str) -> None:
        self._conda_executable = path or ""
        if self._data_registry is not None:
            self._rebuild_engine()
        logger.info(
            "conda_executable updated: %s",
            self._conda_executable or "(empty)",
        )

    @property
    def server_capabilities(self) -> Optional[ServerCapabilities]:
        return self._server_capabilities

    @server_capabilities.setter
    def server_capabilities(self, caps: Optional[ServerCapabilities]) -> None:
        self._server_capabilities = caps

    @property
    def server_capability_error(self) -> str:
        return self._server_capability_error

    @server_capability_error.setter
    def server_capability_error(self, message: str) -> None:
        self._server_capability_error = str(message or "")

    def get_task_dir(self, execution_id: str) -> Optional[str]:
        """Return the remote task dir for an execution."""
        return self._task_dirs.get(execution_id)

    def is_execution_waiting(self, execution_id: str) -> bool:
        """Whether execution is currently monitored by JobDispatcher waiter."""
        return self._job_dispatcher.is_waiting(execution_id)

    def resume_execution_waiting(
        self,
        *,
        execution_id: str,
        sample_id: str,
        tool_id: str,
        task_dir: str,
        job_id: str | None = None,
    ) -> bool:
        """Re-attach waiter for an existing running remote execution.

        This does not re-dispatch remote command. It only restores minimal context
        and starts waiter monitoring.
        """
        ssh = self._ssh
        if ssh is None or not getattr(ssh, "is_connected", False):
            return False
        if self._tool_engine is None:
            return False
        if self.is_execution_waiting(execution_id):
            return False

        descriptor = self._plugin_registry.get_descriptor(tool_id)
        self.register_execution_context(
            execution_id=execution_id,
            command="[resumed-existing-job]",
            descriptor=descriptor,
            sample_id=sample_id,
            output_dir=task_dir,
            task_dir=task_dir,
        )
        self._task_dirs[execution_id] = task_dir
        self._job_dispatcher.start_waiting(
            ssh_service=ssh,
            execution_id=execution_id,
            job_id=job_id or f"h2o_{execution_id}",
            task_dir=task_dir,
        )
        logger.info("Execution waiter resumed: %s", execution_id)
        return True

    def _connect_signals(self) -> None:
        self._job_queue.job_started.connect(self._on_dispatch)
        self._execution_preparer.preparation_succeeded.connect(self._on_preparation_succeeded)
        self._execution_preparer.preparation_failed.connect(self._on_preparation_failed)
        self._task_runner.task_succeeded.connect(self._on_dispatch_submitted)
        self._task_runner.task_failed.connect(self._on_dispatch_failed)
        self._job_dispatcher.job_completed.connect(self._on_completed)
        self._job_dispatcher.job_failed.connect(self._on_failed)
        self._retry_manager.retry_exhausted.connect(
            lambda eid, err: logger.warning("Task retries exhausted: %s - %s", eid, err)
        )

    def _on_dispatch(self, execution_id: str) -> None:
        if not self._ssh:
            logger.error("Cannot dispatch task %s: SSH disconnected", execution_id)
            return

        ctx = self._execution_ctx.get(execution_id)
        if not ctx:
            logger.error("Cannot dispatch task %s: missing execution context", execution_id)
            return

        ssh = self._ssh
        self._task_runner.submit(
            self._dispatch_job,
            execution_id,
            ssh,
            task_id=execution_id,
        )

    def _schedule_preparation(self, request: PreparationRequest) -> None:
        self._execution_preparer.prepare(request)

    def _on_preparation_succeeded(self, execution_id: str, payload: object) -> None:
        if self._shutting_down:
            logger.warning("Ignoring preparation completion during shutdown: %s", execution_id)
            return

        if self._tool_engine is None:
            logger.warning("Preparation completed after ToolEngine teardown: %s", execution_id)
            return

        if not isinstance(payload, PreparationResult):
            logger.error("Invalid preparation payload for %s", execution_id)
            self._on_preparation_failed(execution_id, "Preparation result is invalid")
            return

        self.register_execution_context(
            execution_id=execution_id,
            command=payload.command,
            descriptor=payload.descriptor,
            sample_id=payload.sample_id,
            output_dir=payload.output_dir,
            task_dir=payload.task_dir,
        )
        self._job_queue.submit(
            execution_id=execution_id,
            command=payload.command,
            metadata={
                "tool_id": payload.descriptor.get("id", ""),
                "sample_id": payload.sample_id,
            },
        )
        self._tool_engine.mark_execution_running(execution_id)

    def _on_preparation_failed(self, execution_id: str, error: str) -> None:
        if self._shutting_down:
            logger.warning("Ignoring preparation failure during shutdown: %s - %s", execution_id, error)
            return

        if self._tool_engine is not None:
            self._tool_engine.on_job_failed(execution_id, error)
        self.execution_failed.emit(execution_id, error)

    def _dispatch_job(self, execution_id: str, ssh: SSHService) -> dict[str, str]:
        """Run the SSH-heavy dispatch sequence in the thread pool."""
        ctx = self._execution_ctx.get(execution_id)
        if not ctx:
            raise RuntimeError(f"执行上下文丢失: {execution_id}")

        prepared_result = PreparationResult(
            execution_id=execution_id,
            command=ctx["command"],
            descriptor=ctx["descriptor"],
            sample_id=ctx["sample_id"],
            output_dir=ctx["output_dir"],
            task_dir=ctx["task_dir"],
        )
        dispatch_result = self._execution_backend.dispatch(
            execution_id=execution_id,
            prepared_result=prepared_result,
            ssh_service=ssh,
        )
        return {
            "execution_id": dispatch_result.execution_id,
            "job_id": dispatch_result.job_id,
            "task_dir": dispatch_result.task_dir,
        }

    def _on_dispatch_submitted(self, execution_id: str, payload: object) -> None:
        """Finish dispatch bookkeeping on the main thread."""
        if self._shutting_down:
            logger.warning("Ignoring dispatch completion during shutdown: %s", execution_id)
            return

        ctx = self._execution_ctx.get(execution_id)
        ssh = self._ssh
        if ctx is None or ssh is None:
            logger.warning("Dispatch completed after context/SSH was cleared: %s", execution_id)
            return

        if not isinstance(payload, dict):
            logger.error("Invalid dispatch payload for %s", execution_id)
            self._on_failed(execution_id, "任务派发结果无效")
            return

        dispatch_result = BackendDispatchResult(
            execution_id=execution_id,
            job_id=payload["job_id"],
            task_dir=payload["task_dir"],
        )
        self._execution_backend.start_waiting(
            execution_id=execution_id,
            dispatch_result=dispatch_result,
            ssh_service=ssh,
            job_dispatcher=self._job_dispatcher,
        )
        self._task_dirs[execution_id] = dispatch_result.task_dir
        logger.info("Task dispatched: %s -> screen %s", execution_id, dispatch_result.job_id)

    def _on_dispatch_failed(self, execution_id: str, error: str) -> None:
        if self._shutting_down:
            logger.warning("Ignoring dispatch failure during shutdown: %s - %s", execution_id, error)
            return
        logger.error("Task dispatch failed: %s - %s", execution_id, error)
        self._on_failed(execution_id, error)

    def _on_completed(self, execution_id: str) -> None:
        if not self._is_execution_active(execution_id):
            logger.debug("Completion ignored for non-active execution: %s", execution_id)
            self._execution_ctx.pop(execution_id, None)
            self._task_dirs.pop(execution_id, None)
            return

        ctx = self._execution_ctx.pop(execution_id, None)
        self._task_dirs.pop(execution_id, None)
        if not ctx:
            logger.warning("Completion callback missing execution context: %s", execution_id)
            return

        if self._tool_engine:
            self._tool_engine.on_job_completed(
                execution_id=execution_id,
                descriptor=ctx["descriptor"],
                sample_id=ctx["sample_id"],
                output_dir=ctx["output_dir"],
            )

        if self._job_queue.has_job(execution_id):
            self._job_queue.on_job_finished(execution_id)
        self.execution_completed.emit(execution_id)

    def _on_failed(self, execution_id: str, error: str) -> None:
        if not self._is_execution_active(execution_id):
            logger.debug("Failure ignored for non-active execution: %s", execution_id)
            self._execution_ctx.pop(execution_id, None)
            self._task_dirs.pop(execution_id, None)
            return

        ctx = self._execution_ctx.get(execution_id)
        if ctx is None:
            logger.debug("Failure callback ignored for already-handled execution: %s", execution_id)
            return

        if self._job_queue.has_job(execution_id):
            self._job_queue.on_job_finished(execution_id)
        retry_decision = self._retry_manager.on_task_failed(execution_id, error)
        if retry_decision == "auto_retry":
            logger.info("Task entering auto retry: %s", execution_id)
            return

        self._execution_ctx.pop(execution_id, None)
        self._task_dirs.pop(execution_id, None)
        if self._tool_engine:
            self._tool_engine.on_job_failed(execution_id, error)
        self.execution_failed.emit(execution_id, error)

    def _retry_execution(self, execution_id: str) -> None:
        """RetryManager callback using the original execution context."""
        ctx = self._execution_ctx.get(execution_id)
        if ctx is None:
            raise RuntimeError(f"重试失败：找不到执行上下文 {execution_id}")
        if self._ssh is None:
            raise RuntimeError(f"重试失败：SSH 未连接 ({execution_id})")

        self._job_queue.submit(
            execution_id=execution_id,
            command=ctx["command"],
            metadata={
                "tool_id": ctx["descriptor"].get("id", ""),
                "sample_id": ctx["sample_id"],
                "retry": True,
            },
        )
        logger.info("Task resubmitted: %s", execution_id)

    def _on_project_opened(self, project_id: str) -> None:
        logger.info("Project switched: %s, rebuilding DataRegistry", project_id)
        self._rebuild_registry_and_engine()

    def _rebuild_registry_and_engine(self) -> None:
        try:
            db = self._project_manager.db
            self._data_registry = DataRegistry(db)
            self._rebuild_engine()
        except Exception:
            logger.exception("Failed to rebuild DataRegistry")

    def _rebuild_engine(self) -> None:
        if self._data_registry is None:
            return

        self._tool_engine = ToolEngine(
            ssh_service=self._ssh or _NullSSH(),
            plugin_registry=self._plugin_registry,
            project_manager=self._project_manager,
            data_registry=self._data_registry,
            job_queue=self._job_queue,
            schedule_preparation_fn=self._schedule_preparation,
            conda_executable=self._conda_executable,
        )
        self._tool_engine.execution_started.connect(self.execution_started.emit)

    def register_execution_context(
        self,
        execution_id: str,
        command: str,
        descriptor: dict[str, Any],
        sample_id: str,
        output_dir: str,
        task_dir: str,
    ) -> None:
        self._execution_ctx[execution_id] = {
            "command": command,
            "descriptor": descriptor,
            "sample_id": sample_id,
            "output_dir": output_dir,
            "task_dir": task_dir,
        }

    def shutdown(self) -> None:
        self._shutting_down = True

        try:
            self._job_queue.job_started.disconnect(self._on_dispatch)
        except (TypeError, RuntimeError):
            pass
        try:
            self._execution_preparer.preparation_succeeded.disconnect(self._on_preparation_succeeded)
        except (TypeError, RuntimeError):
            pass
        try:
            self._execution_preparer.preparation_failed.disconnect(self._on_preparation_failed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._task_runner.task_succeeded.disconnect(self._on_dispatch_submitted)
        except (TypeError, RuntimeError):
            pass
        try:
            self._task_runner.task_failed.disconnect(self._on_dispatch_failed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._job_dispatcher.job_completed.disconnect(self._on_completed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._job_dispatcher.job_failed.disconnect(self._on_failed)
        except (TypeError, RuntimeError):
            pass
        if hasattr(self._project_manager, "project_opened"):
            try:
                self._project_manager.project_opened.disconnect(self._on_project_opened)
            except (TypeError, RuntimeError):
                pass
        if self._tool_engine is not None:
            try:
                self._tool_engine.execution_started.disconnect(self.execution_started.emit)
            except (TypeError, RuntimeError):
                pass

        if not self._execution_preparer.wait_for_done(timeout_ms=30000):
            logger.warning("ExecutionPreparer shutdown wait timed out")
        if not self._task_runner.wait_for_done(timeout_ms=30000):
            logger.warning("TaskRunner shutdown wait timed out")
        self._job_dispatcher.stop_all()
        self._execution_ctx.clear()
        self._task_dirs.clear()
        self._tool_engine = None
        self._data_registry = None
        if self._ssh is not None and hasattr(self._ssh, "close"):
            try:
                self._ssh.close()
            except Exception:
                logger.debug("SSH service close failed during shutdown", exc_info=True)
        self._ssh = None
        self._project_manager.close()
        logger.info("ServiceLocator closed")

    def _is_execution_active(self, execution_id: str) -> bool:
        """Check DB status to prevent duplicated terminal transitions."""
        try:
            row = self._project_manager.db.execute(
                "SELECT status, archived_at FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        except Exception:
            return True
        if row is None:
            return False
        if row["archived_at"] is not None:
            return False
        status = str(row["status"] or "").strip().lower()
        return status in {"pending", "running", "retrying"}


class _NullSSH:
    """Empty SSH implementation."""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        raise RuntimeError("SSH 未连接")

    def upload(self, local_path: str, remote_path: str) -> None:
        raise RuntimeError("SSH 未连接")
