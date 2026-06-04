from __future__ import annotations

import paramiko
import pytest

from core.remote.ssh_connector import run_diagnostics, ssh_connect


def test_ssh_connect_reports_tcp_connection_refused(monkeypatch) -> None:
    def refused_connection(*_args, **_kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", refused_connection)

    result = ssh_connect("192.0.2.10", 22, "tester", timeout=5)

    assert result.ok is False
    assert result.code == "SSH_TCP_REFUSED"
    assert result.phase == "tcp_connect"


def test_ssh_connect_does_not_mask_unexpected_tcp_adapter_errors(monkeypatch) -> None:
    def crashed_connection(*_args, **_kwargs):
        raise RuntimeError("tcp adapter crashed")

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", crashed_connection)

    with pytest.raises(RuntimeError, match="tcp adapter crashed"):
        ssh_connect("192.0.2.10", 22, "tester", timeout=5)


def test_ssh_connect_reports_authentication_failure(monkeypatch) -> None:
    class FakeClient:
        def set_missing_host_key_policy(self, _policy) -> None:
            return None

        def connect(self, **_kwargs) -> None:
            raise paramiko.AuthenticationException("bad credentials")

        def close(self) -> None:
            return None

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    result = ssh_connect("192.0.2.10", 22, "tester", timeout=5)

    assert result.ok is False
    assert result.code == "SSH_AUTH_FAILED"
    assert result.phase == "auth"


def test_ssh_connect_does_not_mask_unexpected_ssh_adapter_errors(monkeypatch) -> None:
    class FakeClient:
        def set_missing_host_key_policy(self, _policy) -> None:
            return None

        def connect(self, **_kwargs) -> None:
            raise RuntimeError("ssh adapter crashed")

        def close(self) -> None:
            return None

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    with pytest.raises(RuntimeError, match="ssh adapter crashed"):
        ssh_connect("192.0.2.10", 22, "tester", timeout=5)


def test_ssh_connect_does_not_swallow_keepalive_errors(monkeypatch) -> None:
    class BrokenTransport:
        def set_keepalive(self, _seconds: int) -> None:
            raise RuntimeError("keepalive adapter crashed")

    class FakeClient:
        def set_missing_host_key_policy(self, _policy) -> None:
            return None

        def connect(self, **_kwargs) -> None:
            return None

        def get_transport(self) -> BrokenTransport:
            return BrokenTransport()

        def close(self) -> None:
            return None

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    with pytest.raises(RuntimeError, match="keepalive adapter crashed"):
        ssh_connect("192.0.2.10", 22, "tester", timeout=5)


def test_run_diagnostics_reports_dns_failure(monkeypatch) -> None:
    def fail_dns(*_args, **_kwargs):
        raise OSError("host not found")

    monkeypatch.setattr("core.remote.ssh_connector.socket.getaddrinfo", fail_dns)

    steps = run_diagnostics("bad.example", 22, "tester")

    assert steps == [{"name": "DNS/IP", "status": "fail", "message": "host not found"}]


def test_run_diagnostics_does_not_mask_unexpected_dns_adapter_errors(monkeypatch) -> None:
    def crash_dns(*_args, **_kwargs):
        raise RuntimeError("dns adapter crashed")

    monkeypatch.setattr("core.remote.ssh_connector.socket.getaddrinfo", crash_dns)

    with pytest.raises(RuntimeError, match="dns adapter crashed"):
        run_diagnostics("bad.example", 22, "tester")


def test_run_diagnostics_does_not_mask_unexpected_tcp_adapter_errors(monkeypatch) -> None:
    def crash_tcp(*_args, **_kwargs):
        raise RuntimeError("tcp adapter crashed")

    monkeypatch.setattr("core.remote.ssh_connector.socket.getaddrinfo", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", crash_tcp)

    with pytest.raises(RuntimeError, match="tcp adapter crashed"):
        run_diagnostics("192.0.2.10", 22, "tester")
