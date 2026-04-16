"""SSH 指数退避重连器。

在独立线程中执行重连尝试，使用指数退避策略 (2/4/8/16/32/60s)。
"""

import logging
import threading
import time
from typing import Optional, Callable

import paramiko

logger = logging.getLogger(__name__)

BACKOFF_DELAYS = [2, 4, 8, 16, 32, 60]


class SSHReconnector:
    """SSH 指数退避重连器

    使用指数退避策略在独立线程中尝试恢复 SSH 连接。
    """

    def __init__(
        self,
        connect_fn: Callable[[], paramiko.SSHClient],
        max_retries: int = 5,
        on_success: Optional[Callable[[paramiko.SSHClient], None]] = None,
        on_failure: Optional[Callable[[str], None]] = None,
        on_connection_lost: Optional[Callable[[], None]] = None,
    ):
        self._connect_fn = connect_fn
        self._max_retries = max_retries
        self._on_success = on_success
        self._on_failure = on_failure
        self._on_connection_lost = on_connection_lost
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    def cancel(self) -> None:
        """取消正在进行的重连"""
        self._cancelled = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def trigger_reconnect(self) -> None:
        """启动重连线程"""
        if self._thread and self._thread.is_alive():
            return

        self._cancelled = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """执行指数退避重连循环"""
        for attempt in range(1, self._max_retries + 1):
            if self._cancelled:
                if self._on_failure:
                    self._on_failure("重连已取消")
                return

            delay = BACKOFF_DELAYS[min(attempt - 1, len(BACKOFF_DELAYS) - 1)]
            logger.info(
                "SSH 重连尝试 %d/%d，等待 %ds...", attempt, self._max_retries, delay
            )

            for _ in range(delay * 10):
                if self._cancelled:
                    if self._on_failure:
                        self._on_failure("重连已取消")
                    return
                time.sleep(0.1)

            try:
                client = self._connect_fn()
                transport = client.get_transport()
                if transport and transport.is_active():
                    logger.info("SSH 重连成功 (第 %d 次尝试)", attempt)
                    if self._on_success:
                        self._on_success(client)
                    return
                else:
                    logger.warning("SSH 连接已建立但 transport 不活跃")
            except Exception as e:
                logger.warning("SSH 重连尝试 %d 失败: %s", attempt, e)

        if self._on_failure:
            self._on_failure(f"SSH 重连失败: 已达最大尝试次数 ({self._max_retries})")

    def notify_connection_lost(self) -> None:
        """通知连接丢失"""
        if self._on_connection_lost:
            self._on_connection_lost()
        self.trigger_reconnect()
