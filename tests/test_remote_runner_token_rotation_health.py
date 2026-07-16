from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from core.contracts.execution_activity import (
    EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
)
from core.contracts.remote_endpoints import RemoteEndpointContractError
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.manager import RemoteRunnerManager
from core.remote_runner.token_rotation import _runner_rotation_failure_types, _unlink_temp_configs
from tests.helpers.remote_runner_control_plane import (
    _health_endpoint_json,
    _remote_runner_manifest,
    _remote_runner_protocol_config,
    _runtime_state_json,
)


def test_rotate_token_validates_new_token_with_transport_health(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[tuple[str, str]] = []
    downloads: list[str] = []
    health_calls: list[tuple[str, list[int]]] = []
    lifecycle_requests: list[dict[str, Any]] = []
    lifecycle_releases: list[tuple[str, dict[str, Any], list[int]]] = []
    stored_tokens: list[dict[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="v1")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="v1")), ""
            if cmd.endswith("/shared/runtime/runner-state.json"):
                return 0, _runtime_state_json(version="v1"), ""
            if cmd == "kill -0 123":
                return 0, "", ""
            if "test -s" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd:
                return 0, "", ""
            if "start_service.sh" in cmd or "remote_runner.run" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, remote: str, local: str) -> None:
            assert remote == "/home/tester/.h2ometa/runner/shared/config/runner.json"
            downloads.append(local)
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

        def post_json(
            self,
            path: str,
            payload: dict[str, Any],
            *,
            extra_headers: dict[str, str] | None = None,
            accepted_statuses: set[int] | None = None,
        ) -> dict[str, object]:
            assert extra_headers is None
            lifecycle_releases.append((path, dict(payload), sorted(accepted_statuses or [])))
            if path == "/api/v1/execution/lifecycle-guard/release":
                return {
                    "data": {
                        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
                        "action": "token-rotation",
                        "owner": "srv_1:token-rotation:lifecycle",
                        "released": True,
                        "releasedAt": "2099-01-01T00:00:00Z",
                        "previous": {},
                    }
                }
            raise AssertionError(f"unexpected post path: {path}")

    monkeypatch.setattr(
        "core.remote_runner.token_rotation.secrets.token_urlsafe",
        lambda _size: "rotated-token",
    )
    monkeypatch.setattr("core.remote_runner.token_rotation.RemoteRunnerHttpClient", FakeClient)
    monkeypatch.setattr(
        manager,
        "request_execution_lifecycle_guard",
        lambda **kwargs: lifecycle_requests.append(dict(kwargs))
        or {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
            "action": "token-rotation",
            "owner": "srv_1:token-rotation:lifecycle",
            "idle": True,
            "maintenanceActive": True,
            "activeLeaseCount": 0,
            "allocatedResourceCount": 0,
            "resourceWaitCount": 0,
            "queuedJobCount": 0,
            "claimedJobCount": 0,
            "runningSlotCount": 0,
            "blockReasons": [],
        },
    )
    monkeypatch.setattr(
        "core.remote_runner.token_rotation.store_runner_token",
        lambda **kwargs: stored_tokens.append(dict(kwargs)) or "runner://srv_rotated",
    )

    fake_ssh = FakeSSH()
    result = manager.rotate_token(
        server_id="srv_1",
        ssh_service=fake_ssh,
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
        ("/health/live", [200]),
        ("/health/ready", [200, 503]),
    ]
    assert len(lifecycle_requests) == 1
    lifecycle_request = lifecycle_requests[0]
    assert lifecycle_request["server_id"] == "srv_1"
    assert lifecycle_request["ssh_service"] is fake_ssh
    assert lifecycle_request["server_record"] == {
        "bootstrap_version": "v1",
        "runner_mode": "background_process",
        "service_port": 43127,
        "token_ref": "runner://srv_1",
    }
    assert lifecycle_request["action"] == "token-rotation"
    assert lifecycle_request["owner"] == "srv_1:token-rotation:lifecycle"
    assert lifecycle_request["ttl_seconds"] == 600
    assert lifecycle_request["timeout"] == 30
    assert lifecycle_releases == [
        (
            "/api/v1/execution/lifecycle-guard/release",
            {"action": "token-rotation", "owner": "srv_1:token-rotation:lifecycle"},
            [200],
        )
    ]
    assert stored_tokens == [{"server_id": "srv_1", "token": "rotated-token"}]
    assert uploads
    assert len(downloads) == 1
    assert not Path(downloads[0]).exists()
    assert not Path(uploads[0][0]).exists()


