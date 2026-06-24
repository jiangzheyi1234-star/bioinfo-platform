from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.remote_runner import artifact_lifecycle_controller as controller


ROOT = Path(__file__).resolve().parents[1]


def test_configured_artifact_lifecycle_controller_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER", raising=False)
    monkeypatch.setattr(controller, "load_remote_runner_config", lambda: SimpleNamespace(token="token"))

    assert controller.start_configured_artifact_lifecycle_controller_supervisor() is None


def test_configured_artifact_lifecycle_controller_builds_policy_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    sentinel = object()

    def fake_start(cfg, *, poll_interval_seconds: float, policy_payload: dict[str, Any]):
        captured.append(
            {
                "cfg": cfg,
                "pollIntervalSeconds": poll_interval_seconds,
                "policyPayload": policy_payload,
            }
        )
        return sentinel

    cfg = SimpleNamespace(token="token")
    monkeypatch.setattr(controller, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(controller, "start_artifact_lifecycle_controller_supervisor", fake_start)
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER", "1")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_POLL_SECONDS", "12.5")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_RETENTION_DAYS", "7")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_STATUSES", "completed, failed")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_QUOTA_BYTES", "1024")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_MAX_DELETE_BYTES_PER_TICK", "512")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_REASON", "ttl-preview")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_ACTOR", "artifact-supervisor")

    supervisor = controller.start_configured_artifact_lifecycle_controller_supervisor()

    assert supervisor is sentinel
    assert captured == [
        {
            "cfg": cfg,
            "pollIntervalSeconds": 12.5,
            "policyPayload": {
                "retentionDays": 7,
                "reason": "ttl-preview",
                "actor": "artifact-supervisor",
                "eligibleRunStatuses": ["completed", "failed"],
                "quotaBytes": 1024,
                "maxDeleteBytesPerTick": 512,
            },
        }
    ]


def test_configured_artifact_lifecycle_controller_rejects_invalid_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller, "load_remote_runner_config", lambda: SimpleNamespace(token="token"))
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER", "1")
    monkeypatch.setenv("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_POLL_SECONDS", "0")

    with pytest.raises(ValueError, match="ARTIFACT_LIFECYCLE_CONTROLLER_POLL_INTERVAL_INVALID"):
        controller.start_configured_artifact_lifecycle_controller_supervisor()


def test_artifact_lifecycle_controller_supervisor_runs_preview_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    cfg = SimpleNamespace(service_name="remote-runner")

    def fake_tick(tick_cfg, *, payload: dict[str, Any] | None = None):
        calls.append({"cfg": tick_cfg, "payload": payload})
        return {"tickId": "alct_test"}

    monkeypatch.setattr(controller, "run_artifact_lifecycle_controller_once", fake_tick)

    supervisor = controller.start_artifact_lifecycle_controller_supervisor(
        cfg,
        poll_interval_seconds=0.01,
        policy_payload={"retentionDays": 7},
    )
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    supervisor.stop(timeout_seconds=1)

    assert calls
    assert calls[0] == {"cfg": cfg, "payload": {"retentionDays": 7}}


def test_artifact_lifecycle_controller_source_boundary_excludes_delete_paths() -> None:
    source = (ROOT / "apps" / "remote_runner" / "artifact_lifecycle_controller.py").read_text(encoding="utf-8")

    assert "run_artifact_gc" not in source
    assert "delete_artifact_payload" not in source
    assert "mark_lifecycle_deleted" not in source
    assert "ARTIFACT_GC_CONFIRMATION" not in source
