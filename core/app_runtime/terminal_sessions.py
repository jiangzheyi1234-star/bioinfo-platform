from __future__ import annotations

import time

from core.remote.ssh_service import TerminalSession

from .errors import RuntimeServiceError


TERMINAL_SESSION_IDLE_TTL_SECONDS = 30 * 60
TERMINAL_SESSION_CLOSED_TTL_SECONDS = 60
TERMINAL_SESSION_MAX_ACTIVE = 8


class RuntimeTerminalSessionMixin:
    def create_terminal_session(self, cols: int = 120, rows: int = 28) -> dict:
        with self._lock:
            self._ensure_initialized()
            self._reap_terminal_sessions()
            ssh = self._ensure_ssh_connected()
            session = ssh.open_terminal_session(cols=cols, rows=rows)
            self._terminal_sessions[session.session_id] = session
            self._enforce_terminal_session_limit()
            return session.snapshot(cursor=0)

    def get_terminal_session(self, session_id: str) -> TerminalSession:
        with self._lock:
            self._reap_terminal_sessions()
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            return session

    def send_terminal_input(self, session_id: str, data: str) -> dict:
        with self._lock:
            self._reap_terminal_sessions()
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.send(data)
            return {"session_id": session_id, "accepted": True}

    def resize_terminal_session(self, session_id: str, cols: int, rows: int) -> dict:
        with self._lock:
            self._reap_terminal_sessions()
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.resize(cols, rows)
            return {"session_id": session_id, "cols": cols, "rows": rows}

    def close_terminal_session(self, session_id: str) -> dict:
        with self._lock:
            self._reap_terminal_sessions()
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            self._close_terminal_session_entry(
                session_id=session_id,
                session=session,
                message="终端会话已结束",
            )
            self._terminal_sessions.pop(session_id, None)
            return {"session_id": session_id, "closed": True}

    def _close_all_terminal_sessions(self) -> None:
        ssh = self._service_locator.ssh_service
        for session_id, session in list(self._terminal_sessions.items()):
            if ssh is not None:
                ssh.close_terminal_session(session_id, message="终端会话已结束")
            else:
                session.close(message="终端会话已结束")
        self._terminal_sessions.clear()

    def _reap_terminal_sessions(self) -> None:
        now = time.time()
        for session_id, session in list(self._terminal_sessions.items()):
            if _terminal_session_should_reap(session, now=now):
                self._close_terminal_session_entry(
                    session_id=session_id,
                    session=session,
                    message=_terminal_session_reap_message(session),
                )
                self._terminal_sessions.pop(session_id, None)

    def _enforce_terminal_session_limit(self) -> None:
        overflow = len(self._terminal_sessions) - TERMINAL_SESSION_MAX_ACTIVE
        if overflow <= 0:
            return
        ordered = sorted(
            self._terminal_sessions.items(),
            key=lambda item: (float(item[1].last_accessed_at), float(item[1].created_at), item[0]),
        )
        for session_id, session in ordered[:overflow]:
            self._close_terminal_session_entry(
                session_id=session_id,
                session=session,
                message="终端会话数量超过上限，已关闭最早闲置会话",
            )
            self._terminal_sessions.pop(session_id, None)

    def _close_terminal_session_entry(
        self,
        *,
        session_id: str,
        session: TerminalSession,
        message: str,
    ) -> None:
        ssh = self._service_locator.ssh_service
        if ssh is not None:
            ssh.close_terminal_session(session_id, message=message)
        else:
            session.close(message=message)


def _terminal_session_should_reap(session: TerminalSession, *, now: float) -> bool:
    if session.closed:
        closed_at = session.closed_at or session.last_accessed_at
        return now - closed_at >= TERMINAL_SESSION_CLOSED_TTL_SECONDS
    return now - session.last_accessed_at >= TERMINAL_SESSION_IDLE_TTL_SECONDS


def _terminal_session_reap_message(session: TerminalSession) -> str:
    if session.closed:
        return "终端会话已结束"
    return "终端会话闲置超时，已自动关闭"
