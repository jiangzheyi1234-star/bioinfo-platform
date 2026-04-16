"""SSH 服务封装 - 远程命令执行、文件传输、终端会话。"""

import logging
import re
import threading
import time
import uuid
from threading import RLock
from typing import Any, Callable, Optional, Tuple

import paramiko

from core.remote.ssh_reconnector import SSHReconnector

logger = logging.getLogger(__name__)


class TerminalSession:
    """交互式终端会话"""

    def __init__(self, session_id: str, channel: Any):
        self.session_id = session_id
        self._channel = channel
        self._lock = RLock()
        self._output = ""
        self._closed = False
        self._message = ""
        self._created_at = time.time()

        threading.Thread(target=self._reader_loop, daemon=True).start()

    def snapshot(self, cursor: int = 0) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "cursor": len(self._output),
                "output": self._output[max(0, cursor) :],
                "closed": self._closed,
                "message": self._message,
                "created_at": self._created_at,
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
        self, cursor: int = 0, timeout: float = 1.0
    ) -> Tuple[dict, int]:
        time.sleep(min(timeout, 0.5))
        return self.snapshot(cursor), 0

    def close(self, message: str = "终端会话已结束") -> None:
        with self._lock:
            self._closed = True
            self._message = message
        try:
            self._channel.close()
        except Exception:
            pass

    def _reader_loop(self) -> None:
        try:
            while not self._closed:
                if self._channel.recv_ready():
                    data = self._channel.recv(4096)
                    if data:
                        with self._lock:
                            self._output += data.decode("utf-8", errors="ignore")
                elif self._channel.closed or self._channel.exit_status_ready():
                    with self._lock:
                        self._closed = True
                        self._message = "终端会话已结束"
                    break
                time.sleep(0.05)
        except Exception:
            with self._lock:
                self._closed = True


class SSHService:
    """SSH 服务 - 命令执行、文件传输、终端"""

    def __init__(
        self,
        initial_client: Optional[paramiko.SSHClient] = None,
        connect_fn: Optional[Callable] = None,
        max_retries: int = 5,
    ):
        self._client = initial_client
        self._connect_fn = connect_fn
        self._lock = RLock()
        self._sessions: dict[str, TerminalSession] = {}

        self._reconnector = None
        if connect_fn:
            self._reconnector = SSHReconnector(
                connect_fn=connect_fn,
                max_retries=max_retries,
                on_success=self._on_reconnect,
                on_failure=self._on_failed,
            )

    @property
    def is_connected(self) -> bool:
        if not self._client:
            return False
        try:
            t = self._client.get_transport()
            return t and t.is_active()
        except Exception:
            return False

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        with self._lock:
            if not self._client:
                raise RuntimeError("SSH not connected")
            stdin, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            return stdout.channel.recv_exit_status(), out, err

    def upload(self, local: str, remote: str) -> None:
        with self._lock:
            sftp = self._client.open_sftp()
            sftp.put(local, remote)
            sftp.close()

    def download(self, remote: str, local: str) -> None:
        with self._lock:
            sftp = self._client.open_sftp()
            sftp.get(remote, local)
            sftp.close()

    def open_terminal_session(self, cols: int = 120, rows: int = 28) -> TerminalSession:
        with self._lock:
            t = self._client.get_transport()
            ch = t.open_session()
            ch.get_pty("xterm-256color", cols, rows)
            ch.invoke_shell()
            ch.settimeout(0)

        sid = f"term_{uuid.uuid4().hex}"
        session = TerminalSession(sid, ch)
        self._sessions[sid] = session
        return session

    def close(self) -> None:
        for s in list(self._sessions.values()):
            s.close()
        self._sessions.clear()
        if self._client:
            self._client.close()
            self._client = None

    def _on_reconnect(self, client: paramiko.SSHClient) -> None:
        logger.info("SSH reconnected")
        self._client = client

    def _on_failed(self, error: str) -> None:
        logger.error("SSH reconnect failed: %s", error)
        for s in list(self._sessions.values()):
            s.close(message="SSH disconnected")
        self._sessions.clear()
