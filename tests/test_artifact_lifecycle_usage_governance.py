from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import artifact_lifecycle_service
from apps.remote_runner import control_service
from apps.remote_runner import route_utils
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_lifecycle_usage_read_allows_auditor_and_artifact_curator_roles(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    auditor = make_configured_remote_runner(
        tmp_path / "auditor",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    curator = make_configured_remote_runner(
        tmp_path / "curator",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )

    try:
        authorize_action(denied, "artifact.lifecycle.usage.read")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("artifact.lifecycle.usage.read must require auditor or artifact-curator")
    deny_events = list_governance_audit_events(denied, action="artifact.lifecycle.usage.read")["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["artifact-curator", "auditor"]
    assert deny_events[-1]["details"]["providedRoles"] == ["workflow-operator"]
    assert authorize_action(auditor, "artifact.lifecycle.usage.read").roles == ("auditor",)
    assert authorize_action(curator, "artifact.lifecycle.usage.read").roles == ("artifact-curator",)


def test_artifact_lifecycle_usage_route_denies_wrong_role_before_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_usage_read(*_args, **_kwargs):
        raise AssertionError("artifact lifecycle usage read must not run before authorization")

    monkeypatch.setattr(control_service, "build_governed_artifact_lifecycle_usage", fail_usage_read)

    response = TestClient(app).get(
        "/api/v1/artifacts/lifecycle/usage?quotaBytes=100",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action="artifact.lifecycle.usage.read")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "artifact_lifecycle_usage"
    assert events[0]["subjectId"] == "authorization"


def test_artifact_lifecycle_usage_route_records_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        artifact_lifecycle_service,
        "build_artifact_lifecycle_usage",
        lambda *_args, **_kwargs: {
            "schemaVersion": "h2ometa.artifact-lifecycle-usage.v1",
            "checkedAt": "2099-06-07T10:00:00Z",
            "artifactCount": 3,
            "activeArtifactCount": 2,
            "deletedArtifactCount": 1,
            "activeStorageObjectCount": 2,
            "activeBytes": 128,
            "deletedBytes": 64,
            "ledgerOnlyMaterializationCount": 1,
            "ledgerOnlyActiveBytes": 32,
            "byBackend": {
                "local": {
                    "storageObjectCount": 2,
                    "bytes": 128,
                    "storageUri": "file:///C:/secret/artifacts/not-a-real-field",
                }
            },
            "quota": {
                "quotaBytes": 100,
                "usedBytes": 128,
                "remainingBytes": 0,
                "overageBytes": 28,
                "usedPercent": 128.0,
            },
        },
    )

    response = TestClient(app).get(
        "/api/v1/artifacts/lifecycle/usage?quotaBytes=100",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["activeBytes"] == 128
    audit = list_governance_audit_events(cfg, action="artifact.lifecycle.usage.read")["items"]
    assert audit[-1]["details"] == {
        "artifactCount": 3,
        "activeArtifactCount": 2,
        "deletedArtifactCount": 1,
        "activeStorageObjectCount": 2,
        "activeBytes": 128,
        "deletedBytes": 64,
        "ledgerOnlyMaterializationCount": 1,
        "ledgerOnlyActiveBytes": 32,
        "quotaProvided": True,
        "quotaBytes": 100,
        "quotaOverageBytes": 28,
    }
    serialized_audit = json.dumps(audit, sort_keys=True)
    assert "file:///C:/secret" not in serialized_audit
    assert "storageUri" not in serialized_audit
    assert "rbac-token" not in serialized_audit
