"""任务队列 — 管理执行中的任务状态

任务提交后立即执行，不限制并发数。
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class QueuedJob:
    """队列中的任务"""
    execution_id: str
    command: str
    callback_on_start: Optional[Callable[[str], None]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class JobQueue(QObject):
    """任务队列 — 管理执行中的任务状态

    任务提交后立即执行，不限制并发数。

    Signals:
        job_started(str): 任务开始执行，参数为 execution_id
        queue_empty(): 所有任务均已完成
    """

    job_started = pyqtSignal(str)  # execution_id
    queue_empty = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._running: Dict[str, QueuedJob] = {}

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """提交任务，立即开始执行

        Args:
            execution_id: 任务唯一标识
            command: 要执行的命令
            callback_on_start: 任务开始执行时的回调
            metadata: 附加元数据

        Returns:
            始终返回 'started'
        """
        job = QueuedJob(
            execution_id=execution_id,
            command=command,
            callback_on_start=callback_on_start,
            metadata=metadata or {},
        )
        self._start_job(job)
        return "started"

    def on_job_finished(self, execution_id: str) -> None:
        """通知任务完成，从运行列表移除

        Args:
            execution_id: 已完成的任务标识
        """
        if execution_id in self._running:
            del self._running[execution_id]
            logger.info("任务 %s 完成 (运行数: %d)", execution_id, len(self._running))
        else:
            logger.debug("任务 %s 不在运行列表中（可能是恢复监控任务）", execution_id)

        if not self._running:
            logger.info("所有任务已完成")
            self.queue_empty.emit()

    def has_job(self, execution_id: str) -> bool:
        """Whether execution currently exists in queue running map."""
        return execution_id in self._running

    def get_status(self) -> Dict[str, int]:
        """获取队列状态

        Returns:
            包含 running, pending 的字典
        """
        return {
            "running": len(self._running),
            "pending": 0,
        }

    def _start_job(self, job: QueuedJob) -> None:
        """启动一个任务"""
        self._running[job.execution_id] = job
        logger.info("任务 %s 开始执行 (运行数: %d)", job.execution_id, len(self._running))

        if job.callback_on_start:
            try:
                job.callback_on_start(job.execution_id)
            except Exception as e:
                logger.error("任务 %s 启动回调失败: %s", job.execution_id, e)

        self.job_started.emit(job.execution_id)