def test_guard_release_ambiguity_keeps_verified_rotated_runtime(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[str] = []
    commands: list[str] = []
    stored_tokens: list[dict[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            commands.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="v1")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="v1")), ""
            if "test -s" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd:
                return 0, "", ""
            if "start_service.sh" in cmd or "remote_runner.run" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, _remote: str, local: str) -> None:
            Path(local).write_text('{"token":"old"}', encoding="utf-8")

        def upload(self, local: str, _remote: str) -> None:
            uploads.append(Path(local).read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "core.remote_runner.token_rotation.secrets.token_urlsafe",
        lambda _size: "rotated-token",
    )
    monkeypatch.setattr(
        "core.remote_runner.token_rotation.RemoteRunnerHttpClient",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "core.remote_runner.token_rotation.store_runner_token",
        lambda **kwargs: stored_tokens.append(dict(kwargs)) or "runner://srv_1",
    )
    monkeypatch.setattr(
        manager,
        "request_execution_lifecycle_guard",
        lambda **_kwargs: {"maintenanceActive": True},
    )
    monkeypatch.setattr(
        manager,
        "_wait_for_runtime_state",
        lambda **_kwargs: {"bindPort": 43127},
    )
    monkeypatch.setattr(
        manager,
        "_open_runner_tunnel",
        lambda **_kwargs: SimpleNamespace(local_port=18765),
    )
    monkeypatch.setattr(
        manager,
        "_wait_for_runner_health",
        lambda *_args, **_kwargs: {"ready": {"ok": True}},
    )

    def ambiguous_release(**_kwargs) -> None:
        raise RemoteRunnerClientError("release response lost")

    monkeypatch.setattr(manager, "_release_token_rotation_guard", ambiguous_release)

    with pytest.raises(
        RemoteRunnerManagerError,
        match="committed a verified ready runtime.*release was not confirmed",
    ):
        manager.rotate_token(
            server_id="srv_1",
            ssh_service=FakeSSH(),
            server_record={
                "bootstrap_version": "v1",
                "runner_mode": "background_process",
                "service_port": 43127,
                "token_ref": "runner://srv_1",
            },
        )

    assert len(uploads) == 1
    assert stored_tokens == [{"server_id": "srv_1", "token": "rotated-token"}]
    assert sum("pkill -f '[r]emote_runner.run'" in command for command in commands) == 1
    assert sum("start_service.sh" in command for command in commands) == 1


def test_rotate_token_fails_loudly_when_systemd_restart_fails(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[str] = []
    temp_paths: list[str] = []
    restart_attempts = 0
    lifecycle_releases: list[dict[str, Any]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            nonlocal restart_attempts
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="v1")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="v1")), ""
            if "test -s" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if cmd == "systemctl --user restart h2ometa-remote.service":
                restart_attempts += 1
                if restart_attempts == 1:
                    return 1, "", "systemd unit failed"
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, _remote: str, local: str) -> None:
            temp_paths.append(local)
            Path(local).write_text('{"token":"old"}', encoding="utf-8")

        def upload(self, local: str, _remote: str) -> None:
            temp_paths.append(local)
            uploads.append(Path(local).read_text(encoding="utf-8"))

        def ensure_local_tunnel(self, *args: Any, **kwargs: Any):
            raise AssertionError("rotation must fail before opening a tunnel")

    monkeypatch.setattr(
        manager,
        "request_execution_lifecycle_guard",
        lambda **_kwargs: {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
            "blockReasons": [],
        },
    )
    monkeypatch.setattr(
        manager,
        "release_execution_lifecycle_guard",
        lambda **kwargs: lifecycle_releases.append(dict(kwargs)) or {"released": True},
    )

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
        with pytest.raises(
            RemoteRunnerManagerError,
            match="restart remote runner after token rotation failed: systemd unit failed",
        ):
            manager.rotate_token(
                server_id="srv_1",
                ssh_service=FakeSSH(),
                server_record={
                    "bootstrap_version": "v1",
                    "runner_mode": "systemd_user",
                    "service_port": 43127,
                    "token_ref": "runner://srv_1",
                },
            )

    store_token.assert_not_called()
    assert len(uploads) == 2
    assert uploads[1] == '{"token":"old"}'
    assert restart_attempts == 2
    assert lifecycle_releases == []
    assert len(set(temp_paths)) == 2
    assert all(not Path(path).exists() for path in temp_paths)


