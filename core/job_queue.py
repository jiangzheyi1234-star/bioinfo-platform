"""任务队列 — 控制并发执行的 screen 会话数量

通过 deque 管理待执行任务，限制同时运行的任务数量。
支持动态调整最大并发数。
"""
import logging
from collections import deque
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
    """任务队列 — 控制同时运行的 screen 会话数量

    当提交的任务数超过 max_concurrent 时，多余的任务会排队等待。
    当某个任务完成后，自动启动下一个排队中的任务。

    Signals:
        job_started(str): 任务开始执行，参数为 execution_id
        queue_updated(int): 排队中任务数量变化
        queue_empty(): 所有任务（包括运行中和排队中）均已完成
    """

    job_started = pyqtSignal(str)  # execution_id
    queue_updated = pyqtSignal(int)  # 排队中数量
    queue_empty = pyqtSignal()  # 队列和运行列表均为空

    def __init__(
        self,
        max_concurrent: int = 3,
        parent: Optional[QObject] = None,
    ):
        """
        Args:
            max_concurrent: 最大并发任务数，默认 3
            parent: 父 QObject
        """
        super().__init__(parent)
        self._max_concurrent = max_concurrent
        self._pending: deque[QueuedJob] = deque()
        self._running: Dict[str, QueuedJob] = {}

    @property
    def max_concurrent(self) -> int:
        """最大并发数"""
        return self._max_concurrent

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """提交任务到队列

        Args:
            execution_id: 任务唯一标识
            command: 要执行的命令
            callback_on_start: 任务实际开始执行时的回调
            metadata: 附加元数据

        Returns:
            'started' 如果任务立即开始执行，'queued' 如果任务进入排队
        """
        job = QueuedJob(
            execution_id=execution_id,
            command=command,
            callback_on_start=callback_on_start,
            metadata=metadata or {},
        )

        if len(self._running) < self._max_concurrent:
            self._start_job(job)
            return "started"
        else:
            self._pending.append(job)
            logger.info(
                "任务 %s 已排队 (排队数: %d, 运行数: %d/%d)",
                execution_id, len(self._pending),
                len(self._running), self._max_concurrent,
            )
            self.queue_updated.emit(len(self._pending))
            return "queued"

    def on_job_finished(self, execution_id: str) -> None:
        """通知任务完成，从运行列表移除并启动下一个排队任务

        Args:
            execution_id: 已完成的任务标识
        """
        if execution_id in self._running:
            del self._running[execution_id]
            logger.info(
                "任务 %s 完成 (运行数: %d/%d, 排队数: %d)",
                execution_id, len(self._running),
                self._max_concurrent, len(self._pending),
            )
        else:
            logger.warning("任务 %s 不在运行列表中", execution_id)

        # 尝试启动排队中的任务
        self._try_start_pending()

        # 检查是否全部完成
        if not self._running and not self._pending:
            logger.info("所有任务已完成")
            self.queue_empty.emit()

    def update_max_concurrent(self, n: int) -> None:
        """动态调整最大并发数

        如果新值大于当前值，会立即尝试启动排队中的任务。

        Args:
            n: 新的最大并发数，必须 >= 1
        """
        if n < 1:
            logger.warning("最大并发数不能小于 1，忽略设置")
            return

        old = self._max_concurrent
        self._max_concurrent = n
        logger.info("最大并发数: %d → %d", old, n)

        # 如果增大了并发数，尝试启动更多排队任务
        if n > old:
            self._try_start_pending()

    def get_status(self) -> Dict[str, int]:
        """获取队列状态

        Returns:
            包含 running, pending, max 的字典
        """
        return {
            "running": len(self._running),
            "pending": len(self._pending),
            "max": self._max_concurrent,
        }

    def _start_job(self, job: QueuedJob) -> None:
        """启动一个任务"""
        self._running[job.execution_id] = job
        logger.info(
            "任务 %s 开始执行 (运行数: %d/%d)",
            job.execution_id, len(self._running), self._max_concurrent,
        )

        # 调用启动回调
        if job.callback_on_start:
            try:
                job.callback_on_start(job.execution_id)
            except Exception as e:
                logger.error("任务 %s 启动回调失败: %s", job.execution_id, e)

        self.job_started.emit(job.execution_id)

    def _try_start_pending(self) -> None:
        """尝试启动排队中的任务，直到达到并发上限"""
        while self._pending and len(self._running) < self._max_concurrent:
            job = self._pending.popleft()
            self._start_job(job)
            self.queue_updated.emit(len(self._pending))
