from __future__ import annotations

from types import SimpleNamespace

from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    _remote_runner_manifest,
    _remote_runner_protocol_config,
)


class _RollbackSsh:
    def ensure_local_tunnel(self, name: str, **kwargs):
        assert name == "runner-srv_rollback"
        assert kwargs == {"remote_host": "127.0.0.1", "remote_port": 43127}
        return SimpleNamespace(local_port=18765)


def _metadata() -> dict[str, object]:
    return {
        "release_switch": {"target_release": "/runner/releases/new"},
        "upgradeGuard": {
            "maintenanceOwner": "srv_rollback:upgrade:lifecycle",
        },
    }


def _patch_rollback_runtime(monkeypatch, events: list[object]) -> None:
    def read_remote_json(cls, _ssh_service, path: str, _label: str):
        if path.endswith("bootstrap_manifest.json"):
            return _remote_runner_manifest(version="old")
        return _remote_runner_protocol_config(
            version="old",
            release="/runner/releases/old",
        )

    monkeypatch.setattr(
        RemoteRunnerManager,
        "_read_remote_json",
        classmethod(read_remote_json),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_run_checked",
        classmethod(lambda cls, *args, **kwargs: events.append("stop") or (0, "", "")),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_upload_remote_file_atomic",
        classmethod(lambda cls, *args, **kwargs: events.append("config")),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_switch_current_release",
        classmethod(lambda cls, **kwargs: events.append("switch")),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_start_remote_runner_service",
        classmethod(lambda cls, **kwargs: events.append("start")),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_wait_for_runtime_state",
        classmethod(
            lambda cls, **kwargs: events.append("runtime")
            or {"bindPort": 43127, "pid": 123, "version": "old"}
        ),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_wait_for_runner_live",
        classmethod(
            lambda cls, client, **kwargs: events.append("live")
            or {"status": "ok", "service": "h2ometa-remote"}
        ),
    )
    monkeypatch.setattr(
        RemoteRunnerManager,
        "_wait_for_runner_health",
        classmethod(
            lambda cls, client, **kwargs: events.append("ready")
            or {"ready": {"ok": True}}
        ),
    )
    monkeypatch.setattr(
        "core.remote_runner.bootstrap_activation.resolve_runner_token",
        lambda token_ref: "previous-token" if token_ref == "runner://srv_rollback" else "",
    )


def _attempt_rollback(tmp_path, metadata: dict[str, object]) -> None:
    previous_config = tmp_path / "previous-runner.json"
    previous_config.write_text("{}", encoding="utf-8")
    RemoteRunnerManager._attempt_release_rollback(
        ssh_service=_RollbackSsh(),
        server_id="srv_rollback",
        server_record={"token_ref": "runner://srv_rollback"},
        bootstrap_action="upgrade",
        previous_version="old",
        previous_release="/runner/releases/old",
        previous_mode="systemd_user",
        previous_config_path=previous_config,
        remote_current="/runner/current",
        remote_config="/runner/config.json",
        remote_log="/runner/service.log",
        remote_runtime_state="/runner/runner-state.json",
        bootstrap_metadata=metadata,
        failure="new release canary failed",
    )


def test_rollback_releases_recorded_guard_after_live_and_ready(monkeypatch, tmp_path) -> None:
    events: list[object] = []
    metadata = _metadata()
    _patch_rollback_runtime(monkeypatch, events)

    def release(cls, *, client, endpoint_id, payload):
        events.append(("release", dict(payload)))
        return {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v1",
            "action": payload["action"],
            "owner": payload["owner"],
            "released": True,
        }

    monkeypatch.setattr(
        RemoteRunnerManager,
        "_call_lifecycle_guard_endpoint_with_client",
        classmethod(release),
    )

    _attempt_rollback(tmp_path, metadata)

    assert events[-3:] == [
        "live",
        "ready",
        ("release", {"action": "upgrade", "owner": "srv_rollback:upgrade:lifecycle"}),
    ]
    rollback = metadata["rollback"]
    assert rollback["restored"] is True
    assert rollback["message"] == "previous release restored"
    assert rollback["lifecycleGuardRecovery"] == {
        "schemaVersion": "h2ometa.remote-runner-rollback-lifecycle-guard-recovery.v1",
        "required": True,
        "bootstrapAction": "upgrade",
        "maintenanceOwner": "srv_rollback:upgrade:lifecycle",
        "liveVerified": True,
        "releaseAttempted": True,
        "released": True,
        "readyVerified": True,
        "failClosed": False,
        "admissionState": "open",
        "message": "rollback lifecycle guard released",
        "alreadyAbsent": False,
    }
    assert metadata["release_switch"]["active_release"] == "/runner/releases/old"
    assert metadata["release_switch"]["rolled_back"] is True


