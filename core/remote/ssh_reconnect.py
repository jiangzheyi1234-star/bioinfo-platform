"""SSH reconnect helpers."""

from __future__ import annotations

import logging
import threading
import time

import paramiko

logger = logging.getLogger(__name__)

BACKOFF_DELAYS = [2, 4, 8, 16, 32, 60]


class SSHReconnectError(RuntimeError):
    pass


class SSHReconnector:
    """SSH 指数退避重连器"""

    def __init__(self, connect_fn, max_retries=5, on_success=None, on_failure=None):
        self._connect_fn = connect_fn
        self._max_retries = max_retries
        self._on_success = on_success
        self._on_failure = on_failure
        self._cancelled = False

    def start(self):
        self._cancelled = False
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancelled = True

    def _run(self):
        for attempt in range(1, self._max_retries + 1):
            if self._cancelled:
                return
            delay = BACKOFF_DELAYS[min(attempt - 1, len(BACKOFF_DELAYS) - 1)]
            time.sleep(delay)
            try:
                client = self._connect_fn()
                if client.get_transport() and client.get_transport().is_active():
                    if self._on_success:
                        self._on_success(client)
                    return
            except (OSError, EOFError, paramiko.SSHException, SSHReconnectError) as e:
                logger.warning("SSH 重连尝试 %d 失败: %s", attempt, e)
        if self._on_failure:
            self._on_failure("SSH 重连失败")
