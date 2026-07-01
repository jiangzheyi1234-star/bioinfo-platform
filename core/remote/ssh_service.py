"""SSH 服务 - 远程命令执行、文件传输、终端会话、自动重连。"""

import logging
import posixpath
import stat
import uuid
from threading import RLock
from typing import Any, Tuple

import paramiko

from core.remote.local_tunnel import LocalTunnel
from core.remote.ssh_reconnect import SSHReconnectError, SSHReconnector
from core.remote.terminal_session import TerminalSession

__all__ = [
    "LocalTunnel",
    "SSHReconnectError",
    "SSHReconnector",
    "SSHService",
    "TerminalSession",
]

logger = logging.getLogger(__name__)


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
        except (OSError, paramiko.SSHException):
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

    def list_directory(
        self,
        path: str = "",
        *,
        directories_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._client:
                raise RuntimeError("SSH not connected")
            sftp = self._client.open_sftp()
            try:
                remote_path = self._normalize_sftp_input_path(path)
                resolved_path = sftp.normalize(remote_path)
                attrs = sftp.listdir_attr(resolved_path)
            finally:
                sftp.close()

        items = []
        for attr in attrs:
            name = str(getattr(attr, "filename", "") or "")
            if not name or name in {".", ".."}:
                continue
            mode = int(getattr(attr, "st_mode", 0) or 0)
            is_dir = stat.S_ISDIR(mode)
            is_symlink = stat.S_ISLNK(mode)
            if directories_only and not is_dir:
                continue
            item_type = "directory" if is_dir else "symlink" if is_symlink else "file"
            items.append(
                {
                    "name": name,
                    "path": self._join_remote_path(resolved_path, name),
                    "type": item_type,
                    "isDirectory": is_dir,
                    "isSymlink": is_symlink,
                    "size": int(getattr(attr, "st_size", 0) or 0),
                    "mtime": int(getattr(attr, "st_mtime", 0) or 0),
                    "hidden": name.startswith("."),
                }
            )
        items.sort(key=lambda item: (not item["isDirectory"], str(item["name"]).lower()))
        bounded_limit = max(1, min(int(limit or 500), 5000))
        bounded_offset = max(0, int(offset or 0))
        next_offset = bounded_offset + bounded_limit
        total = len(items)
        normalized_resolved = str(resolved_path or "/")
        return {
            "path": normalized_resolved,
            "parentPath": self._parent_remote_path(normalized_resolved),
            "items": items[bounded_offset:next_offset],
            "offset": bounded_offset,
            "limit": bounded_limit,
            "total": total,
            "nextOffset": next_offset if next_offset < total else None,
            "truncated": next_offset < total,
        }

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

    def close_terminal_session(self, session_id: str, message: str = "终端会话已结束") -> None:
        with self._lock:
            session = self._sessions.pop(str(session_id or ""), None)
            if session is None:
                raise RuntimeError(f"unknown terminal session: {session_id}")
            session.close(message=message)

    @staticmethod
    def _normalize_sftp_input_path(path: str) -> str:
        raw = str(path or "").strip()
        if raw in {"", "~"}:
            return "."
        if raw.startswith("~/"):
            return f".{raw[1:]}"
        return raw

    @staticmethod
    def _join_remote_path(parent: str, name: str) -> str:
        if parent == "/":
            return f"/{name}"
        return posixpath.join(parent.rstrip("/"), name)

    @staticmethod
    def _parent_remote_path(path: str) -> str:
        normalized = str(path or "/").rstrip("/") or "/"
        if normalized == "/":
            return "/"
        return posixpath.dirname(normalized) or "/"

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

    def close_local_tunnel(self, name: str) -> None:
        with self._lock:
            tunnel = self._tunnels.pop(str(name or ""), None)
            if tunnel is not None:
                tunnel.close()

    def local_tunnel_snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "schemaVersion": "local-ssh-tunnel.v1",
                    "name": str(getattr(tunnel, "name", name) or name),
                    "localHost": str(getattr(tunnel, "local_host", "") or ""),
                    "localPort": self._coerce_tunnel_port(
                        getattr(tunnel, "local_port", 0)
                    ),
                    "remoteHost": str(getattr(tunnel, "remote_host", "") or ""),
                    "remotePort": self._coerce_tunnel_port(
                        getattr(tunnel, "remote_port", 0)
                    ),
                    "active": bool(getattr(tunnel, "is_active", False)),
                }
                for name, tunnel in sorted(self._tunnels.items())
            ]

    @staticmethod
    def _coerce_tunnel_port(value: Any) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return 0
        return port if 0 < port <= 65535 else 0

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
