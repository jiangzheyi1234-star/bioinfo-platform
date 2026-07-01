from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from core.remote.ssh_service import LocalTunnel, SSHReconnector, SSHService, TerminalSession
from core.remote.terminal_session import TERMINAL_SESSION_SCROLLBACK_CHARS


def test_terminal_session_logic_lives_outside_ssh_service() -> None:
    service_source = Path("core/remote/ssh_service.py").read_text(encoding="utf-8")
    terminal_path = Path("core/remote/terminal_session.py")

    assert terminal_path.exists()
    terminal_source = terminal_path.read_text(encoding="utf-8")
    assert "from core.remote.terminal_session import TerminalSession" in service_source
    assert "class TerminalSession:" not in service_source
    assert "class TerminalSession:" in terminal_source
    assert "def _reader_loop(" in terminal_source
    assert "except Exception" not in terminal_source


def test_local_tunnel_logic_lives_outside_ssh_service() -> None:
    service_source = Path("core/remote/ssh_service.py").read_text(encoding="utf-8")
    tunnel_path = Path("core/remote/local_tunnel.py")

    assert tunnel_path.exists()
    tunnel_source = tunnel_path.read_text(encoding="utf-8")
    assert "from core.remote.local_tunnel import LocalTunnel" in service_source
    assert "class LocalTunnel:" not in service_source
    assert "socketserver.ThreadingTCPServer" not in service_source
    assert "select.select(" not in service_source
    assert "class LocalTunnel:" in tunnel_source
    assert "socketserver.ThreadingTCPServer" in tunnel_source
    assert "select.select(" in tunnel_source


def test_ssh_reconnector_logic_lives_outside_ssh_service() -> None:
    service_source = Path("core/remote/ssh_service.py").read_text(encoding="utf-8")
    reconnect_path = Path("core/remote/ssh_reconnect.py")

    assert reconnect_path.exists()
    reconnect_source = reconnect_path.read_text(encoding="utf-8")
    assert "from core.remote.ssh_reconnect import SSHReconnectError, SSHReconnector" in service_source
    assert "class SSHReconnector:" not in service_source
    assert "class SSHReconnectError" not in service_source
    assert "BACKOFF_DELAYS =" not in service_source
    assert "class SSHReconnector:" in reconnect_source
    assert "class SSHReconnectError" in reconnect_source
    assert "BACKOFF_DELAYS =" in reconnect_source


def test_local_tunnel_forwarder_uses_explicit_transport_error_boundaries() -> None:
    local_tunnel_source = Path("core/remote/local_tunnel.py").read_text(encoding="utf-8")

    assert "except Exception" not in local_tunnel_source
    assert local_tunnel_source.count("except (OSError, EOFError, paramiko.SSHException)") == 2


