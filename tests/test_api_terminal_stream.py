from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from apps.api.main import app


class _FakeStreamingSession:
    def __init__(self) -> None:
        self.session_id = "term_1"
        self.sent: list[str] = []
        self.resizes: list[tuple[int, int]] = []
        self._close_gate = threading.Event()
        self._snapshot_version = 1

    def wait_for_update(self, *, cursor: int = 0, version: int = -1, timeout: float = 1.0):
        if version < 0:
            return (
                {
                    "session_id": self.session_id,
                    "cursor": len("ready\n"),
                    "output": "ready\n"[max(0, cursor) :],
                    "connected": True,
                    "input_enabled": True,
                    "closed": False,
                    "message": "",
                    "created_at": 0.0,
                    "closed_at": None,
                },
                self._snapshot_version,
            )
        self._close_gate.wait(timeout)
        return (
            {
                "session_id": self.session_id,
                "cursor": len("ready\n"),
                "output": "",
                "connected": False,
                "input_enabled": False,
                "closed": True,
                "message": "SSH 已断开，终端会话已结束",
                "created_at": 0.0,
                "closed_at": 1.0,
            },
            self._snapshot_version + 1,
        )

    def send(self, data: str) -> None:
        self.sent.append(data)

    def resize(self, *, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))


class _FakeRuntime:
    def __init__(self, session: _FakeStreamingSession) -> None:
        self.session = session

    def get_terminal_session(self, *, session_id: str):
        assert session_id == self.session.session_id
        return self.session

    def send_terminal_input(self, *, session_id: str, data: str):
        assert session_id == self.session.session_id
        self.session.send(data)
        return {"session_id": session_id, "accepted": True}

    def resize_terminal_session(self, *, session_id: str, cols: int, rows: int):
        assert session_id == self.session.session_id
        self.session.resize(cols=cols, rows=rows)
        return {"session_id": session_id, "accepted": True, "cols": cols, "rows": rows}

    def shutdown(self) -> None:
        return None


class _FakeRuntimeGetter:
    def __init__(self, runtime: _FakeRuntime) -> None:
        self._runtime = runtime

    def __call__(self) -> _FakeRuntime:
        return self._runtime

    def cache_clear(self) -> None:
        return None


def test_terminal_stream_websocket_supports_input_resize_and_closed(monkeypatch) -> None:
    session = _FakeStreamingSession()
    runtime = _FakeRuntime(session)
    monkeypatch.setattr("apps.api.main.get_runtime_service", _FakeRuntimeGetter(runtime))

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/ssh/terminal/sessions/{session.session_id}/stream?cursor=0") as websocket:
            assert websocket.receive_json() == {"type": "ready", "session_id": session.session_id}
            assert websocket.receive_json() == {"type": "output", "data": "ready\n"}
            assert websocket.receive_json() == {"type": "state", "connected": True, "input_enabled": True, "message": ""}

            websocket.send_json({"type": "input", "data": "pwd\n"})
            websocket.send_json({"type": "resize", "cols": 132, "rows": 40})
            websocket.send_json({"type": "ping"})

            assert websocket.receive_json() == {"type": "pong"}
            assert session.sent == ["pwd\n"]
            assert session.resizes == [(132, 40)]

            session._close_gate.set()
            assert websocket.receive_json() == {"type": "closed", "message": "SSH 已断开，终端会话已结束"}
