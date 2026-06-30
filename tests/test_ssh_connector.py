from __future__ import annotations

import base64
import hashlib

import paramiko
import pytest

from core.remote.ssh_connector import run_diagnostics, ssh_connect, trust_ssh_host_key


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


def test_ssh_connect_reports_authentication_failure(monkeypatch, tmp_path) -> None:
    calls = {}
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")

    class FakeClient:
        def load_system_host_keys(self) -> None:
            calls["loaded_system_host_keys"] = True

        def load_host_keys(self, path: str) -> None:
            calls["loaded_host_keys"] = path

        def set_missing_host_key_policy(self, policy) -> None:
            calls["policy"] = policy

        def connect(self, **kwargs) -> None:
            calls["connect_kwargs"] = kwargs
            raise paramiko.AuthenticationException("bad credentials")

        def close(self) -> None:
            return None

    monkeypatch.setenv("H2OMETA_SSH_KNOWN_HOSTS", str(known_hosts))
    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    result = ssh_connect("192.0.2.10", 22, "tester", timeout=5)

    assert result.ok is False
    assert result.code == "SSH_AUTH_FAILED"
    assert result.phase == "auth"
    assert calls["loaded_system_host_keys"] is True
    assert calls["loaded_host_keys"] == str(known_hosts)
    assert isinstance(calls["policy"], paramiko.RejectPolicy)
    assert calls["connect_kwargs"]["disabled_algorithms"]["keys"] == [
        "ssh-rsa",
        "ssh-rsa-cert-v01@openssh.com",
    ]
    assert calls["connect_kwargs"]["disabled_algorithms"]["pubkeys"] == [
        "ssh-rsa",
        "ssh-rsa-cert-v01@openssh.com",
    ]


def test_ssh_connect_reports_untrusted_host_key(monkeypatch) -> None:
    class FakeClient:
        def load_system_host_keys(self) -> None:
            return None

        def load_host_keys(self, _path: str) -> None:
            return None

        def set_missing_host_key_policy(self, _policy) -> None:
            return None

        def connect(self, **_kwargs) -> None:
            raise paramiko.SSHException("Server '192.0.2.10' not found in known_hosts")

        def close(self) -> None:
            return None

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    result = ssh_connect("192.0.2.10", 22, "tester", timeout=5)

    assert result.ok is False
    assert result.code == "SSH_HOST_KEY_UNTRUSTED"
    assert result.phase == "host_key"


def test_ssh_connect_reports_host_key_mismatch(monkeypatch) -> None:
    expected_key = paramiko.RSAKey.generate(1024)
    presented_key = paramiko.RSAKey.generate(1024)

    class FakeClient:
        def load_system_host_keys(self) -> None:
            return None

        def load_host_keys(self, _path: str) -> None:
            return None

        def set_missing_host_key_policy(self, _policy) -> None:
            return None

        def connect(self, **_kwargs) -> None:
            raise paramiko.BadHostKeyException("192.0.2.10", presented_key, expected_key)

        def close(self) -> None:
            return None

    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.SSHClient", FakeClient)

    result = ssh_connect("192.0.2.10", 22, "tester", timeout=5)

    assert result.ok is False
    assert result.code == "SSH_HOST_KEY_UNTRUSTED"
    assert result.phase == "host_key"


def test_ssh_connect_does_not_mask_unexpected_ssh_adapter_errors(monkeypatch) -> None:
    class FakeClient:
        def load_system_host_keys(self) -> None:
            return None

        def load_host_keys(self, _path: str) -> None:
            return None

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
        def load_system_host_keys(self) -> None:
            return None

        def load_host_keys(self, _path: str) -> None:
            return None

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


def test_trust_ssh_host_key_writes_app_known_hosts(monkeypatch, tmp_path) -> None:
    known_hosts = tmp_path / "known_hosts"
    server_key = paramiko.RSAKey.generate(1024)
    calls = {}

    class FakeSock:
        def close(self) -> None:
            calls["socket_closed"] = True

    class FakeTransport:
        def __init__(self, _sock, *, disabled_algorithms=None) -> None:
            calls["disabled_algorithms"] = disabled_algorithms
            self.banner_timeout = None
            self.auth_timeout = None

        def start_client(self, *, timeout: int) -> None:
            calls["start_timeout"] = timeout

        def get_remote_server_key(self):
            return server_key

        def close(self) -> None:
            calls["transport_closed"] = True

    monkeypatch.setenv("H2OMETA_SSH_KNOWN_HOSTS", str(known_hosts))
    monkeypatch.setattr(
        "core.remote.ssh_connector.socket.create_connection",
        lambda *_args, **_kwargs: FakeSock(),
    )
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.Transport", FakeTransport)

    fingerprint = (
        "SHA256:"
        + base64.b64encode(hashlib.sha256(server_key.asbytes()).digest()).decode("ascii").rstrip("=")
    )
    result = trust_ssh_host_key(
        "192.0.2.10",
        2222,
        timeout=7,
        expected_fingerprint_sha256=fingerprint,
    )

    assert result.ok is True
    assert result.key_type == "ssh-rsa"
    assert result.fingerprint_sha256.startswith("SHA256:")
    assert result.known_hosts_path == str(known_hosts)
    assert calls["start_timeout"] == 7
    assert calls["transport_closed"] is True
    assert calls["disabled_algorithms"]["keys"] == [
        "ssh-rsa",
        "ssh-rsa-cert-v01@openssh.com",
    ]
    known_hosts_source = known_hosts.read_text(encoding="utf-8")
    assert "[192.0.2.10]:2222 ssh-rsa " in known_hosts_source


def test_trust_ssh_host_key_rejects_fingerprint_mismatch(monkeypatch, tmp_path) -> None:
    known_hosts = tmp_path / "known_hosts"
    server_key = paramiko.RSAKey.generate(1024)

    class FakeTransport:
        def __init__(self, _sock, *, disabled_algorithms=None) -> None:
            self.banner_timeout = None
            self.auth_timeout = None

        def start_client(self, *, timeout: int) -> None:
            return None

        def get_remote_server_key(self):
            return server_key

        def close(self) -> None:
            return None

    monkeypatch.setenv("H2OMETA_SSH_KNOWN_HOSTS", str(known_hosts))
    monkeypatch.setattr("core.remote.ssh_connector.socket.create_connection", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("core.remote.ssh_connector.paramiko.Transport", FakeTransport)

    result = trust_ssh_host_key(
        "192.0.2.10",
        2222,
        timeout=7,
        expected_fingerprint_sha256="SHA256:different",
    )

    assert result.ok is False
    assert result.code == "SSH_HOST_KEY_FINGERPRINT_MISMATCH"
    assert result.fingerprint_sha256.startswith("SHA256:")
    assert not known_hosts.exists()
