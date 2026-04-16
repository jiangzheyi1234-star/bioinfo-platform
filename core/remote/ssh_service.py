"""SSH 服务封装

提供远程命令执行、文件传输等功能。
集成 SSHReconnector 实现连接丢失时的自动重连。
"""

import logging
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from threading import Condition, Event, RLock, Thread
from typing import Any, Callable, Optional, Tuple

import paramiko

from core.remote.ssh_reconnector import SSHReconnector

logger = logging.getLogger(__name__)

_PRIO_USER_INTERACTIVE = 1
_PRIO_TASK_SUBMIT = 3
_PRIO_BACKGROUND_POLL = 9
_STOP = "__SSH_QUEUE_STOP__"


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


@dataclass
class _CommandRequest:
    request_id: str
    cmd: str
    timeout: int
    priority: int
    tag: str
    done: Event
    rc: int = -1
    out: str = ""
    err: str = ""
    exc: Exception | None = None


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
        self._queue: "queue.PriorityQueue[tuple[int, int, _CommandRequest | str]]" = (
            queue.PriorityQueue()
        )
        self._seq = 0
        self._queue_alive = True
        self._worker = Thread(
            target=self._queue_loop, daemon=True, name="SSHServiceQueueWorker"
        )
        self._worker.start()
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
        """执行远程命令

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            (exit_code, stdout, stderr) 元组
        """
        request_id = f"ssh_{int(time.time() * 1000)}_{self._next_seq()}"
        priority = self._classify_priority(cmd, async_mode=False)
        request = _CommandRequest(
            request_id=request_id,
            cmd=cmd,
            timeout=timeout,
            priority=priority,
            tag=self._build_tag(cmd),
            done=Event(),
        )
        enqueue_ts = time.time()
        self._queue.put((priority, self._next_seq(), request))
        request.done.wait()
        if request.exc is not None:
            raise request.exc
        duration_ms = int((time.time() - enqueue_ts) * 1000)
        logger.debug(
            "ssh_cmd_end request_id=%s tag=%s timeout=%s priority=%s duration_ms=%s rc=%s",
            request.request_id,
            request.tag,
            timeout,
            priority,
            duration_ms,
            request.rc,
        )
        return request.rc, request.out, request.err

    def run_async(self, cmd: str) -> None:
        """执行远程命令但不等待结果（用于启动后台任务）"""
        request = _CommandRequest(
            request_id=f"ssh_async_{int(time.time() * 1000)}_{self._next_seq()}",
            cmd=cmd,
            timeout=5,
            priority=self._classify_priority(cmd, async_mode=True),
            tag=self._build_tag(cmd),
            done=Event(),
        )
        self._queue.put((request.priority, self._next_seq(), request))

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
        """Stop queue worker gracefully."""
        if not self._queue_alive:
            return
        self.close_terminal_sessions(message="终端会话已结束")
        self._queue_alive = False
        self._queue.put((_PRIO_USER_INTERACTIVE, self._next_seq(), _STOP))
        self._worker.join(timeout=2.0)
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

    def run_interactive(
        self,
        cmd: str,
        *,
        timeout: int = 15,
        cols: int = 120,
        rows: int = 28,
        term: str = "xterm-256color",
    ) -> Tuple[int, str, str]:
        """Execute a command through an interactive invoke_shell channel.

        This is used for one-click runtime detection so the probe path matches
        the same interactive shell semantics as terminal-mediated remediation.
        """

        marker = uuid.uuid4().hex
        begin_marker = f"__OMX_BEGIN_{marker}__"
        rc_marker = f"__OMX_RC_{marker}__"
        end_marker = f"__OMX_END_{marker}__"
        payload = (
            "stty -echo >/dev/null 2>&1 || true\n"
            f"echo '{begin_marker}'\n"
            f"{cmd}\n"
            "__omx_status=$?\n"
            f"echo '{rc_marker}'\"$__omx_status\"\n"
            f"echo '{end_marker}' \"$__omx_status\"\n"
            "stty echo >/dev/null 2>&1 || true\n"
        )

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

            output_chunks: list[str] = []
            deadline = time.monotonic() + max(float(timeout), 0.1)
            init_deadline = time.monotonic() + 2.0
            try:
                while time.monotonic() < init_deadline:
                    if getattr(channel, "recv_ready", lambda: False)():
                        chunk = channel.recv(32768)
                        if chunk:
                            output_chunks.append(chunk.decode("utf-8", errors="ignore"))
                        else:
                            break
                    else:
                        if output_chunks:
                            break
                        time.sleep(0.05)
                init_output = "".join(output_chunks)
                if init_output:
                    logger.debug("SSH interactive shell init: %r", init_output[:200])
                channel.send(payload)
                while True:
                    made_progress = False
                    while getattr(channel, "recv_ready", lambda: False)():
                        chunk = channel.recv(32768)
                        if not chunk:
                            break
                        output_chunks.append(chunk.decode("utf-8", errors="ignore"))
                        made_progress = True
                    while getattr(channel, "recv_stderr_ready", lambda: False)():
                        chunk = channel.recv_stderr(32768)
                        if not chunk:
                            break
                        output_chunks.append(chunk.decode("utf-8", errors="ignore"))
                        made_progress = True
                    text = "".join(output_chunks)
                    if end_marker in text:
                        return self._parse_interactive_command_output(
                            text=text,
                            begin_marker=begin_marker,
                            rc_marker=rc_marker,
                            end_marker=end_marker,
                        )
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"SSH interactive command timed out after {timeout}s: {self._build_tag(cmd)}"
                        )
                    if not made_progress:
                        time.sleep(0.05)
            finally:
                try:
                    channel.close()
                except Exception:
                    logger.debug(
                        "Failed to close interactive SSH channel", exc_info=True
                    )

    def _parse_interactive_command_output(
        self,
        *,
        text: str,
        begin_marker: str,
        rc_marker: str,
        end_marker: str,
    ) -> Tuple[int, str, str]:
        begin_pattern = re.compile(rf"(?m)^[ \t]*{re.escape(begin_marker)}[ \t]*\r?$")
        rc_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(rc_marker)}[ \t]*(\d+)[ \t]*\r?$"
        )
        end_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(end_marker)}(?:[ \t]+(\d+))?[ \t]*\r?$"
        )

        end_match = None
        for match in end_pattern.finditer(text):
            end_match = match
        if end_match is None:
            raise RuntimeError("交互式 SSH 检测输出缺少完成标记")

        begin_match = None
        for match in begin_pattern.finditer(text, 0, end_match.start()):
            begin_match = match
        if begin_match is None or end_match.start() < begin_match.end():
            raise RuntimeError("交互式 SSH 检测输出缺少完成标记")

        end_line = end_match.group(0)
        content = text[begin_match.end() : end_match.start()].lstrip("\r\n")
        rc_match = None
        for match in rc_pattern.finditer(content):
            rc_match = match
        end_rc = end_match.group(1)
        if rc_match is not None:
            rc = int(rc_match.group(1))
            stdout = content[: rc_match.start()].rstrip("\r\n")
        elif end_rc:
            rc = int(end_rc)
            stdout = content.rstrip("\r\n")
        else:
            logger.warning(
                "SSH interactive parse failed: rc_marker=%s, end_line=%r, content_tail=%r",
                rc_marker,
                end_line[:200],
                content[-500:] if len(content) > 500 else content,
            )
            raise RuntimeError(
                "交互式 SSH 检测输出缺少退出码标记"
                f"；结束行: {_single_line_preview(end_line, 120)}"
                f"；输出片段: {_single_line_preview(content or text)}"
            )
        return rc, stdout, ""

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

    def _next_seq(self) -> int:
        with self._io_lock:
            self._seq += 1
            return self._seq

    def _queue_loop(self) -> None:
        while self._queue_alive:
            _prio, _seq, payload = self._queue.get()
            try:
                if payload == _STOP:
                    return
                request = payload
                assert isinstance(request, _CommandRequest)
                try:
                    logger.debug(
                        "ssh_cmd_begin request_id=%s tag=%s timeout=%s priority=%s",
                        request.request_id,
                        request.tag,
                        request.timeout,
                        request.priority,
                    )
                    rc, out, err = self._execute_command(request.cmd, request.timeout)
                    request.rc = rc
                    request.out = out
                    request.err = err
                except Exception as exc:
                    request.exc = exc
                    logger.exception(
                        "ssh_cmd_error request_id=%s tag=%s timeout=%s priority=%s",
                        request.request_id,
                        request.tag,
                        request.timeout,
                        request.priority,
                    )
                finally:
                    request.done.set()
            finally:
                self._queue.task_done()

    def _execute_command(self, cmd: str, timeout: int) -> Tuple[int, str, str]:
        # Serialize all command channel operations and keep sftp operations coherent.
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

    def _build_tag(self, cmd: str) -> str:
        text = (cmd or "").strip().replace("\n", " ")
        return text[:64] if text else "empty"

    def _classify_priority(self, cmd: str, async_mode: bool) -> int:
        lowered = str(cmd or "").lower()
        # 用户点击触发命令：目录浏览、权限校验、手动路径操作
        if any(
            k in lowered
            for k in (
                "find ",
                "ls ",
                "test -d",
                "test -w",
                "test -x",
                "touch ",
                "mkdir -p",
            )
        ):
            return _PRIO_USER_INTERACTIVE
        # 后台轮询命令：状态文件、心跳、screen 列表、tail 日志
        if any(
            k in lowered
            for k in (
                "status.txt",
                "heartbeat.txt",
                "exit_code.txt",
                "screen -ls",
                "tail -",
                "date +%s",
            )
        ):
            return _PRIO_BACKGROUND_POLL
        # 任务提交/默认命令
        if async_mode:
            return _PRIO_TASK_SUBMIT
        return _PRIO_TASK_SUBMIT
