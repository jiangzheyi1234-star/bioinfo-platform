from __future__ import annotations

import pytest

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator
from core.app_runtime import terminal_sessions


class FakeTerminalSession:
    def __init__(
        self,
        session_id: str,
        *,
        created_at: float,
        last_accessed_at: float | None = None,
        closed: bool = False,
        closed_at: float | None = None,
    ) -> None:
        self.session_id = session_id
        self.created_at = created_at
        self.last_accessed_at = last_accessed_at if last_accessed_at is not None else created_at
        self.closed = closed
        self.closed_at = closed_at
        self.close_messages: list[str] = []

    def snapshot(self, cursor: int = 0) -> dict[str, object]:
        self.last_accessed_at = 1000.0
        return {
            "session_id": self.session_id,
            "cursor": cursor,
            "base_cursor": 0,
            "output": "",
            "truncated": False,
            "scrollback_limit": 524288,
            "connected": not self.closed,
            "input_enabled": not self.closed,
            "closed": self.closed,
            "message": self.close_messages[-1] if self.close_messages else "",
            "created_at": self.created_at,
            "closed_at": self.closed_at,
        }

    def send(self, _data: str) -> None:
        self.last_accessed_at = 1000.0

    def resize(self, _cols: int, _rows: int) -> None:
        self.last_accessed_at = 1000.0

    def close(self, message: str = "终端会话已结束") -> None:
        self.closed = True
        self.closed_at = self.closed_at or 1000.0
        self.close_messages.append(message)


class FakeSSH:
    is_connected = True

    def __init__(self) -> None:
        self.sessions: dict[str, FakeTerminalSession] = {}
        self.closed_sessions: list[tuple[str, str]] = []

    def open_terminal_session(self, cols: int = 120, rows: int = 28) -> FakeTerminalSession:
        session_id = f"term_{len(self.sessions) + 1}"
        session = FakeTerminalSession(session_id, created_at=1000.0)
        self.sessions[session_id] = session
        return session

    def close_terminal_session(self, session_id: str, message: str = "终端会话已结束") -> None:
        session = self.sessions.pop(session_id)
        session.close(message=message)
        self.closed_sessions.append((session_id, message))

    def close(self) -> None:
        self.is_connected = False


def _runtime_with_sessions(fake_ssh: FakeSSH) -> RuntimeService:
    service = RuntimeService(service_locator=ServiceLocator(ssh_service=fake_ssh))
    service._initialized = True
    return service


def test_idle_terminal_session_is_reaped_before_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ssh = FakeSSH()
    session = FakeTerminalSession("term_idle", created_at=0.0, last_accessed_at=10.0)
    fake_ssh.sessions[session.session_id] = session
    service = _runtime_with_sessions(fake_ssh)
    service._terminal_sessions[session.session_id] = session
    monkeypatch.setattr(
        terminal_sessions.time,
        "time",
        lambda: 10.0 + terminal_sessions.TERMINAL_SESSION_IDLE_TTL_SECONDS + 1,
    )

    with pytest.raises(RuntimeServiceError, match="unknown session"):
        service.get_terminal_session(session.session_id)

    assert session.session_id not in service._terminal_sessions
    assert session.session_id not in fake_ssh.sessions
    assert fake_ssh.closed_sessions == [
        (session.session_id, "终端会话闲置超时，已自动关闭"),
    ]


def test_recent_terminal_session_survives_reap_for_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ssh = FakeSSH()
    session = FakeTerminalSession("term_recent", created_at=0.0, last_accessed_at=100.0)
    fake_ssh.sessions[session.session_id] = session
    service = _runtime_with_sessions(fake_ssh)
    service._terminal_sessions[session.session_id] = session
    monkeypatch.setattr(terminal_sessions.time, "time", lambda: 100.0 + 5)

    assert service.get_terminal_session(session.session_id) is session
    assert fake_ssh.closed_sessions == []


def test_terminal_session_limit_closes_oldest_session(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ssh = FakeSSH()
    oldest = FakeTerminalSession("term_oldest", created_at=1.0, last_accessed_at=1.0)
    recent = FakeTerminalSession("term_recent", created_at=2.0, last_accessed_at=2.0)
    fake_ssh.sessions = {oldest.session_id: oldest, recent.session_id: recent}
    service = _runtime_with_sessions(fake_ssh)
    service._terminal_sessions = dict(fake_ssh.sessions)
    monkeypatch.setattr(terminal_sessions, "TERMINAL_SESSION_MAX_ACTIVE", 2)
    monkeypatch.setattr(terminal_sessions.time, "time", lambda: 1000.0)

    created = service.create_terminal_session()

    assert created["session_id"] == "term_3"
    assert oldest.session_id not in service._terminal_sessions
    assert oldest.session_id not in fake_ssh.sessions
    assert recent.session_id in service._terminal_sessions
    assert "term_3" in service._terminal_sessions
    assert fake_ssh.closed_sessions == [
        (oldest.session_id, "终端会话数量超过上限，已关闭最早闲置会话"),
    ]
