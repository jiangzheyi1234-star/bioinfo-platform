"""SSH 服务 - 远程命令执行、文件传输、终端会话、自动重连。"""

import logging
import select
import socketserver
import threading
import time
import uuid
from threading import Condition, RLock
from typing import Any, Callable, Optional, Tuple

import paramiko

logger = logging.getLogger(__name__)

BACKOFF_DELAYS = [2, 4, 8, 16, 32, 60]


class LocalTunnel:
    def __init__(
        self,
        *,
        name: str,
        transport: Any,
        remote_host: str,
        remote_port: int,
        local_host: str = "127.0.0.1",
        local_port: int = 0,
    ) -> None:
        self.name = name
        self.local_host = local_host
        self.remote_host = remote_host
        self.remote_port = remote_port
        self._transport = transport
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._requested_port = local_port

    @property
    def local_port(self) -> int:
        if self._server is None:
            return 0
        return int(self._server.server_address[1])

    @property
    def is_active(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_active:
            return

        remote_host = self.remote_host
        remote_port = self.remote_port
        transport = self._transport

        class _ForwardHandler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                try:
                    channel = transport.open_channel(
                        "direct-tcpip",
                        (remote_host, remote_port),
                        self.request.getpeername(),
                    )
                except Exception:
                    logger.exception("Failed to open direct-tcpip channel")
                    return
                if channel is None:
                    return
                try:
                    while True:
                        readable, _, _ = select.select([self.request, channel], [], [], 1.0)
                        if self.request in readable:
                            data = self.request.recv(4096)
                            if not data:
                                break
                            channel.sendall(data)
                        if channel in readable:
                            data = channel.recv(4096)
                            if not data:
                                break
                            self.request.sendall(data)
                finally:
                    try:
                        channel.close()
                    except Exception:
                        pass

        class _ForwardServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = _ForwardServer((self.local_host, self._requested_port), _ForwardHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None


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
        except Exception:
            with self._updated:
                self._closed = True
                self._version += 1
                self._updated.notify_all()


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
            except Exception as e:
                logger.warning("SSH 重连尝试 %d 失败: %s", attempt, e)
        if self._on_failure:
            self._on_failure("SSH 重连失败")


class SSHService:
    """SSH 服务 - 命令执行、文件传输、终端"""

    def __init__(self, initial_client=None, connect_fn=None, max_retries=5):
        self._client = initial_client
        self._connect_fn = connect_fn
        self._lock = RLock()
        self._sessions = {}
        self._tunnels: dict[str, LocalTunnel] = {}
        self._reconnector = None
        self._reconnecting = False
        if connect_fn:
            self._reconnector = SSHReconnector(
                connect_fn, max_retries, self._on_reconnect, self._on_failed
            )

    @property
    def is_connected(self) -> bool:
        if not self._client:
            return False
        try:
            t = self._client.get_transport()
            active = bool(t and t.is_active())
            if not active:
                self._start_reconnect()
            return active
        except Exception:
            self._start_reconnect()
            return False

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        with self._lock:
            if not self._client:
                raise RuntimeError("SSH not connected")
            stdin, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
            return (
                stdout.channel.recv_exit_status(),
                stdout.read().decode("utf-8", errors="ignore"),
                stderr.read().decode("utf-8", errors="ignore"),
            )

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

    def open_terminal_session(self, cols=120, rows=28) -> TerminalSession:
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

    def ensure_local_tunnel(
        self,
        name: str,
        *,
        remote_host: str,
        remote_port: int,
        local_host: str = "127.0.0.1",
        local_port: int = 0,
    ) -> LocalTunnel:
        with self._lock:
            if not self._client:
                raise RuntimeError("SSH not connected")
            existing = self._tunnels.get(name)
            if existing and existing.is_active:
                if existing.remote_host == remote_host and existing.remote_port == remote_port:
                    return existing
                existing.close()
                self._tunnels.pop(name, None)
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH transport is not active")
            tunnel = LocalTunnel(
                name=name,
                transport=transport,
                remote_host=remote_host,
                remote_port=remote_port,
                local_host=local_host,
                local_port=local_port,
            )
            tunnel.start()
            self._tunnels[name] = tunnel
            return tunnel

    def close(self) -> None:
        if self._reconnector:
            self._reconnector.cancel()
        self._close_tunnels()
        for s in list(self._sessions.values()):
            s.close()
        self._sessions.clear()
        if self._client:
            self._client.close()
            self._client = None

    def _close_tunnels(self) -> None:
        for tunnel in list(self._tunnels.values()):
            tunnel.close()
        self._tunnels.clear()

    def _start_reconnect(self) -> None:
        if not self._reconnector or self._reconnecting:
            return
        self._reconnecting = True
        self._reconnector.start()

    def _on_reconnect(self, client):
        logger.info("SSH reconnected")
        self._reconnecting = False
        self._close_tunnels()
        self._client = client

    def _on_failed(self, error):
        self._reconnecting = False
        logger.error("SSH reconnect failed: %s", error)
        self._close_tunnels()
        for s in list(self._sessions.values()):
            s.close(message="SSH disconnected")
        self._sessions.clear()
