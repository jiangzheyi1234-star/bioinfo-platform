from __future__ import annotations

from core.remote.ssh_service import TerminalSession

from .errors import RuntimeServiceError


class RuntimeTerminalSessionMixin:
    def create_terminal_session(self, cols: int = 120, rows: int = 28) -> dict:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
            session = ssh.open_terminal_session(cols=cols, rows=rows)
            self._terminal_sessions[session.session_id] = session
            return session.snapshot(cursor=0)

    def get_terminal_session(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            return session

    def send_terminal_input(self, session_id: str, data: str) -> dict:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.send(data)
            return {"session_id": session_id, "accepted": True}

    def resize_terminal_session(self, session_id: str, cols: int, rows: int) -> dict:
        with self._lock:
            session = self._terminal_sessions.get(session_id)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.resize(cols, rows)
            return {"session_id": session_id, "cols": cols, "rows": rows}

    def close_terminal_session(self, session_id: str) -> dict:
        with self._lock:
            session = self._terminal_sessions.pop(session_id, None)
            if not session:
                raise RuntimeServiceError(f"unknown session: {session_id}")
            session.close(message="终端会话已结束")
            return {"session_id": session_id, "closed": True}

    def _close_all_terminal_sessions(self) -> None:
        for session in list(self._terminal_sessions.values()):
            session.close(message="终端会话已结束")
        self._terminal_sessions.clear()
