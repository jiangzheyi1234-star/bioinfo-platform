from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.remote_runner.manager import RemoteRunnerManager
from tests.helpers.remote_runner_control_plane import _health_endpoint_json


def test_rotate_token_validates_new_token_with_transport_health(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[tuple[str, str]] = []
    health_calls: list[tuple[str, list[int]]] = []
    stored_tokens: list[dict[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "test -s" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd:
                return 0, "", ""
            if "start_service.sh" in cmd or "remote_runner.run" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, remote: str, local: str) -> None:
            assert remote == "/home/tester/.h2ometa/runner/shared/config/runner.json"
            Path(local).write_text("{}", encoding="utf-8")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))

        def ensure_local_tunnel(self, *args: Any, **kwargs: Any):
            assert kwargs["remote_port"] == 43127
            return SimpleNamespace(local_port=18765)

    class FakeClient:
        def __init__(self, *, base_url: str, token: str, timeout: int) -> None:
            assert base_url == "http://127.0.0.1:18765"
            assert token == "rotated-token"
            assert timeout == 5

        def get_json(
            self, path: str, *, accepted_statuses: set[int] | None = None
        ) -> dict[str, object]:
            health_calls.append((path, sorted(accepted_statuses or [])))
            health = _health_endpoint_json(path, accepted_statuses)
            if health is not None:
                return health
            raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(
        "core.remote_runner.token_rotation.secrets.token_urlsafe",
        lambda _size: "rotated-token",
    )
    monkeypatch.setattr("core.remote_runner.token_rotation.RemoteRunnerHttpClient", FakeClient)
    monkeypatch.setattr(
        "core.remote_runner.token_rotation.store_runner_token",
        lambda **kwargs: stored_tokens.append(dict(kwargs)) or "runner://srv_rotated",
    )

    result = manager.rotate_token(
        server_id="srv_1",
        ssh_service=FakeSSH(),
        server_record={
            "bootstrap_version": "v1",
            "runner_mode": "background_process",
            "service_port": 43127,
            "token_ref": "runner://srv_1",
        },
    )

    assert result == {"token_ref": "runner://srv_rotated"}
    assert health_calls == [
        ("/health/startup", [200, 503]),
        ("/health/live", []),
        ("/health/ready", [200, 503]),
    ]
    assert stored_tokens == [{"server_id": "srv_1", "token": "rotated-token"}]
    assert uploads