@pytest.mark.parametrize(
    "release",
    [
        {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v2",
            "action": "token-rotation",
            "owner": "srv_1:token-rotation:lifecycle",
            "released": True,
        },
        {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
            "action": "bootstrap",
            "owner": "srv_1:token-rotation:lifecycle",
            "released": True,
        },
        {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
            "action": "token-rotation",
            "owner": "srv_other:token-rotation:lifecycle",
            "released": True,
        },
        {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
            "action": "token-rotation",
            "owner": "srv_1:token-rotation:lifecycle",
            "released": False,
        },
    ],
)
def test_token_rotation_rejects_unconfirmed_lifecycle_guard_release(
    monkeypatch,
    release: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_call_lifecycle_guard_endpoint_with_client",
        classmethod(lambda cls, **_kwargs: release),
    )

    with pytest.raises(
        RemoteRunnerManagerError,
        match="token rotation lifecycle guard release was not confirmed",
    ) as exc_info:
        RemoteRunnerManager._release_token_rotation_guard(
            client=object(),
            owner="srv_1:token-rotation:lifecycle",
        )

    assert exc_info.value.detail == release


def test_temp_cleanup_attempts_all_paths_and_propagates_errors() -> None:
    calls: list[str] = []

    class FakePath:
        def __init__(self, name: str, *, error: OSError | None = None) -> None:
            self.name = name
            self.error = error

        def unlink(self, *, missing_ok: bool) -> None:
            assert missing_ok is True
            calls.append(self.name)
            if self.error is not None:
                raise self.error

    cleanup_error = OSError("temporary config cleanup failed")
    with pytest.raises(OSError, match="temporary config cleanup failed"):
        _unlink_temp_configs(
            FakePath("old", error=cleanup_error),  # type: ignore[arg-type]
            FakePath("new"),  # type: ignore[arg-type]
        )

    assert calls == ["old", "new"]


def test_temp_cleanup_failure_is_combined_with_primary_rotation_failure(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    rotation_error = RemoteRunnerManagerError("rotation failed")
    cleanup_error = OSError("cleanup failed")

    def fail_rotation(**_kwargs: Any) -> dict[str, Any]:
        raise rotation_error

    def fail_cleanup(*_paths: Path | None) -> None:
        raise cleanup_error

    monkeypatch.setattr(manager, "_rotate_token_with_temp_configs", fail_rotation)
    monkeypatch.setattr("core.remote_runner.token_rotation._unlink_temp_configs", fail_cleanup)

    with pytest.raises(BaseExceptionGroup) as exc_info:
        manager.rotate_token()

    assert exc_info.value.exceptions == (rotation_error, cleanup_error)


def test_remote_endpoint_contract_failures_enter_token_rotation_rollback() -> None:
    assert RemoteEndpointContractError in _runner_rotation_failure_types()


def test_rotate_token_fails_loudly_when_background_stop_fails(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[str] = []
    stop_attempts = 0
    lifecycle_releases: list[dict[str, Any]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            nonlocal stop_attempts
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="v1")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="v1")), ""
            if "test -s" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if cmd == "pkill -f '[r]emote_runner.run'":
                stop_attempts += 1
                if stop_attempts == 1:
                    return 1, "", "no remote runner process matched"
                return 0, "", ""
            if "start_service.sh" in cmd or "remote_runner.run" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, _remote: str, local: str) -> None:
            Path(local).write_text('{"token":"old"}', encoding="utf-8")

        def upload(self, local: str, _remote: str) -> None:
            uploads.append(Path(local).read_text(encoding="utf-8"))

        def ensure_local_tunnel(self, *args: Any, **kwargs: Any):
            raise AssertionError("rotation must fail before opening a tunnel")

    monkeypatch.setattr(
        manager,
        "request_execution_lifecycle_guard",
        lambda **_kwargs: {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
            "blockReasons": [],
        },
    )
    monkeypatch.setattr(
        manager,
        "release_execution_lifecycle_guard",
        lambda **kwargs: lifecycle_releases.append(dict(kwargs)) or {"released": True},
    )

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
        with pytest.raises(
            RemoteRunnerManagerError,
            match="stop remote runner after token rotation failed: no remote runner process matched",
        ):
            manager.rotate_token(
                server_id="srv_1",
                ssh_service=FakeSSH(),
                server_record={
                    "bootstrap_version": "v1",
                    "runner_mode": "background_process",
                    "service_port": 43127,
                    "token_ref": "runner://srv_1",
                },
            )

    store_token.assert_not_called()
    assert len(uploads) == 2
    assert uploads[1] == '{"token":"old"}'
    assert stop_attempts == 2
    assert lifecycle_releases == []


