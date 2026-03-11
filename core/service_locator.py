"""服务总线 — 连接所有 Phase 1 模块为可运行的整体。

职责:
  1. 持有 SSHService 引用（从 SettingsPage 注入，可 hot-swap）
  2. 创建和管理 PluginRegistry、ProjectManager、JobQueue、JobDispatcher 等
  3. 信号链路:
     JobQueue.job_started → _on_dispatch → CommandBuilder.wrap() → JobDispatcher.submit()
       → JobDispatcher.start_waiting() (事件驱动)
       → JobDispatcher.job_completed → _on_completed → ToolEngine.on_job_completed()
       → JobQueue.on_job_finished()
     JobDispatcher.job_failed → _on_failed → RetryManager.on_task_failed()
  4. 监听 ProjectManager.project_opened → 重建 DataRegistry

事件驱动模式:
  - JobDispatcher 在后台线程中同步等待 screen 会话结束
  - 任务完成后通过信号通知，不依赖固定轮询
  - JobMonitor 保留作为 fallback
"""

import logging
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.command_builder import CommandBuilder
from core.data_registry import DataRegistry
from core.job_dispatcher import JobDispatcher
from core.job_monitor import JobMonitor
from core.job_queue import JobQueue
from core.plugin_registry import PluginRegistry
from core.project_manager import ProjectManager
from core.retry_manager import RetryManager
from core.ssh_service import SSHService
from core.tool_engine import ToolEngine

logger = logging.getLogger(__name__)

_DEFAULT_PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


