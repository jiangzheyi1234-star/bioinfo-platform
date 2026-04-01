"""Minimal Paramiko stub for Codex Windows test runs.

This module is injected ahead of site-packages via ``scripts/codex_pytest.ps1``.
It only implements the small surface used by the unit tests in this repository.
"""

from __future__ import annotations

from typing import Any


class SSHException(Exception):
    pass


class AuthenticationException(SSHException):
    pass


class BadHostKeyException(SSHException):
    pass


class AutoAddPolicy:
    pass


class Transport:
    def __init__(self, _addr: Any):
        self.remote_version = "stub-transport"
        self._active = False

    def connect(self, *args: Any, **kwargs: Any) -> None:
        self._active = True

    def is_active(self) -> bool:
        return self._active

    def set_keepalive(self, _interval: int) -> None:
        return None

    def send_ignore(self) -> None:
        return None

    def close(self) -> None:
        self._active = False


class SFTPClient:
    def put(self, _local_path: str, _remote_path: str) -> None:
        return None

    def get(self, _remote_path: str, _local_path: str) -> None:
        return None

    def close(self) -> None:
        return None


class SSHClient:
    def __init__(self) -> None:
        self._policy = None
        self._transport = Transport(("stub", 22))

    def set_missing_host_key_policy(self, policy: Any) -> None:
        self._policy = policy

    def connect(self, *args: Any, **kwargs: Any) -> None:
        self._transport.connect()

    def get_transport(self) -> Transport:
        return self._transport

    def exec_command(self, cmd: str, timeout: int = 10):
        raise NotImplementedError(f"Stub SSHClient.exec_command not implemented for {cmd!r} (timeout={timeout})")

    def open_sftp(self) -> SFTPClient:
        return SFTPClient()

    def close(self) -> None:
        self._transport.close()