def test_rotate_token_does_not_persist_local_token_before_remote_update_succeeds(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[tuple[str, str]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="0.1.0-control-plane")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="0.1.0-control-plane")), ""
            raise RuntimeError("boom")

        def download(self, remote: str, local: str) -> None:
            raise RuntimeError("download failed")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))
            raise RuntimeError("upload failed")

    fake_ssh = FakeSSH()

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
        try:
            manager.rotate_token(
                server_id="srv_test",
                server={},
                ssh_service=fake_ssh,
                server_record={
                    "bootstrap_version": "0.1.0-control-plane",
                    "runner_mode": "background_process",
                    "service_port": 43127,
                },
            )
        except Exception as exc:
            assert "download failed" in str(exc)
        else:
            raise AssertionError("rotate_token should fail when remote update fails")

    store_token.assert_not_called()
    assert uploads == []


def test_rotate_token_restores_and_retains_guard_on_tunnel_adapter_errors(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    uploads: list[str] = []
    lifecycle_requests: list[dict[str, object]] = []
    lifecycle_releases: list[dict[str, object]] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "bootstrap_manifest.json" in cmd:
                return 0, json.dumps(_remote_runner_manifest(version="0.1.0-control-plane")), ""
            if cmd.endswith("/shared/config/runner.json"):
                return 0, json.dumps(_remote_runner_protocol_config(version="0.1.0-control-plane")), ""
            if cmd.endswith("/shared/runtime/runner-state.json"):
                return 0, _runtime_state_json(version="0.1.0-control-plane"), ""
            if cmd == "kill -0 123":
                return 0, "", ""
            if cmd.startswith("test -s ") or cmd.startswith("pkill -f ") or "start_service.sh" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def download(self, _remote: str, local: str) -> None:
            Path(local).write_text('{"token":"old"}', encoding="utf-8")

        def upload(self, local: str, _remote: str) -> None:
            uploads.append(Path(local).read_text(encoding="utf-8"))

        def ensure_local_tunnel(self, *args: Any, **kwargs: Any):
            raise RuntimeError("tunnel adapter crashed")

    monkeypatch.setattr(
        manager,
        "request_execution_lifecycle_guard",
        lambda **kwargs: lifecycle_requests.append(dict(kwargs))
        or {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
            "action": "token-rotation",
            "owner": "srv_test:token-rotation:lifecycle",
            "idle": True,
            "maintenanceActive": True,
            "activeLeaseCount": 0,
            "allocatedResourceCount": 0,
            "resourceWaitCount": 0,
            "queuedJobCount": 0,
            "claimedJobCount": 0,
            "runningSlotCount": 0,
            "blockReasons": [],
        },
    )
    monkeypatch.setattr(
        manager,
        "release_execution_lifecycle_guard",
        lambda **kwargs: lifecycle_releases.append(dict(kwargs))
        or {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v1",
            "action": "token-rotation",
            "owner": "srv_test:token-rotation:lifecycle",
            "released": True,
            "releasedAt": "2099-01-01T00:00:00Z",
            "previous": {},
        },
    )

    with patch("core.remote_runner.token_rotation.store_runner_token") as store_token:
        with pytest.raises(RemoteRunnerManagerError, match="tunnel adapter crashed"):
            manager.rotate_token(
                server_id="srv_test",
                server={},
                ssh_service=FakeSSH(),
                server_record={
                    "bootstrap_version": "0.1.0-control-plane",
                    "runner_mode": "background_process",
                    "service_port": 43127,
                },
            )

    store_token.assert_not_called()
    assert len(uploads) == 2
    assert '"token":"old"' not in uploads[0]
    assert uploads[1] == '{"token":"old"}'
    assert lifecycle_requests[0]["action"] == "token-rotation"
    assert lifecycle_releases == []
