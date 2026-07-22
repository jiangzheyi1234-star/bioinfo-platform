from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.contracts.execution_activity import (
    EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
)
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.manager import RemoteRunnerManager
from tests.helpers.remote_runner_control_plane import (
    _remote_runner_manifest,
    _remote_runner_protocol_config,
)


PREVIOUS_RELEASE = "/runner/releases/previous"
TARGET_RELEASE = "/runner/releases/target"


class _CompatibleRollbackManager(RemoteRunnerManager):
    events: list[str] = []
    manifest: dict[str, Any] = _remote_runner_manifest(version="previous")
    remote_config: dict[str, Any] = _remote_runner_protocol_config(
        version="previous",
        release=PREVIOUS_RELEASE,
    )

    @classmethod
    def _read_remote_json(cls, _ssh_service, path: str, _label: str):
        if path.endswith("bootstrap_manifest.json"):
            return dict(cls.manifest)
        return dict(cls.remote_config)

    @classmethod
    def _run_checked(cls, _ssh_service, _cmd: str, *, step: str, timeout: int):
        cls.events.append(step)
        return 0, "", ""

    @classmethod
    def _upload_remote_file_atomic(cls, _ssh_service, **_kwargs) -> None:
        cls.events.append("restore-config")

    @classmethod
    def _switch_current_release(cls, **_kwargs) -> None:
        cls.events.append("switch-current")

    @classmethod
    def _start_remote_runner_service(cls, **_kwargs) -> None:
        cls.events.append("start-previous")

    @classmethod
    def _wait_for_runtime_state(cls, **_kwargs) -> dict[str, object]:
        cls.events.append("runtime-state")
        return {"bindPort": 43127, "pid": 321, "version": "previous"}

    @classmethod
    def _wait_for_runner_live(cls, _client, **_kwargs) -> dict[str, object]:
        cls.events.append("live")
        return {"status": "ok"}

    @classmethod
    def _wait_for_runner_health(cls, _client, **_kwargs) -> dict[str, object]:
        cls.events.append("ready")
        return {"ready": {"ok": True}}

    @classmethod
    def _release_bootstrap_lifecycle_guard(cls, **_kwargs) -> dict[str, object]:
        cls.events.append("release-guard")
        return {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
            "action": "upgrade",
            "owner": "srv:upgrade:lifecycle",
            "released": True,
            "previous": {"owner": "srv:upgrade:lifecycle"},
        }


def _metadata() -> dict[str, Any]:
    return {
        "preflight": {"platform": "linux-64"},
        "release_switch": {"target_release": TARGET_RELEASE},
        "upgradeGuard": {"maintenanceOwner": "srv:upgrade:lifecycle"},
    }


def _attempt_rollback(
    manager_type: type[RemoteRunnerManager],
    *,
    tmp_path: Path,
    metadata: dict[str, Any],
) -> None:
    previous_config = tmp_path / "previous-runner.json"
    previous_config.write_text("{}", encoding="utf-8")
    ssh = SimpleNamespace(
        ensure_local_tunnel=lambda *_args, **_kwargs: SimpleNamespace(local_port=18765)
    )
    manager_type._attempt_release_rollback(
        ssh_service=ssh,
        server_id="srv",
        server_record={"token_ref": "runner://srv"},
        bootstrap_action="upgrade",
        previous_version="previous",
        previous_release=PREVIOUS_RELEASE,
        previous_mode="background_process",
        previous_config_path=previous_config,
        remote_current="/runner/current",
        remote_config="/runner/shared/config/runner.json",
        remote_log="/runner/shared/logs/runner.log",
        remote_runtime_state="/runner/shared/runtime/runner-state.json",
        bootstrap_metadata=metadata,
        failure="target failed",
    )