def test_rollback_guard_release_failure_remains_fail_closed(monkeypatch, tmp_path) -> None:
    events: list[object] = []
    metadata = _metadata()
    _patch_rollback_runtime(monkeypatch, events)

    def release_failure(cls, *, client, endpoint_id, payload):
        events.append(("release", dict(payload)))
        return {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v1",
            "action": payload["action"],
            "owner": "another-owner",
            "released": True,
        }

    monkeypatch.setattr(
        RemoteRunnerManager,
        "_call_lifecycle_guard_endpoint_with_client",
        classmethod(release_failure),
    )

    _attempt_rollback(tmp_path, metadata)

    assert events[-3:] == [
        "live",
        "ready",
        ("release", {"action": "upgrade", "owner": "srv_rollback:upgrade:lifecycle"}),
    ]
    rollback = metadata["rollback"]
    recovery = rollback["lifecycleGuardRecovery"]
    assert rollback["restored"] is False
    assert rollback["message"] == "remote runner bootstrap guard release was not confirmed"
    assert recovery["liveVerified"] is True
    assert recovery["releaseAttempted"] is True
    assert recovery["released"] is False
    assert recovery["readyVerified"] is True
    assert recovery["failClosed"] is True
    assert recovery["admissionState"] == "guarded-or-unknown"
    assert "remains fail-closed" in recovery["message"]
    assert recovery["nextAction"] == "retry owner-matched lifecycle guard release"
    assert metadata["upgradeGuardRelease"]["released"] is False
    assert metadata["upgradeGuardRelease"]["reason"] == "execution-lifecycle-guard-release-unconfirmed"
    assert metadata["release_switch"] == {"target_release": "/runner/releases/new"}


def test_rollback_accepts_owner_matched_guard_already_released_by_failed_canary(
    monkeypatch, tmp_path
) -> None:
    events: list[object] = []
    metadata = _metadata()
    _patch_rollback_runtime(monkeypatch, events)

    def release_absent(cls, *, client, endpoint_id, payload):
        events.append(("release", dict(payload)))
        return {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v1",
            "action": payload["action"],
            "owner": payload["owner"],
            "released": False,
            "previous": {},
        }

    monkeypatch.setattr(
        RemoteRunnerManager,
        "_call_lifecycle_guard_endpoint_with_client",
        classmethod(release_absent),
    )

    _attempt_rollback(tmp_path, metadata)

    rollback = metadata["rollback"]
    recovery = rollback["lifecycleGuardRecovery"]
    assert rollback["restored"] is True
    assert events[-1] == (
        "release",
        {"action": "upgrade", "owner": "srv_rollback:upgrade:lifecycle"},
    )
    assert recovery["released"] is False
    assert recovery["alreadyAbsent"] is True
    assert recovery["admissionState"] == "open"
    assert recovery["failClosed"] is False
    assert recovery["message"] == "rollback lifecycle guard was already absent"


def test_rollback_ready_failure_retains_guard_and_admission_closed(monkeypatch, tmp_path) -> None:
    events: list[object] = []
    metadata = _metadata()
    _patch_rollback_runtime(monkeypatch, events)

    def release(cls, *, client, endpoint_id, payload):
        events.append(("release", dict(payload)))
        return {
            "schemaVersion": "h2ometa.execution-lifecycle-guard-release.v1",
            "action": payload["action"],
            "owner": payload["owner"],
            "released": True,
        }

    def not_ready(cls, client, **kwargs):
        events.append("ready")
        raise RemoteRunnerManagerError("previous runner is not ready")

    monkeypatch.setattr(
        RemoteRunnerManager,
        "_call_lifecycle_guard_endpoint_with_client",
        classmethod(release),
    )
    monkeypatch.setattr(RemoteRunnerManager, "_wait_for_runner_health", classmethod(not_ready))

    _attempt_rollback(tmp_path, metadata)

    rollback = metadata["rollback"]
    recovery = rollback["lifecycleGuardRecovery"]
    assert rollback["restored"] is False
    assert ("release", {"action": "upgrade", "owner": "srv_rollback:upgrade:lifecycle"}) not in events
    assert recovery["released"] is False
    assert recovery["readyVerified"] is False
    assert recovery["admissionState"] == "guarded-or-unknown"
    assert recovery["failClosed"] is True
    assert "ready health failed before guard release" in recovery["message"]
    assert recovery["nextAction"] == (
        "repair previous runner readiness, then release the lifecycle guard"
    )
