import threading
import time
from types import SimpleNamespace

from core.remote.ssh_service import LocalTunnel, SSHService, TerminalSession


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


def test_terminal_session_snapshot_marks_closed_session_as_unavailable() -> None:
    session = TerminalSession("term_test_closed", DummyChannel())
    session.close(message="SSH disconnected")
    snapshot = session.snapshot()

    assert snapshot["connected"] is False
    assert snapshot["input_enabled"] is False
    assert snapshot["closed"] is True
    assert snapshot["message"] == "SSH disconnected"
    assert snapshot["closed_at"] is not None


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
