"""SSH 服务封装

提供远程命令执行、文件传输等功能。
集成 SSHReconnector 实现连接丢失时的自动重连。
"""

import logging
import threading
import time
import uuid
from threading import Condition, Event, RLock, Thread
from typing import Any, Callable, Optional, Tuple

import paramiko

from core.remote.ssh_reconnector import SSHReconnector

logger = logging.getLogger(__name__)


def _single_line_preview(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


class TerminalSession:
    """Interactive shell session backed by a Paramiko channel."""

    def __init__(self, *, session_id: str, channel: Any):
        self.session_id = session_id
        self._channel = channel
        self._lock = RLock()
        self._updates = Condition(self._lock)
        self._stop = Event()
        self._output = ""
        self._closed = False
        self._connected = True
        self._input_enabled = True
        self._message = ""
        self._created_at = time.time()
        self._closed_at: float | None = None
        self._version = 0
        self._reader = Thread(
            target=self._reader_loop,
            daemon=True,
            name=f"SSHTerminalReader-{session_id}",
        )
        self._reader.start()

    def snapshot(self, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            safe_cursor = max(0, min(int(cursor or 0), len(self._output)))
            return {
                "session_id": self.session_id,
                "cursor": len(self._output),
                "output": self._output[safe_cursor:],
                "connected": self._connected,
                "input_enabled": self._input_enabled,
                "closed": self._closed,
                "message": self._message,
                "created_at": self._created_at,
                "closed_at": self._closed_at,
            }

    def send(self, data: str) -> None:
        if not data:
            return
        with self._lock:
            if self._closed or not self._input_enabled:
                raise RuntimeError(self._message or "Terminal session is not writable")
            try:
                self._channel.send(data)
            except Exception as exc:
                self._mark_closed(
                    message=str(exc) or "Terminal session write failed", connected=False
                )
                raise

    def resize(self, *, cols: int, rows: int) -> None:
        with self._lock:
            if self._closed or not self._input_enabled:
                raise RuntimeError(self._message or "Terminal session is not writable")
            resize_pty = getattr(self._channel, "resize_pty", None)
            if not callable(resize_pty):
                raise RuntimeError("Terminal session does not support resizing")
            try:
                resize_pty(width=max(40, int(cols)), height=max(12, int(rows)))
            except Exception as exc:
                self._mark_closed(
                    message=str(exc) or "Terminal session resize failed",
                    connected=False,
                )
                raise

    def wait_for_update(
        self,
        *,
        cursor: int = 0,
        version: int = -1,
        timeout: float = 1.0,
    ) -> tuple[dict[str, Any], int]:
        with self._updates:
            safe_cursor = max(0, min(int(cursor or 0), len(self._output)))
            has_pending_output = safe_cursor < len(self._output)
            has_pending_state = version != self._version
            if not has_pending_output and not has_pending_state:
                self._updates.wait(timeout=max(0.0, float(timeout)))
            return self.snapshot(cursor=safe_cursor), self._version

    def close(
        self, *, message: str = "终端会话已结束", connected: bool = False
    ) -> None:
        with self._lock:
            if self._closed:
                if message and not self._message:
                    self._message = message
                self._connected = self._connected and connected
                self._input_enabled = self._input_enabled and connected
                return
            self._mark_closed(message=message, connected=connected)
        self._stop.set()
        try:
            self._channel.close()
        except Exception:
            logger.debug("Failed to close interactive terminal channel", exc_info=True)
        if self._reader.is_alive() and self._reader is not threading.current_thread():
            self._reader.join(timeout=0.5)

    def _append_output(self, text: str) -> None:
        if not text:
            return
        with self._updates:
            self._output += text
            self._touch_locked()

    def _mark_closed(self, *, message: str, connected: bool) -> None:
        self._closed = True
        self._connected = connected
        self._input_enabled = False
        self._message = message
        self._closed_at = time.time()
        self._touch_locked()

    def _touch_locked(self) -> None:
        self._version += 1
        self._updates.notify_all()

    def _reader_loop(self) -> None:
        try:
            while not self._stop.is_set():
                had_data = False
                while (
                    not self._stop.is_set()
                    and getattr(self._channel, "recv_ready", lambda: False)()
                ):
                    chunk = self._channel.recv(4096)
                    if not chunk:
                        break
                    self._append_output(chunk.decode("utf-8", errors="ignore"))
                    had_data = True
                while (
                    not self._stop.is_set()
                    and getattr(self._channel, "recv_stderr_ready", lambda: False)()
                ):
                    chunk = self._channel.recv_stderr(4096)
                    if not chunk:
                        break
                    self._append_output(chunk.decode("utf-8", errors="ignore"))
                    had_data = True
                if (
                    getattr(self._channel, "closed", False)
                    or getattr(self._channel, "exit_status_ready", lambda: False)()
                ):
                    if not had_data:
                        with self._lock:
                            if not self._closed:
                                self._mark_closed(
                                    message="终端会话已结束", connected=False
                                )
                        return
                time.sleep(0.05)
        except Exception as exc:
            logger.debug(
                "Interactive terminal reader stopped with error", exc_info=True
            )
            with self._lock:
                if not self._closed:
                    self._mark_closed(
                        message=str(exc) or "终端会话已结束", connected=False
                    )
        finally:
            self._stop.set()

class SSHService:
    """SSH 服务封装

    封装 paramiko.SSHClient，提供命令执行、文件传输等功能。
    集成 SSHReconnector，在连接丢失时自动触发重连。
    """

    def __init__(
        self,
        initial_client: Optional[paramiko.SSHClient] = None,
        connect_fn: Optional[Callable[[], paramiko.SSHClient]] = None,
        max_retries: int = 5,
    ):
        """
        Args:
            initial_client: 初始活跃的 SSHClient（可为 None）
            connect_fn: 重连函数，调用后返回新的 SSHClient。
                        若为 None，则不启用自动重连。
            max_retries: SSHReconnector 最大重试次数，默认 5
        """
        self._active_client: Optional[paramiko.SSHClient] = initial_client
        self._connect_fn = connect_fn
        self._io_lock = RLock()
        self._terminal_sessions: dict[str, TerminalSession] = {}

        self._reconnector: Optional[SSHReconnector] = None
        if connect_fn:
            self._reconnector = SSHReconnector(
                connect_fn=connect_fn,
                max_retries=max_retries,
                on_success=self._on_reconnected,
                on_failure=self._on_reconnect_failed,
                on_connection_lost=self._on_connection_lost,
            )

    @property
    def reconnector(self) -> Optional[SSHReconnector]:
        return self._reconnector

    @property
    def is_connected(self) -> bool:
        """检查 SSH 连接是否可用"""
        client = self._client()
        if not client:
            return False
        return self._check_transport(client)

    def _client(self) -> Optional[paramiko.SSHClient]:
        return self._active_client

    def _check_transport(self, client: paramiko.SSHClient) -> bool:
        """检查 SSH 连接是否仍然活跃"""
        try:
            transport = client.get_transport()
            if transport and transport.is_active():
                transport.send_ignore()
                return True
            return False
        except Exception:
            return False

    def _ensure_connection(self) -> paramiko.SSHClient:
        """确保 SSH 连接可用，连接丢失时触发重连"""
        client = self._client()
        if client and self._check_transport(client):
            return client

        # 连接不可用，触发重连
        if self._reconnector and not self._reconnector.is_reconnecting:
            logger.warning("SSH 连接不可用，触发自动重连")
            self._reconnector.start()

        raise RuntimeError("SSH 未连接")

    def _on_reconnected(self, client: paramiko.SSHClient) -> None:
        """重连成功回调，存储新客户端"""
        logger.info("SSH 连接已恢复")
        old_client = self._active_client
        self._active_client = client
        if old_client is not None and old_client is not client:
            try:
                old_client.close()
            except Exception:
                logger.debug(
                    "Failed to close old SSH client after reconnection", exc_info=True
                )

    def _on_connection_lost(self) -> None:
        """连接丢失回调"""
        logger.warning("SSH 连接已丢失")
        self.close_terminal_sessions(message="SSH 已断开，终端会话已结束")

    def _on_reconnect_failed(self, error: str) -> None:
        """重连失败回调"""
        logger.error("SSH 重连最终失败: %s", error)
        self.close_terminal_sessions(message="SSH 已断开，终端会话已结束")

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        """执行远程命令并同步返回结果。"""
        return self._execute_command(cmd, timeout)

    def sftp(self) -> paramiko.SFTPClient:
        """获取 SFTP 客户端"""
        with self._io_lock:
            client = self._ensure_connection()
            return client.open_sftp()

    def upload(self, local_path: str, remote_path: str) -> None:
        """上传本地文件到远端

        Args:
            local_path: 本地文件路径
            remote_path: 远端文件路径
        """
        sftp_client = self.sftp()
        try:
            sftp_client.put(local_path, remote_path)
        finally:
            sftp_client.close()

    def download(self, remote_path: str, local_path: str) -> None:
        """从远端下载文件到本地

        Args:
            remote_path: 远端文件路径
            local_path: 本地文件路径
        """
        sftp_client = self.sftp()
        try:
            sftp_client.get(remote_path, local_path)
        finally:
            sftp_client.close()

    def open_terminal(
        self,
        *,
        cols: int = 120,
        rows: int = 24,
        term: str = "xterm-256color",
    ) -> paramiko.Channel:
        """打开一个绑定当前 SSH 连接的交互式终端 channel。"""
        with self._io_lock:
            client = self._ensure_connection()
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH 未连接")
            channel = transport.open_session(timeout=10)
            channel.get_pty(
                term=term, width=max(40, int(cols)), height=max(12, int(rows))
            )
            channel.invoke_shell()
            channel.settimeout(0.0)
            return channel

    def close(self) -> None:
        """Close SSH client and all tracked terminal sessions."""
        self.close_terminal_sessions(message="终端会话已结束")
        client = self._active_client
        self._active_client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("Failed to close SSH client", exc_info=True)

    def open_terminal_session(
        self, *, cols: int = 120, rows: int = 28
    ) -> TerminalSession:
        with self._io_lock:
            client = self._ensure_connection()
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH 未连接")
            channel = transport.open_session(timeout=10)
            channel.get_pty(
                term="xterm-256color",
                width=max(40, int(cols)),
                height=max(12, int(rows)),
            )
            channel.invoke_shell()
            channel.settimeout(0.0)
        session = TerminalSession(
            session_id=f"term_{uuid.uuid4().hex}", channel=channel
        )
        self._terminal_sessions[session.session_id] = session
        return session

    def close_terminal_sessions(self, *, message: str, connected: bool = False) -> None:
        sessions = list(self._terminal_sessions.values())
        self._terminal_sessions.clear()
        for session in sessions:
            try:
                session.close(message=message, connected=connected)
            except Exception:
                logger.debug(
                    "Failed to close terminal session %s",
                    session.session_id,
                    exc_info=True,
                )

    def _execute_command(self, cmd: str, timeout: int) -> Tuple[int, str, str]:
        with self._io_lock:
            client = self._ensure_connection()
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            del stdin
            channel = stdout.channel
            deadline = time.monotonic() + max(float(timeout), 0.1)
            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []

            while True:
                made_progress = False
                while channel.recv_ready():
                    stdout_chunks.append(channel.recv(32768))
                    made_progress = True
                while channel.recv_stderr_ready():
                    stderr_chunks.append(channel.recv_stderr(32768))
                    made_progress = True
                if channel.exit_status_ready():
                    while channel.recv_ready():
                        stdout_chunks.append(channel.recv(32768))
                    while channel.recv_stderr_ready():
                        stderr_chunks.append(channel.recv_stderr(32768))
                    rc = channel.recv_exit_status()
                    break
                if time.monotonic() >= deadline:
                    try:
                        channel.close()
                    except Exception:
                        logger.debug(
                            "Failed to close timed-out SSH channel", exc_info=True
                        )
                    raise TimeoutError(
                        f"SSH command timed out after {timeout}s: {self._build_tag(cmd)}"
                    )
                if not made_progress:
                    time.sleep(0.05)

            out = b"".join(stdout_chunks).decode("utf-8", errors="ignore")
            err = b"".join(stderr_chunks).decode("utf-8", errors="ignore")
            return rc, out, err
