from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from apps.remote_runner import artifact_lifecycle_policy_route_service, route_utils
from apps.remote_runner.artifact_lifecycle_controller import evaluate_artifact_lifecycle_controller_tick
from apps.remote_runner.artifact_lifecycle_policy import (
    get_artifact_lifecycle_policy,
    set_artifact_lifecycle_policy,
)
from apps.remote_runner.artifact_lifecycle_service import preview_artifact_gc
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_lifecycle_policy_defaults_then_persists_versioned_fingerprint(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    default = get_artifact_lifecycle_policy(cfg)

    assert default.policy_id == "default"
    assert default.policy_version == 0
    assert default.persisted is False
    assert default.retention_days == 30

    first = set_artifact_lifecycle_policy(
        cfg,
        {
            "retentionDays": 14,
            "eligibleRunStatuses": ["failed", "completed"],
            "quotaBytes": 4096,
            "maxDeleteBytesPerTick": 1024,
            "actor": "operator@example.test",
            "reason": "trial-retention",
        },
    )
    second = set_artifact_lifecycle_policy(
        cfg,
        {
            "retentionDays": 21,
            "eligibleRunStatuses": ["failed", "completed"],
            "quotaBytes": 4096,
            "maxDeleteBytesPerTick": 1024,
            "actor": "operator@example.test",
            "reason": "trial-retention",
        },
    )
    current = get_artifact_lifecycle_policy(cfg)

    assert first.policy_version == 1
    assert second.policy_version == 2
    assert current.policy_version == 2
    assert current.retention_days == 21
    assert current.eligible_run_statuses == ("completed", "failed")
    assert current.policy_fingerprint != first.policy_fingerprint
    assert str(tmp_path) not in str(current)


def test_artifact_lifecycle_controller_uses_persisted_policy_by_default(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    policy = set_artifact_lifecycle_policy(
        cfg,
        {
            "retentionDays": 9,
            "eligibleRunStatuses": ["completed"],
            "quotaBytes": 0,
            "maxDeleteBytesPerTick": 2048,
            "actor": "operator@example.test",
            "reason": "controller-default-policy",
        },
    )

    tick = evaluate_artifact_lifecycle_controller_tick(cfg, payload={})

    assert tick["policy"]["policyId"] == "default"
    assert tick["policy"]["policyVersion"] == 1
    assert tick["policy"]["policyFingerprint"] == policy.policy_fingerprint
    assert tick["policy"]["retentionDays"] == 9
    assert tick["policy"]["eligibleRunStatuses"] == ["completed"]
    assert tick["policy"]["quotaBytes"] == 0
    assert tick["policy"]["maxDeleteBytesPerTick"] == 2048


def test_controller_gc_preview_fingerprint_tracks_policy_version(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    payload = {
        "retentionDays": 9,
        "eligibleRunStatuses": ["completed"],
        "actor": "operator@example.test",
        "reason": "controller-default-policy",
    }

    set_artifact_lifecycle_policy(cfg, payload)
    first_tick = evaluate_artifact_lifecycle_controller_tick(cfg, payload={})
    set_artifact_lifecycle_policy(cfg, payload)
    second_tick = evaluate_artifact_lifecycle_controller_tick(cfg, payload={})

    assert first_tick["policy"]["policyVersion"] == 1
    assert second_tick["policy"]["policyVersion"] == 2
    assert first_tick["policy"]["policyFingerprint"] == second_tick["policy"]["policyFingerprint"]
    assert first_tick["gcPreview"]["planFingerprint"] != second_tick["gcPreview"]["planFingerprint"]


def test_artifact_gc_rejects_mismatched_policy_fingerprint(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="ARTIFACT_LIFECYCLE_POLICY_FINGERPRINT_MISMATCH"):
        preview_artifact_gc(
            cfg,
            {
                "policyId": "default",
                "policyVersion": 1,
                "policyFingerprint": "alpfp_wrong",
                "retentionDays": 9,
                "eligibleRunStatuses": ["completed"],
                "reason": "controller-default-policy",
            },
        )


def test_artifact_gc_rejects_partial_inline_policy_override(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="ARTIFACT_GC_INLINE_POLICY_FIELD_REQUIRED: retentionDays"):
        preview_artifact_gc(
            cfg,
            {
                "maxDeleteBytes": 1024,
                "actor": "operator@example.test",
            },
        )


def test_artifact_lifecycle_policy_read_route_denies_wrong_role_before_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_read(*_args, **_kwargs):
        raise AssertionError("policy read must not run before authorization")

    monkeypatch.setattr(artifact_lifecycle_policy_route_service, "get_governed_artifact_lifecycle_policy", fail_read)

    response = TestClient(app).get(
        "/api/v1/artifacts/lifecycle/policy",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    events = list_governance_audit_events(cfg, action="artifact.lifecycle.policy.read")["items"]
    assert events[-1]["decision"] == "deny"
    assert events[-1]["subjectKind"] == "artifact_lifecycle_policy"


def test_artifact_lifecycle_policy_set_route_requires_curator_before_write(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_set(*_args, **_kwargs):
        raise AssertionError("policy set must not run before authorization")

    monkeypatch.setattr(artifact_lifecycle_policy_route_service, "set_governed_artifact_lifecycle_policy", fail_set)

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/policy",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "set-artifact-lifecycle-policy",
            "retentionDays": 14,
            "eligibleRunStatuses": ["completed", "failed"],
            "reason": "trial-retention",
        },
    )

    assert response.status_code == 403
    events = list_governance_audit_events(cfg, action="artifact.lifecycle.policy.set")["items"]
    assert events[-1]["decision"] == "deny"
    assert events[-1]["subjectKind"] == "artifact_lifecycle_policy"


def test_artifact_lifecycle_policy_set_route_requires_complete_policy(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/policy",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "set-artifact-lifecycle-policy",
        },
    )

    assert response.status_code == 422
    assert list_governance_audit_events(cfg, action="artifact.lifecycle.policy.set")["items"] == []


def test_artifact_lifecycle_policy_set_route_records_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/policy",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "set-artifact-lifecycle-policy",
            "retentionDays": 14,
            "eligibleRunStatuses": ["completed", "failed"],
            "quotaBytes": 4096,
            "maxDeleteBytesPerTick": 1024,
            "actor": "operator@example.test",
            "reason": "trial-retention",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schemaVersion"] == "h2ometa.artifact-lifecycle-policy.v1"
    assert data["policyVersion"] == 1
    assert data["retentionDays"] == 14
    assert data["eligibleRunStatuses"] == ["completed", "failed"]
    assert data["redactionPolicy"] == {
        "pathsExposed": False,
        "storageUrisExposed": False,
        "artifactIdsExposed": False,
        "runIdsExposed": False,
    }
    audit = list_governance_audit_events(cfg, action="artifact.lifecycle.policy.set")["items"]
    assert audit[-1]["decision"] == "allow"
    assert audit[-1]["details"]["policyVersion"] == 1
    assert audit[-1]["details"]["retentionDays"] == 14
    assert audit[-1]["details"]["quotaProvided"] is True
    assert audit[-1]["details"]["maxDeleteBytesPerTickProvided"] is True
    assert str(tmp_path) not in str(audit[-1])
