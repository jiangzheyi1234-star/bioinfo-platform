from __future__ import annotations

import threading
import time
from threading import Condition, RLock
from typing import Any, Tuple

import paramiko


class TerminalSession:
    """交互式终端会话"""

    def __init__(self, session_id: str, channel: Any):
        self.session_id = session_id
        self._channel = channel
        self._lock = RLock()
        self._updated = Condition(self._lock)
        self._version = 0
        self._output = ""
        self._closed = False
        self._message = ""
        self._created_at = time.time()
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def snapshot(self, cursor: int = 0) -> dict:
        with self._lock:
            connected = not self._closed
            return {
                "session_id": self.session_id,
                "cursor": len(self._output),
                "output": self._output[max(0, cursor) :],
                "connected": connected,
                "input_enabled": connected,
                "closed": self._closed,
                "message": self._message,
                "created_at": self._created_at,
                "closed_at": time.time() if self._closed else None,
            }

    def send(self, data: str) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("session closed")
            self._channel.send(data)

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("session closed")
            self._channel.resize_pty(cols, rows)

    def wait_for_update(
        self, cursor: int = 0, version: int = -1, timeout: float = 1.0
    ) -> Tuple[dict, int]:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._updated:
            while (
                self._version == version
                and len(self._output) <= max(0, cursor)
                and not self._closed
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._updated.wait(remaining)
            return self.snapshot(cursor), self._version

    def close(self, message: str = "终端会话已结束") -> None:
        with self._updated:
            self._closed = True
            self._message = message
            self._version += 1
            self._updated.notify_all()
        self._channel.close()

    def _reader_loop(self) -> None:
        try:
            while not self._closed:
                if self._channel.recv_ready():
                    data = self._channel.recv(4096)
                    if data:
                        with self._updated:
                            self._output += data.decode("utf-8", errors="ignore")
                            self._version += 1
                            self._updated.notify_all()
                elif self._channel.closed or self._channel.exit_status_ready():
                    with self._updated:
                        self._closed = True
                        self._message = "终端会话已结束"
                        self._version += 1
                        self._updated.notify_all()
                    break
                time.sleep(0.05)
        except (OSError, EOFError, paramiko.SSHException):
            with self._updated:
                self._closed = True
                self._version += 1
                self._updated.notify_all()