def test_exact_protocol_rollback_verifies_ready_before_releasing_guard(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _CompatibleRollbackManager.events = []
    metadata = _metadata()
    monkeypatch.setattr(
        "core.remote_runner.bootstrap_activation.resolve_runner_token",
        lambda _token_ref: "previous-token",
    )

    _attempt_rollback(_CompatibleRollbackManager, tmp_path=tmp_path, metadata=metadata)

    events = _CompatibleRollbackManager.events
    assert events.index("live") < events.index("ready") < events.index("release-guard")
    assert metadata["rollback"]["restored"] is True
    recovery = metadata["rollback"]["lifecycleGuardRecovery"]
    assert recovery["readyVerified"] is True
    assert recovery["released"] is True
    assert recovery["failClosed"] is False


def test_incompatible_protocol_rollback_stops_and_requires_forward_repair(
    tmp_path: Path,
) -> None:
    class IncompatibleRollbackManager(_CompatibleRollbackManager):
        events: list[str] = []
        manifest = {
            "service": "h2ometa-remote",
            "version": "previous",
            "runtime": {
                "provider": "bundled",
                "python": "runtime/bin/python",
                "sqlite": {"minimumVersion": "3.51.3"},
            },
        }

    metadata = _metadata()

    _attempt_rollback(IncompatibleRollbackManager, tmp_path=tmp_path, metadata=metadata)

    rollback = metadata["rollback"]
    assert rollback["restored"] is False
    assert rollback["forwardRepairRequired"] is True
    assert rollback["protocolCompatible"] is False
    assert "restore-config" in IncompatibleRollbackManager.events
    assert "switch-current" not in IncompatibleRollbackManager.events
    assert "start-previous" not in IncompatibleRollbackManager.events
    assert "release-guard" not in IncompatibleRollbackManager.events
    recovery = rollback["lifecycleGuardRecovery"]
    assert recovery["failClosed"] is True
    assert recovery["admissionState"] == "guarded-or-unknown"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", "unexpected-runner"),
        ("platform", "unexpected-platform"),
        ("runtime", {"provider": "system", "python": "/usr/bin/python"}),
        ("runtime", {"provider": "bundled", "python": "runtime/bin/python"}),
    ],
)
def test_drifted_previous_manifest_requires_forward_repair(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    class DriftedManifestRollbackManager(_CompatibleRollbackManager):
        events: list[str] = []

    DriftedManifestRollbackManager.manifest = {
        **_remote_runner_manifest(version="previous"),
        field: value,
    }
    metadata = _metadata()

    _attempt_rollback(
        DriftedManifestRollbackManager,
        tmp_path=tmp_path,
        metadata=metadata,
    )

    rollback = metadata["rollback"]
    assert rollback["forwardRepairRequired"] is True
    assert rollback["protocolCompatible"] is False
    assert "switch-current" not in DriftedManifestRollbackManager.events
    assert "start-previous" not in DriftedManifestRollbackManager.events
    assert "release-guard" not in DriftedManifestRollbackManager.events


def test_drifted_previous_config_binding_requires_forward_repair(
    tmp_path: Path,
) -> None:
    class DriftedConfigRollbackManager(_CompatibleRollbackManager):
        events: list[str] = []
        remote_config = {
            **_remote_runner_protocol_config(
                version="previous",
                release=PREVIOUS_RELEASE,
            ),
            "runner_python": "/unexpected/runtime/bin/python",
        }

    metadata = _metadata()

    _attempt_rollback(
        DriftedConfigRollbackManager,
        tmp_path=tmp_path,
        metadata=metadata,
    )

    rollback = metadata["rollback"]
    assert rollback["forwardRepairRequired"] is True
    assert rollback["protocolCompatible"] is False
    assert "switch-current" not in DriftedConfigRollbackManager.events
    assert "start-previous" not in DriftedConfigRollbackManager.events
    assert "release-guard" not in DriftedConfigRollbackManager.events
    assert (
        "exact release/config binding"
        in rollback["lifecycleGuardRecovery"]["nextAction"]
    )


def test_pre_activation_failure_retains_guard_without_unproven_release() -> None:
    class FailIfGuardReleasedManager(RemoteRunnerManager):
        def release_execution_lifecycle_guard(self, **_kwargs):
            raise AssertionError("pre-activation failure must not release the guard")

    metadata = _metadata()
    failure = FailIfGuardReleasedManager()._pre_activation_failure(
        exc=RemoteRunnerManagerError("candidate preflight failed"),
        bootstrap_action="upgrade",
        bootstrap_metadata=metadata,
    )

    assert isinstance(failure, RemoteRunnerManagerError)
    assert "lifecycle guard retained" in str(failure)
    recovery = metadata["preActivationRecovery"]
    assert recovery["forwardRepairRequired"] is True
    assert recovery["failClosed"] is True
    assert recovery["admissionState"] == "guarded-or-unknown"
