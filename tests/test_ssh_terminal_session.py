from core.remote.ssh_service import TerminalSession


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