class DummyChannel:
    def __init__(self) -> None:
        self.closed = False
        self._exit_ready = False

    def close(self) -> None:
        self.closed = True

    def recv_ready(self) -> bool:
        return False

    def recv(self, _size: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return self._exit_ready


class DelayedOutputChannel(DummyChannel):
    def __init__(self) -> None:
        super().__init__()
        self._data = b""
        self._lock = threading.Lock()

    def push(self, data: bytes) -> None:
        with self._lock:
            self._data += data

    def recv_ready(self) -> bool:
        with self._lock:
            return bool(self._data)

    def recv(self, size: int) -> bytes:
        with self._lock:
            data = self._data[:size]
            self._data = self._data[size:]
            return data


def test_terminal_session_snapshot_marks_live_session_as_connected() -> None:
    session = TerminalSession("term_test", DummyChannel())
    snapshot = session.snapshot()
    session.close()

    assert snapshot["session_id"] == "term_test"
    assert snapshot["connected"] is True
    assert snapshot["input_enabled"] is True
    assert snapshot["closed"] is False
    assert snapshot["closed_at"] is None


def test_terminal_session_scrollback_caps_output_with_absolute_cursor(monkeypatch) -> None:
    class IdleThread:
        def __init__(self, **_kwargs) -> None:
            return None

        def start(self) -> None:
            return None

    monkeypatch.setattr("core.remote.terminal_session.threading.Thread", IdleThread)
    session = TerminalSession("term_test_scrollback", DummyChannel())
    session._append_output("a" * (TERMINAL_SESSION_SCROLLBACK_CHARS + 10))

    fresh = session.snapshot(cursor=10)
    stale = session.snapshot(cursor=0)
    started = time.monotonic()
    waited, _version = session.wait_for_update(cursor=0, version=session._version, timeout=1.0)
    elapsed = time.monotonic() - started

    assert fresh["cursor"] == TERMINAL_SESSION_SCROLLBACK_CHARS + 10
    assert fresh["base_cursor"] == 10
    assert fresh["truncated"] is False
    assert len(fresh["output"]) == TERMINAL_SESSION_SCROLLBACK_CHARS
    assert stale["truncated"] is True
    assert stale["output"] == fresh["output"]
    assert stale["scrollback_limit"] == TERMINAL_SESSION_SCROLLBACK_CHARS
    assert waited["truncated"] is True
    assert elapsed < 0.25


def test_terminal_session_snapshot_marks_closed_session_as_unavailable() -> None:
    session = TerminalSession("term_test_closed", DummyChannel())
    session.close(message="SSH disconnected")
    snapshot = session.snapshot()

    assert snapshot["connected"] is False
    assert snapshot["input_enabled"] is False
    assert snapshot["closed"] is True
    assert snapshot["message"] == "SSH disconnected"
    assert snapshot["closed_at"] is not None


def test_terminal_session_close_does_not_swallow_channel_close_errors() -> None:
    class BrokenCloseChannel(DummyChannel):
        def close(self) -> None:
            raise RuntimeError("channel close adapter crashed")

    session = TerminalSession("term_test_close_error", BrokenCloseChannel())

    with pytest.raises(RuntimeError, match="channel close adapter crashed"):
        session.close()
    assert session.snapshot()["closed"] is True


def test_terminal_session_reader_marks_channel_io_errors_closed(monkeypatch) -> None:
    class IdleThread:
        def __init__(self, **_kwargs) -> None:
            return None

        def start(self) -> None:
            return None

    class BrokenReadChannel(DummyChannel):
        def recv_ready(self) -> bool:
            raise OSError("channel read failed")

    monkeypatch.setattr("core.remote.terminal_session.threading.Thread", IdleThread)
    session = TerminalSession("term_test_reader_io_error", BrokenReadChannel())

    session._reader_loop()

    assert session.snapshot()["closed"] is True


def test_terminal_session_reader_does_not_mask_unexpected_channel_errors(monkeypatch) -> None:
    class IdleThread:
        def __init__(self, **_kwargs) -> None:
            return None

        def start(self) -> None:
            return None

    class BrokenReadChannel(DummyChannel):
        def recv_ready(self) -> bool:
            raise RuntimeError("channel adapter crashed")

    monkeypatch.setattr("core.remote.terminal_session.threading.Thread", IdleThread)
    session = TerminalSession("term_test_reader_adapter_error", BrokenReadChannel())

    with pytest.raises(RuntimeError, match="channel adapter crashed"):
        session._reader_loop()
    assert session.snapshot()["closed"] is False


def test_wait_for_update_returns_promptly_when_output_arrives() -> None:
    channel = DelayedOutputChannel()
    session = TerminalSession("term_test_update", channel)
    _initial_snapshot, initial_version = session.wait_for_update(cursor=0, timeout=0.0)
    timer = threading.Timer(0.05, lambda: channel.push(b"hello"))
    timer.start()

    started = time.monotonic()
    snapshot, _version = session.wait_for_update(cursor=0, version=initial_version, timeout=1.0)
    elapsed = time.monotonic() - started
    session.close()
    timer.cancel()

    assert snapshot["output"] == "hello"
    assert elapsed < 0.25


def test_ssh_service_close_terminal_session_removes_owned_session(monkeypatch) -> None:
    class FakeChannel(DummyChannel):
        def get_pty(self, *_args) -> None:
            return None

        def invoke_shell(self) -> None:
            return None

        def settimeout(self, _timeout: int) -> None:
            return None

    class FakeTransport:
        def __init__(self) -> None:
            self.channel = FakeChannel()

        def is_active(self) -> bool:
            return True

        def open_session(self):
            return self.channel

    class FakeClient:
        def __init__(self) -> None:
            self.transport = FakeTransport()

        def get_transport(self):
            return self.transport

    class IdleThread:
        def __init__(self, **_kwargs) -> None:
            return None

        def start(self) -> None:
            return None

    monkeypatch.setattr("core.remote.terminal_session.threading.Thread", IdleThread)
    service = SSHService(initial_client=FakeClient())
    session = service.open_terminal_session(cols=120, rows=28)

    assert session.session_id in service._sessions

    service.close_terminal_session(session.session_id)

    assert session.session_id not in service._sessions
    assert service._client.transport.channel.closed is True


def test_named_tunnel_is_recreated_when_remote_port_changes(monkeypatch) -> None:
    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def get_transport(self):
            return FakeTransport()

    starts: list[int] = []
    closes: list[int] = []

    def fake_start(self: LocalTunnel) -> None:
        starts.append(self.remote_port)
        self._thread = object()
        self._server = object()

    def fake_close(self: LocalTunnel) -> None:
        closes.append(self.remote_port)
        self._thread = None
        self._server = None

    monkeypatch.setattr(LocalTunnel, "start", fake_start)
    monkeypatch.setattr(LocalTunnel, "close", fake_close)
    monkeypatch.setattr(LocalTunnel, "is_active", property(lambda self: self._server is not None))

    service = SSHService(initial_client=FakeClient())
    first = service.ensure_local_tunnel("runner-test", remote_host="127.0.0.1", remote_port=39967)
    second = service.ensure_local_tunnel("runner-test", remote_host="127.0.0.1", remote_port=43549)

    assert first is not second
    assert starts == [39967, 43549]
    assert closes == [39967]


def test_close_local_tunnel_closes_named_tunnel(monkeypatch) -> None:
    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def get_transport(self):
            return FakeTransport()

    closes: list[str] = []

    def fake_start(self: LocalTunnel) -> None:
        self._thread = object()
        self._server = object()

    def fake_close(self: LocalTunnel) -> None:
        closes.append(self.name)
        self._thread = None
        self._server = None

    monkeypatch.setattr(LocalTunnel, "start", fake_start)
    monkeypatch.setattr(LocalTunnel, "close", fake_close)
    monkeypatch.setattr(LocalTunnel, "is_active", property(lambda self: self._server is not None))

    service = SSHService(initial_client=FakeClient())
    service.ensure_local_tunnel("runner-test", remote_host="127.0.0.1", remote_port=39967)
    service.close_local_tunnel("runner-test")
    service.ensure_local_tunnel("runner-test", remote_host="127.0.0.1", remote_port=39967)

    assert closes == ["runner-test"]


def test_local_tunnel_snapshots_expose_only_public_endpoint_state(monkeypatch) -> None:
    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def get_transport(self):
            return FakeTransport()

    def fake_start(self: LocalTunnel) -> None:
        self._thread = object()
        self._server = SimpleNamespace(server_address=(self.local_host, 18001))

    monkeypatch.setattr(LocalTunnel, "start", fake_start)
    monkeypatch.setattr(LocalTunnel, "is_active", property(lambda self: self._server is not None))

    service = SSHService(initial_client=FakeClient())
    service.ensure_local_tunnel("runner-test", remote_host="127.0.0.1", remote_port=39967)

    snapshot = service.local_tunnel_snapshots()

    assert snapshot == [
        {
            "schemaVersion": "local-ssh-tunnel.v1",
            "name": "runner-test",
            "localHost": "127.0.0.1",
            "localPort": 18001,
            "remoteHost": "127.0.0.1",
            "remotePort": 39967,
            "active": True,
        }
    ]
    assert "_transport" not in str(snapshot)


def test_list_directory_uses_sftp_and_returns_directory_metadata() -> None:
    class FakeSftp:
        def __init__(self) -> None:
            self.closed = False

        def normalize(self, path: str) -> str:
            assert path == "./databases"
            return "/home/user/databases"

        def listdir_attr(self, path: str):
            assert path == "/home/user/databases"
            return [
                SimpleNamespace(filename="kraken2", st_mode=0o040755, st_size=0, st_mtime=1710000000),
                SimpleNamespace(filename="notes.txt", st_mode=0o100644, st_size=120, st_mtime=1710000010),
                SimpleNamespace(filename=".cache", st_mode=0o040755, st_size=0, st_mtime=1710000020),
            ]

        def close(self) -> None:
            self.closed = True

    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def __init__(self) -> None:
            self.sftp = FakeSftp()

        def get_transport(self):
            return FakeTransport()

        def open_sftp(self):
            return self.sftp

    client = FakeClient()
    service = SSHService(initial_client=client)

    result = service.list_directory("~/databases", directories_only=True, limit=20)

    assert result["path"] == "/home/user/databases"
    assert result["parentPath"] == "/home/user"
    assert [item["name"] for item in result["items"]] == [".cache", "kraken2"]
    assert result["items"][0]["type"] == "directory"
    assert client.sftp.closed is True


def test_list_directory_allows_large_remote_directory_listing() -> None:
    class FakeSftp:
        def __init__(self) -> None:
            self.closed = False

        def normalize(self, path: str) -> str:
            assert path == "/data/db"
            return "/data/db"

        def listdir_attr(self, path: str):
            assert path == "/data/db"
            return [
                SimpleNamespace(filename=f"file_{index:04d}.fa", st_mode=0o100644, st_size=1, st_mtime=1)
                for index in range(700)
            ]

        def close(self) -> None:
            self.closed = True

    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def __init__(self) -> None:
            self.sftp = FakeSftp()

        def get_transport(self):
            return FakeTransport()

        def open_sftp(self):
            return self.sftp

    service = SSHService(initial_client=FakeClient())

    result = service.list_directory("/data/db", directories_only=False, limit=5000)

    assert len(result["items"]) == 700
    assert result["truncated"] is False


def test_ssh_service_is_connected_reports_transport_os_errors_as_disconnected() -> None:
    class FakeClient:
        def get_transport(self):
            raise OSError("transport socket closed")

    service = SSHService(initial_client=FakeClient())

    assert service.is_connected is False


def test_ssh_service_is_connected_does_not_mask_unexpected_transport_errors() -> None:
    class FakeClient:
        def get_transport(self):
            raise RuntimeError("transport adapter crashed")

    service = SSHService(initial_client=FakeClient())

    with pytest.raises(RuntimeError, match="transport adapter crashed"):
        _connected = service.is_connected


def test_ssh_reconnector_retries_channel_io_errors(monkeypatch) -> None:
    attempts = {"count": 0}
    failures: list[str] = []

    def connect():
        attempts["count"] += 1
        raise OSError("ssh socket closed")

    monkeypatch.setattr("core.remote.ssh_reconnect.time.sleep", lambda _delay: None)
    reconnector = SSHReconnector(connect, max_retries=2, on_failure=failures.append)

    reconnector._run()

    assert attempts["count"] == 2
    assert failures == ["SSH 重连失败"]


def test_ssh_reconnector_does_not_mask_unexpected_connect_errors(monkeypatch) -> None:
    failures: list[str] = []

    def connect():
        raise RuntimeError("ssh adapter crashed")

    monkeypatch.setattr("core.remote.ssh_reconnect.time.sleep", lambda _delay: None)
    reconnector = SSHReconnector(connect, max_retries=2, on_failure=failures.append)

    with pytest.raises(RuntimeError, match="ssh adapter crashed"):
        reconnector._run()
    assert failures == []
