"""SSH 指数退避重连器

在独立 QThread 中执行重连尝试，使用指数退避策略 (2/4/8/16/32/60s)。
通过 pyqtSignal 通知重连状态变化。
"""
import logging
import time
from typing import Optional, Callable

import paramiko
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)

# 指数退避延迟序列 (秒)
BACKOFF_DELAYS = [2, 4, 8, 16, 32, 60]


class _ReconnectWorker(QObject):
    """在 QThread 中执行实际重连操作的 Worker"""

    # 内部信号
    attempt_made = pyqtSignal(int, int)  # (当前次数, 最大次数)
    succeeded = pyqtSignal(object)  # paramiko.SSHClient
    failed = pyqtSignal(str)  # 错误消息

    def __init__(
        self,
        connect_fn: Callable[[], paramiko.SSHClient],
        max_retries: int,
    ):
        super().__init__()
        self._connect_fn = connect_fn
        self._max_retries = max_retries
        self._cancelled = False

    def cancel(self) -> None:
        """请求取消重连"""
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        """执行指数退避重连循环"""
        for attempt in range(1, self._max_retries + 1):
            if self._cancelled:
                self.failed.emit("重连已取消")
                return

            self.attempt_made.emit(attempt, self._max_retries)
            delay = BACKOFF_DELAYS[min(attempt - 1, len(BACKOFF_DELAYS) - 1)]
            logger.info("SSH 重连尝试 %d/%d，等待 %ds...", attempt, self._max_retries, delay)

            # 等待退避时间（分段 sleep 以便及时响应取消）
            for _ in range(delay * 10):
                if self._cancelled:
                    self.failed.emit("重连已取消")
                    return
                time.sleep(0.1)

            try:
                client = self._connect_fn()
                transport = client.get_transport()
                if transport and transport.is_active():
                    logger.info("SSH 重连成功 (第 %d 次尝试)", attempt)
                    self.succeeded.emit(client)
                    return
                else:
                    logger.warning("SSH 连接已建立但 transport 不活跃")
            except Exception as e:
                logger.warning("SSH 重连尝试 %d 失败: %s", attempt, e)

        self.failed.emit(f"SSH 重连失败: 已达最大尝试次数 ({self._max_retries})")


class SSHReconnector(QObject):
    """SSH 指数退避重连器

    使用指数退避策略在独立线程中尝试恢复 SSH 连接。
    退避延迟序列: 2, 4, 8, 16, 32, 60 秒。

    Attributes:
        max_retries: 最大重试次数，默认 5
    """

    # 公开信号
    reconnected = pyqtSignal()  # 重连成功
    connection_lost = pyqtSignal()  # 连接丢失（开始重连前发出）
    retry_attempt = pyqtSignal(int, int)  # (当前次数, 最大次数)
    reconnect_failed = pyqtSignal(str)  # 重连最终失败，附带错误消息

    def __init__(
        self,
        connect_fn: Callable[[], paramiko.SSHClient],
        max_retries: int = 5,
        parent: Optional[QObject] = None,
    ):
        """
        Args:
            connect_fn: 可调用对象，调用后返回新的 paramiko.SSHClient 实例。
                        该函数应包含完整的连接逻辑（host/port/credentials）。
            max_retries: 最大重试次数，默认 5
            parent: 父 QObject
        """
        super().__init__(parent)
        self._connect_fn = connect_fn
        self.max_retries = max_retries
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ReconnectWorker] = None
        self._is_reconnecting = False

    @property
    def is_reconnecting(self) -> bool:
        """当前是否正在重连"""
        return self._is_reconnecting

    def start(self) -> None:
        """启动重连流程

        如果已经在重连中，则忽略本次调用。
        """
        if self._is_reconnecting:
            logger.debug("重连已在进行中，忽略重复请求")
            return

        self._is_reconnecting = True
        self.connection_lost.emit()
        logger.info("SSH 连接丢失，开始重连 (最大 %d 次)", self.max_retries)

        # 创建 worker 和 thread
        self._thread = QThread()
        self._worker = _ReconnectWorker(self._connect_fn, self.max_retries)
        self._worker.moveToThread(self._thread)

        # 连接信号
        self._thread.started.connect(self._worker.run)
        self._worker.attempt_made.connect(self._on_attempt)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)

        # 清理
        self._worker.succeeded.connect(self._cleanup_thread)
        self._worker.failed.connect(self._cleanup_thread)

        self._thread.start()

    def cancel(self) -> None:
        """取消当前重连"""
        if self._worker:
            self._worker.cancel()

    def _on_attempt(self, current: int, total: int) -> None:
        """转发重试尝试信号"""
        self.retry_attempt.emit(current, total)

    def _on_success(self, client: paramiko.SSHClient) -> None:
        """重连成功"""
        self._is_reconnecting = False
        logger.info("SSH 重连成功")
        self.reconnected.emit()

    def _on_failure(self, error: str) -> None:
        """重连失败"""
        self._is_reconnecting = False
        logger.error("SSH 重连失败: %s", error)
        self.reconnect_failed.emit(error)

    def _cleanup_thread(self) -> None:
        """清理 worker 线程"""
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = None
        self._worker = None
