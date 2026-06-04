from __future__ import annotations

import logging
import select
import socketserver
import threading
from typing import Any, Optional

import paramiko


logger = logging.getLogger(__name__)


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
                except (OSError, EOFError, paramiko.SSHException):
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
                    except (OSError, EOFError, paramiko.SSHException):
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
