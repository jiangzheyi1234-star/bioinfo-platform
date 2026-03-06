"""服务总线 — 连接所有 Phase 1 模块为可运行的整体。

职责:
  1. 持有 SSHService 引用（从 SettingsPage 注入，可 hot-swap）
  2. 创建和管理 PluginRegistry、ProjectManager、JobQueue、JobMonitor 等
  3. 信号链路:
     JobQueue.job_started → _on_dispatch → CommandBuilder.wrap() → JobDispatcher.submit()
       → JobMonitor.add_job()
     JobMonitor.job_completed → _on_completed → ToolEngine.on_job_completed()
       → JobQueue.on_job_finished()
     JobMonitor.job_failed → RetryManager.on_task_failed()
  4. 监听 ProjectManager.project_opened → 重建 DataRegistry
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

# 默认 plugins 目录
_DEFAULT_PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


class ServiceLocator(QObject):
    """服务总线 — 将所有核心模块连接成可运行的整体。

    典型用法 (在 MainWindow.__init__ 中)::

        locator = ServiceLocator(ssh_service=ssh_svc)
        locator.initialize()
        # 将 locator 传入各页面
    """

    # 信号: 任务状态变化（供 UI 层监听）
    execution_started = pyqtSignal(str)       # execution_id
    execution_completed = pyqtSignal(str)     # execution_id
    execution_failed = pyqtSignal(str, str)   # execution_id, error
    ssh_changed = pyqtSignal(bool)            # connected

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

        # 核心模块
        self._plugin_registry = PluginRegistry(self._plugins_dir)
        self._project_manager = project_manager or ProjectManager()
        self._job_queue = JobQueue(max_concurrent=max_concurrent)
        self._job_monitor = JobMonitor()
        self._retry_manager = RetryManager()
        self._data_registry: Optional[DataRegistry] = None
        self._tool_engine: Optional[ToolEngine] = None

        # 执行上下文缓存: execution_id -> {tool_id, sample_id, output_dir, descriptor}
        self._execution_ctx: dict[str, dict[str, Any]] = {}

    def initialize(self) -> int:
        """初始化服务总线: 扫描插件 + 连接信号链路。

        Returns:
            扫描到的插件数量。
        """
        # 1. 扫描插件
        count = self._plugin_registry.scan()
        logger.info("ServiceLocator 初始化: 扫描到 %d 个插件", count)

        # 2. 连接信号链路
        self._connect_signals()

        # 3. 监听项目切换（ProjectManager 可能是 Protocol mock，需 hasattr 检查）
        if hasattr(self._project_manager, 'project_opened'):
            self._project_manager.project_opened.connect(self._on_project_opened)

        # 4. 如果已有项目打开，立即构建 DataRegistry + ToolEngine
        if self._project_manager.current_project is not None:
            self._rebuild_registry_and_engine()

        return count

    # ── 属性访问 ──────────────────────────────────────────────

    @property
    def ssh_service(self) -> Optional[SSHService]:
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh: SSHService) -> None:
        """Hot-swap SSH 服务（设置页连接后调用）"""
        self._ssh = ssh
        # 重建 ToolEngine（依赖 SSH）
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

    # ── 信号链路 ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """连接核心信号链路"""
        # JobQueue.job_started → 实际派发到远程
        self._job_queue.job_started.connect(self._on_dispatch)

        # JobMonitor 完成/失败 → 回调处理
        self._job_monitor.job_completed.connect(self._on_completed)
        self._job_monitor.job_failed.connect(self._on_failed)

        # RetryManager 信号
        self._retry_manager.retry_exhausted.connect(
            lambda eid, err: logger.warning("任务重试用尽: %s — %s", eid, err)
        )

    def _on_dispatch(self, execution_id: str) -> None:
        """JobQueue 启动任务后的实际派发流程。

        1. 从执行上下文获取命令信息
        2. CommandBuilder.wrap() 生成包装脚本
        3. JobDispatcher.submit() 写脚本 + 启动 screen
        4. JobMonitor.add_job() 开始轮询
        """
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

            # 生成包装脚本
            wrapped = CommandBuilder.wrap(command, job_id, task_dir)

            # 写入远端并启动 screen
            JobDispatcher.submit(
                ssh_service=self._ssh,
                wrapped_script=wrapped,
                execution_id=execution_id,
                task_dir=task_dir,
            )

            # 添加到监控
            self._job_monitor.add_job(
                execution_id=execution_id,
                job_id=job_id,
                task_dir=task_dir,
                ssh_service=self._ssh,
            )

            # 启动监控线程（如果尚未启动）
            if not self._job_monitor.isRunning():
                self._job_monitor.start()

            logger.info("任务已派发: %s → screen %s", execution_id, job_id)

        except Exception as e:
            logger.exception("任务派发失败: %s", execution_id)
            self._on_failed(execution_id, str(e))

    def _on_completed(self, execution_id: str) -> None:
        """JobMonitor 报告任务完成"""
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

        # 释放 JobQueue 并发槽位
        self._job_queue.on_job_finished(execution_id)

        self.execution_completed.emit(execution_id)

    def _on_failed(self, execution_id: str, error: str) -> None:
        """JobMonitor 报告任务失败"""
        ctx = self._execution_ctx.pop(execution_id, None)

        if self._tool_engine:
            self._tool_engine.on_job_failed(execution_id, error)

        # 尝试自动重试
        self._retry_manager.on_task_failed(execution_id, error)

        # 释放 JobQueue 并发槽位
        self._job_queue.on_job_finished(execution_id)

        self.execution_failed.emit(execution_id, error)

    # ── 项目切换 ──────────────────────────────────────────────

    def _on_project_opened(self, project_id: str) -> None:
        """项目切换时重建 DataRegistry + ToolEngine"""
        logger.info("项目切换: %s, 重建 DataRegistry", project_id)
        self._rebuild_registry_and_engine()

    def _rebuild_registry_and_engine(self) -> None:
        """重建 DataRegistry 和 ToolEngine"""
        try:
            db = self._project_manager.db
            self._data_registry = DataRegistry(db)
            self._rebuild_engine()
        except Exception:
            logger.exception("重建 DataRegistry 失败")

    def _rebuild_engine(self) -> None:
        """重建 ToolEngine（在 SSH 或项目变化后调用）"""
        if self._data_registry is None:
            return

        self._tool_engine = ToolEngine(
            ssh_service=self._ssh or _NullSSH(),
            plugin_registry=self._plugin_registry,
            project_manager=self._project_manager,
            data_registry=self._data_registry,
            job_queue=self._job_queue,
        )

        # 转发 ToolEngine 信号
        self._tool_engine.execution_started.connect(self.execution_started.emit)

    # ── 执行上下文管理 ────────────────────────────────────────

    def register_execution_context(
        self,
        execution_id: str,
        command: str,
        descriptor: dict[str, Any],
        sample_id: str,
        output_dir: str,
        task_dir: str,
    ) -> None:
        """注册执行上下文（由 ToolEngine.execute 后调用，供 _on_dispatch 使用）"""
        self._execution_ctx[execution_id] = {
            "command": command,
            "descriptor": descriptor,
            "sample_id": sample_id,
            "output_dir": output_dir,
            "task_dir": task_dir,
        }

    def shutdown(self) -> None:
        """关闭服务总线，停止监控线程"""
        self._job_monitor.request_stop()
        if self._job_monitor.isRunning():
            self._job_monitor.wait(5000)
        self._project_manager.close()
        logger.info("ServiceLocator 已关闭")


class _NullSSH:
    """空 SSH 实现 — 在未连接 SSH 时使用，避免 NoneType 错误"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        raise RuntimeError("SSH 未连接")

    def upload(self, local_path: str, remote_path: str) -> None:
        raise RuntimeError("SSH 未连接")