class ServiceLocator(QObject):
    """服务总线 — 将所有核心模块连接成可运行的整体。"""

    execution_started = pyqtSignal(str)
    execution_completed = pyqtSignal(str)
    execution_failed = pyqtSignal(str, str)
    ssh_changed = pyqtSignal(bool)

    def __init__(
        self,
        ssh_service: Optional[SSHService] = None,
        plugins_dir: Optional[Path] = None,
        project_manager: Optional[ProjectManager] = None,
        max_concurrent: int = 3,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self._ssh: Optional[SSHService] = ssh_service
        self._plugins_dir = plugins_dir or _DEFAULT_PLUGINS_DIR
        self._plugin_registry = PluginRegistry(self._plugins_dir)
        self._project_manager = project_manager or ProjectManager()
        self._job_queue = JobQueue(max_concurrent=max_concurrent)
        self._job_monitor = JobMonitor()
        self._job_dispatcher = JobDispatcher()  # 事件驱动核心
        self._retry_manager = RetryManager()
        self._data_registry: Optional[DataRegistry] = None
        self._tool_engine: Optional[ToolEngine] = None
        self._execution_ctx: dict[str, dict[str, Any]] = {}
        self._conda_executable: str = ""

    def initialize(self) -> int:
        count = self._plugin_registry.scan()
        logger.info("ServiceLocator 初始化: 扫描到 %d 个插件", count)
        self._connect_signals()

        if hasattr(self._project_manager, "project_opened"):
            self._project_manager.project_opened.connect(self._on_project_opened)

        if self._project_manager.current_project is not None:
            self._rebuild_registry_and_engine()

        return count

    @property
    def ssh_service(self) -> Optional[SSHService]:
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh: SSHService) -> None:
        self._ssh = ssh
        if self._data_registry is not None:
            self._rebuild_engine()
        self.ssh_changed.emit(ssh is not None)
        logger.info("SSH 服务已更新")

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
    def job_monitor(self) -> JobMonitor:
        return self._job_monitor

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
        logger.info("conda_executable 已更新: %s", self._conda_executable or "(空)")

    def update_max_concurrent(self, n: int) -> None:
        self._job_queue.update_max_concurrent(n)

    def _connect_signals(self) -> None:
        self._job_queue.job_started.connect(self._on_dispatch)
        # 事件驱动：JobDispatcher 的信号
        self._job_dispatcher.job_completed.connect(self._on_completed)
        self._job_dispatcher.job_failed.connect(self._on_failed)
        # Fallback：JobMonitor 的信号（保留以防事件驱动失败）
        self._job_monitor.job_completed.connect(self._on_completed)
        self._job_monitor.job_failed.connect(self._on_failed)
        self._retry_manager.retry_exhausted.connect(
            lambda eid, err: logger.warning("任务重试用尽: %s — %s", eid, err)
        )

    def _on_dispatch(self, execution_id: str) -> None:
        if not self._ssh:
            logger.error("无法派发任务 %s: SSH 未连接", execution_id)
            return

        ctx = self._execution_ctx.get(execution_id)
        if not ctx:
            logger.error("无法派发任务 %s: 找不到执行上下文", execution_id)
            return

        try:
            command = ctx["command"]
            task_dir = ctx["task_dir"]
            job_id = f"h2o_{execution_id}"
            wrapped = CommandBuilder.wrap(command, job_id, task_dir)

            JobDispatcher.submit(
                ssh_service=self._ssh,
                wrapped_script=wrapped,
                execution_id=execution_id,
                task_dir=task_dir,
            )

            # 事件驱动：启动后台等待线程
            self._job_dispatcher.start_waiting(
                ssh_service=self._ssh,
                execution_id=execution_id,
                job_id=job_id,
                task_dir=task_dir,
            )

            # Fallback：同时添加到 JobMonitor（以防事件驱动线程异常退出）
            self._job_monitor.add_job(
                execution_id=execution_id,
                job_id=job_id,
                task_dir=task_dir,
                ssh_service=self._ssh,
            )

            if not self._job_monitor.isRunning():
                self._job_monitor.start()

            logger.info("任务已派发: %s → screen %s", execution_id, job_id)
        except Exception as e:
            logger.exception("任务派发失败: %s", execution_id)
            self._on_failed(execution_id, str(e))

    def _on_completed(self, execution_id: str) -> None:
        ctx = self._execution_ctx.pop(execution_id, None)
        if not ctx:
            logger.warning("完成回调: 找不到执行上下文 %s", execution_id)
            return

        if self._tool_engine:
            self._tool_engine.on_job_completed(
                execution_id=execution_id,
                descriptor=ctx["descriptor"],
                sample_id=ctx["sample_id"],
                output_dir=ctx["output_dir"],
            )

        self._job_queue.on_job_finished(execution_id)
        self.execution_completed.emit(execution_id)

    def _on_failed(self, execution_id: str, error: str) -> None:
        # 幂等保护：防止重复处理（事件驱动和 JobMonitor fallback 同时触发）
        # 如果上下文已被弹出，说明已处理过，跳过
        ctx = self._execution_ctx.get(execution_id)
        if ctx is None:
            logger.debug("失败回调: 上下文已处理 %s", execution_id)
            return

        # 弹出上下文，防止后续重复处理
        self._execution_ctx.pop(execution_id, None)

        if self._tool_engine:
            self._tool_engine.on_job_failed(execution_id, error)

        self._retry_manager.on_task_failed(execution_id, error)
        self._job_queue.on_job_finished(execution_id)
        self.execution_failed.emit(execution_id, error)

    def _on_project_opened(self, project_id: str) -> None:
        logger.info("项目切换: %s, 重建 DataRegistry", project_id)
        self._rebuild_registry_and_engine()

    def _rebuild_registry_and_engine(self) -> None:
        try:
            db = self._project_manager.db
            self._data_registry = DataRegistry(db)
            self._rebuild_engine()
        except Exception:
            logger.exception("重建 DataRegistry 失败")

    def _rebuild_engine(self) -> None:
        if self._data_registry is None:
            return

        self._tool_engine = ToolEngine(
            ssh_service=self._ssh or _NullSSH(),
            plugin_registry=self._plugin_registry,
            project_manager=self._project_manager,
            data_registry=self._data_registry,
            job_queue=self._job_queue,
            context_register_fn=self.register_execution_context,
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
        # 停止事件驱动的等待线程
        self._job_dispatcher.stop_all()
        # 停止 JobMonitor
        self._job_monitor.request_stop()
        if self._job_monitor.isRunning():
            self._job_monitor.wait(5000)
        self._project_manager.close()
        logger.info("ServiceLocator 已关闭")


class _NullSSH:
    """空 SSH 实现。"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        raise RuntimeError("SSH 未连接")

    def upload(self, local_path: str, remote_path: str) -> None:
        raise RuntimeError("SSH 未连接")
