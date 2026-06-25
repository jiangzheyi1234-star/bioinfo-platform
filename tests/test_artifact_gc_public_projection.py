from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import artifact_lifecycle_service
from apps.remote_runner import route_utils
from apps.remote_runner.artifact_lifecycle_service import (
    ARTIFACT_GC_CONFIRMATION,
    preview_artifact_gc,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.main import app
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_artifact_lifecycle_gc import _persist_managed_artifact


def test_artifact_gc_preview_route_returns_public_projection_without_storage_identifiers(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    artifact = _persist_managed_artifact(cfg, "run_gc_public_preview", status="completed")
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    raw_plan = preview_artifact_gc(cfg, {"retentionDays": 30})
    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/gc/preview",
        json={"retentionDays": 30, "actor": "operator@example.test"},
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert raw_plan["candidates"][0]["storageUri"] == artifact["storageUri"]
    assert raw_plan["candidates"][0]["path"] == artifact["path"]
    assert raw_plan["candidates"][0]["artifactIds"] == [artifact["artifactId"]]
    assert raw_plan["candidates"][0]["runIds"] == ["run_gc_public_preview"]
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schemaVersion"] == "h2ometa.artifact-gc-public-plan.v1"
    assert data["candidateCount"] == 1
    assert data["candidates"][0]["storageBackend"] == artifact["storageBackend"]
    assert data["candidates"][0]["artifactCount"] == 1
    assert data["candidates"][0]["runCount"] == 1
    _assert_no_storage_identifiers(data, artifact)


def test_artifact_gc_run_route_returns_public_projection_but_evidence_keeps_deletion_fields(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    artifact = _persist_managed_artifact(cfg, "run_gc_public_run", status="completed")
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/gc/run",
        json={
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "actor": "operator@example.test",
        },
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    evidence = list_evidence_events(
        cfg,
        subject_kind="artifact_gc",
        subject_id=data["planId"],
        event_type="artifact.gc.v1",
    )
    assert data["schemaVersion"] == "h2ometa.artifact-gc-public-run.v1"
    assert data["deletedCount"] == 1
    assert data["deleted"][0]["payloadDeleted"] is True
    assert data["deleted"][0]["artifactCount"] == 1
    assert data["plan"]["schemaVersion"] == "h2ometa.artifact-gc-public-plan.v1"
    _assert_no_storage_identifiers(data, artifact)
    assert evidence[-1]["payload"]["deleted"][0]["storageUri"] == artifact["storageUri"]
    assert evidence[-1]["payload"]["deleted"][0]["sha256"] == artifact["sha256"]
    assert evidence[-1]["payload"]["deleted"][0]["artifactIds"] == [artifact["artifactId"]]
    assert evidence[-1]["payload"]["deleted"][0]["runIds"] == ["run_gc_public_run"]


def test_artifact_gc_delete_failure_response_does_not_leak_path_or_sha(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    artifact = _persist_managed_artifact(cfg, "run_gc_public_failure", status="completed")
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_delete(_cfg, _item):
        raise RuntimeError(f"cannot delete {artifact['path']} with sha {artifact['sha256']}")

    monkeypatch.setattr(artifact_lifecycle_service, "delete_artifact_payload", fail_delete)
    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/gc/run",
        json={
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "actor": "operator@example.test",
        },
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ARTIFACT_GC_DELETE_FAILED"
    serialized = json.dumps(response.json(), sort_keys=True)
    assert artifact["path"] not in serialized
    assert artifact["storageUri"] not in serialized
    assert artifact["sha256"] not in serialized


def _assert_no_storage_identifiers(payload: dict, artifact: dict) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    forbidden_values = {
        artifact["path"],
        artifact["storageUri"],
        artifact["sha256"],
        artifact["artifactId"],
        "run_gc_public_preview",
        "run_gc_public_run",
        "run_gc_public_failure",
    }
    forbidden_keys = {
        "path",
        "localPath",
        "storageUri",
        "groupId",
        "artifactIds",
        "runIds",
        "materializationIds",
        "sha256",
    }
    for value in forbidden_values:
        assert value not in serialized
    for key in forbidden_keys:
        assert key not in serialized
