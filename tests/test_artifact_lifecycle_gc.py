from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.remote_runner import artifact_lifecycle_service, route_utils
from apps.remote_runner import artifact_lifecycle_controller_control as controller_control
from apps.remote_runner.api_models import ArtifactLifecycleControllerRunOnceRequest
from apps.remote_runner.artifact_lifecycle_service import (
    ARTIFACT_GC_CONFIRMATION,
    build_artifact_lifecycle_usage,
    preview_artifact_gc,
    run_artifact_gc,
)
from apps.remote_runner.artifact_lifecycle_controller import (
    ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
    evaluate_artifact_lifecycle_controller_tick,
)
from apps.remote_runner.artifact_lifecycle_policy import (
    artifact_lifecycle_policy_fingerprint,
    normalize_artifact_lifecycle_policy_payload,
)
from apps.remote_runner.artifact_product_service import build_result_artifact_audit, export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.storage import create_run_record, fetch_run_results, persist_artifact, upsert_tool
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.removed: list[tuple[str, str]] = []

    def fput_object(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ):
        self.objects[(bucket, object_name)] = Path(file_path).read_bytes()
        return type("Result", (), {"bucket_name": bucket, "object_name": object_name})()

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.removed.append((bucket, object_name))
        self.objects.pop((bucket, object_name), None)


def test_artifact_gc_preview_reports_usage_and_protection_reasons(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    candidate = _persist_managed_artifact(cfg, "run_gc_candidate", status="completed")
    active = _persist_managed_artifact(cfg, "run_gc_active", status="running")
    exported_full = _persist_managed_artifact(cfg, "run_gc_exported_full", status="completed")
    exported_metadata = _persist_managed_artifact(cfg, "run_gc_exported_metadata", status="completed")
    production = _persist_managed_artifact(cfg, "run_gc_production", status="completed")
    full_package = export_result_package(cfg, "res_run_gc_exported_full", include_artifacts=True)
    metadata_package = export_result_package(
        cfg,
        "res_run_gc_exported_metadata",
        include_artifacts=False,
    )
    Path(full_package["packagePath"]).unlink()
    Path(metadata_package["packagePath"]).unlink()
    _protect_run_as_production_evidence(cfg, "run_gc_production")

    usage = build_artifact_lifecycle_usage(cfg, quota_bytes=10)
    plan = preview_artifact_gc(cfg)

    assert usage["activeArtifactCount"] == 5
    assert usage["quota"]["overageBytes"] > 0
    assert [item["artifactIds"] for item in plan["candidates"]] == [[candidate["artifactId"]]]
    protected_by_artifact = {
        artifact_id: set(item["reasons"])
        for item in plan["protected"]
        for artifact_id in item["artifactIds"]
    }
    assert "run_not_terminal" in protected_by_artifact[active["artifactId"]]
    assert protected_by_artifact[exported_full["artifactId"]] == {"export_package"}
    assert protected_by_artifact[exported_metadata["artifactId"]] == {"export_package"}
    assert "production_evidence" in protected_by_artifact[production["artifactId"]]


def test_artifact_gc_preview_uses_quota_pressure_without_bypassing_hard_protections(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    candidate = _persist_managed_artifact(cfg, "run_gc_quota_candidate", status="completed")
    active = _persist_managed_artifact(cfg, "run_gc_quota_active", status="running")

    plan = preview_artifact_gc(
        cfg,
        _inline_policy_payload(
            retention_days=5000,
            quota_bytes=0,
            reason="operator-retention",
        ),
    )

    assert plan["policy"]["quotaBytes"] == 0
    assert plan["quotaOverageBytes"] >= candidate["sizeBytes"] + active["sizeBytes"]
    assert [item["artifactIds"] for item in plan["candidates"]] == [[candidate["artifactId"]]]
    assert plan["candidates"][0]["reason"] == "quota_pressure"
    protected_by_artifact = {
        artifact_id: set(item["reasons"])
        for item in plan["protected"]
        for artifact_id in item["artifactIds"]
    }
    assert "run_not_terminal" in protected_by_artifact[active["artifactId"]]
    public = artifact_lifecycle_service.public_artifact_gc_plan(plan)
    assert public["policy"]["quotaBytes"] == 0
    assert public["quotaOverageBytes"] == plan["quotaOverageBytes"]
    assert public["candidates"][0]["reason"] == "quota_pressure"
    assert "storageUri" not in repr(public)
    assert "artifactId" not in repr(public)


def test_artifact_lifecycle_controller_tick_previews_without_deleting_payloads(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_controller", status="completed")
    artifact_path = Path(artifact["path"])

    tick = evaluate_artifact_lifecycle_controller_tick(
        cfg,
        {
            "retentionDays": 30,
            "eligibleRunStatuses": ["completed", "failed", "canceled", "cancelled"],
            "quotaBytes": 0,
            "actor": "artifact-supervisor",
            "reason": "controller-preview",
        },
    )
    fetched = fetch_run_results(cfg, "run_gc_controller")["artifacts"][0]
    evidence = list_evidence_events(
        cfg,
        subject_kind="artifact_lifecycle_controller",
        subject_id=tick["tickId"],
        event_type=ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
    )
    gc_evidence = list_evidence_events(
        cfg,
        subject_kind="artifact_gc",
        subject_id=tick["gcPreview"]["planId"],
        event_type="artifact.gc.v1",
    )
    governance = list_governance_audit_events(
        cfg,
        subject_kind="artifact_lifecycle_controller",
        subject_id=tick["tickId"],
        action="artifact.lifecycle.controller_tick",
    )["items"]

    assert tick["schemaVersion"] == "h2ometa.artifact-lifecycle-controller-tick.v1"
    assert tick["executionMode"] == "preview-only"
    assert tick["deleteConfirmationRequired"] is True
    assert tick["quotaOverageBytes"] == artifact["sizeBytes"]
    assert tick["wouldDeleteCount"] == 1
    assert tick["gcPreview"]["candidateCount"] == 1
    assert tick["gcPreview"]["planFingerprint"].startswith("agcfp_")
    assert tick["gcPreview"]["planFingerprint"] == governance[-1]["details"]["planFingerprint"]
    assert tick["policyDecision"] == {
        "decision": "preview_ready",
        "reasonCode": "DELETE_CONFIRMATION_REQUIRED",
        "message": "GC candidates are available, but the controller is preview-only.",
        "deletionAuthorized": False,
        "deleteConfirmationRequired": True,
        "candidateCount": 1,
        "deleteBytes": artifact["sizeBytes"],
    }
    assert tick["retentionHolds"]["schemaVersion"] == "artifact-retention-hold-summary.v1"
    assert tick["retentionHolds"]["reasonCount"] == 0
    assert tick["batchSafety"] == {
        "schemaVersion": "artifact-gc-batch-safety.v1",
        "maxDeleteBytes": None,
        "maxDeleteBytesApplied": False,
        "candidateCount": 1,
        "candidateBytes": artifact["sizeBytes"],
        "candidateArtifactCount": 1,
        "candidateRunCount": 1,
        "limitedGroupCount": 0,
        "limitedBytes": 0,
    }
    assert tick["gcPreview"]["candidateArtifactCount"] == 1
    assert tick["gcPreview"]["candidateRunCount"] == 1
    assert "candidateGroupIds" not in tick["gcPreview"]
    assert "candidates" not in tick["gcPreview"]
    assert "protected" not in tick["gcPreview"]
    assert "storageUri" not in repr(tick)
    assert "groupId" not in repr(tick)
    assert "path" not in repr(tick)
    assert artifact_path.is_file()
    assert fetched["lifecycleState"] == "active"
    assert fetched["deletedAt"] is None
    assert evidence[-1]["eventType"] == ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE
    assert evidence[-1]["payload"]["deleteConfirmationRequired"] is True
    assert evidence[-1]["payload"]["policyDecision"]["deletionAuthorized"] is False
    assert evidence[-1]["payload"]["batchSafety"]["candidateArtifactCount"] == 1
    assert evidence[-1]["payload"]["gcPreview"]["planFingerprint"] == tick["gcPreview"]["planFingerprint"]
    assert "candidateGroupIds" not in repr(evidence[-1]["payload"])
    assert "storageUri" not in repr(evidence[-1]["payload"])
    assert "path" not in repr(evidence[-1]["payload"])
    assert gc_evidence == []
    assert governance[-1]["actor"] == "artifact-supervisor"
    assert governance[-1]["details"]["planId"] == tick["gcPreview"]["planId"]
    assert governance[-1]["details"]["planFingerprint"] == tick["gcPreview"]["planFingerprint"]
    assert governance[-1]["details"]["deleteConfirmationRequired"] is True
    assert governance[-1]["details"]["policyDecision"] == "preview_ready"
    assert governance[-1]["details"]["batchLimitApplied"] is False


def test_artifact_lifecycle_controller_run_once_route_returns_safe_preview_only_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    artifact = _persist_managed_artifact(cfg, "run_gc_controller_route", status="completed")
    artifact_path = Path(artifact["path"])
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/controller/run-once",
        json={
            "confirmation": "run-artifact-lifecycle-controller-once",
            "retentionDays": 30,
            "eligibleRunStatuses": ["completed", "failed", "canceled", "cancelled"],
            "quotaBytes": 0,
            "maxDeleteBytesPerTick": 4096,
            "actor": "operator@example.test",
            "reason": "controller-run-once",
        },
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 202
    data = response.json()["data"]
    fetched = fetch_run_results(cfg, "run_gc_controller_route")["artifacts"][0]
    governance = list_governance_audit_events(
        cfg,
        subject_kind="artifact_lifecycle_controller",
        subject_id=data["tickId"],
        action="artifact.lifecycle.controller.run_once",
    )["items"]
    assert data["schemaVersion"] == "h2ometa.artifact-lifecycle-controller-run-once-result.v1"
    assert data["executionMode"] == "preview-only"
    assert data["deleteConfirmationRequired"] is True
    assert data["deleteExecutionAuthorized"] is False
    assert data["controlsExposed"] is False
    assert data["gcPreview"]["candidateCount"] == 1
    assert data["gcPreview"]["deleteBytes"] == artifact["sizeBytes"]
    assert data["policyDecision"]["deletionAuthorized"] is False
    assert fetched["lifecycleState"] == "active"
    assert artifact_path.is_file()
    assert governance[-1]["details"]["deleteExecutionAuthorized"] is False
    assert governance[-1]["details"]["controlsExposed"] is False
    _assert_no_artifact_lifecycle_controller_public_leak(data, artifact)
    _assert_no_artifact_lifecycle_controller_public_leak(governance[-1]["details"], artifact)


def test_artifact_lifecycle_controller_run_once_rejects_missing_plan_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    def fake_controller_tick(_cfg, *, payload):
        return {
            "tickId": "alct_missing_fingerprint",
            "evidenceId": "evt_missing_fingerprint",
            "evaluatedAt": "2099-01-01T00:00:00Z",
            "policy": {
                "retentionDays": int(payload["retentionDays"]),
                "eligibleRunStatuses": list(payload["eligibleRunStatuses"]),
            },
            "usage": {
                "activeBytes": 0,
                "activeStorageObjectCount": 0,
                "quotaOverageBytes": 0,
            },
            "policyDecision": {
                "decision": "preview_ready",
                "reasonCode": "DELETE_CONFIRMATION_REQUIRED",
                "deletionAuthorized": False,
                "deleteConfirmationRequired": True,
                "candidateCount": 1,
                "deleteBytes": 25,
            },
            "retentionHolds": {
                "schemaVersion": "artifact-retention-hold-summary.v1",
                "protectedGroupCount": 0,
                "protectedBytes": 0,
                "reasonCount": 0,
                "reasons": [],
            },
            "batchSafety": {
                "schemaVersion": "artifact-gc-batch-safety.v1",
                "maxDeleteBytes": None,
                "maxDeleteBytesApplied": False,
                "candidateCount": 1,
                "candidateBytes": 25,
                "candidateArtifactCount": 1,
                "candidateRunCount": 1,
                "limitedGroupCount": 0,
                "limitedBytes": 0,
            },
            "gcPreview": {
                "planId": "agc_missing_fingerprint",
                "candidateCount": 1,
                "deleteBytes": 25,
                "protectedCount": 0,
                "protectedBytes": 0,
                "candidateArtifactCount": 1,
                "candidateRunCount": 1,
            },
        }

    monkeypatch.setattr(
        controller_control,
        "run_artifact_lifecycle_controller_once",
        fake_controller_tick,
    )
    request = ArtifactLifecycleControllerRunOnceRequest.model_validate(
        {
            "confirmation": "run-artifact-lifecycle-controller-once",
            "retentionDays": 30,
            "eligibleRunStatuses": ["completed"],
            "actor": "operator@example.test",
            "reason": "controller-run-once",
        }
    )

    with pytest.raises(
        ValueError,
        match="ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_FINGERPRINT_REQUIRED",
    ):
        controller_control.run_governed_artifact_lifecycle_controller_once(cfg, request)

    governance = list_governance_audit_events(
        cfg,
        subject_kind="artifact_lifecycle_controller",
        subject_id="alct_missing_fingerprint",
        action="artifact.lifecycle.controller.run_once",
    )["items"]
    assert governance == []


def test_artifact_lifecycle_controller_quota_overage_does_not_broaden_gc_eligibility(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    active = _persist_managed_artifact(cfg, "run_gc_controller_active", status="running")

    tick = evaluate_artifact_lifecycle_controller_tick(
        cfg,
        {
            "retentionDays": 30,
            "eligibleRunStatuses": ["completed", "failed", "canceled", "cancelled"],
            "quotaBytes": 0,
            "actor": "artifact-supervisor",
            "reason": "controller-preview",
        },
    )

    assert tick["quotaOverageBytes"] == active["sizeBytes"]
    assert tick["wouldDeleteCount"] == 0
    assert tick["policyDecision"]["decision"] == "no_action"
    assert tick["policyDecision"]["reasonCode"] == "NO_ELIGIBLE_CANDIDATES"
    run_not_terminal = next(item for item in tick["retentionHolds"]["reasons"] if item["reason"] == "run_not_terminal")
    assert run_not_terminal == {
        "reason": "run_not_terminal",
        "groupCount": 1,
        "artifactCount": 1,
        "runCount": 1,
        "bytes": active["sizeBytes"],
    }
    assert tick["gcPreview"]["candidateCount"] == 0
    assert tick["gcPreview"]["deleteBytes"] == 0
    assert tick["gcPreview"]["protectedCount"] >= 1
    assert "protected" not in tick["gcPreview"]


def test_artifact_lifecycle_controller_summarizes_batch_safety_without_group_ids(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    first = _persist_managed_artifact(cfg, "run_gc_batch_first", status="completed")
    second = _persist_managed_artifact(cfg, "run_gc_batch_second", status="completed")

    tick = evaluate_artifact_lifecycle_controller_tick(
        cfg,
        {
            "retentionDays": 30,
            "eligibleRunStatuses": ["completed", "failed", "canceled", "cancelled"],
            "quotaBytes": 0,
            "maxDeleteBytesPerTick": first["sizeBytes"],
            "actor": "artifact-supervisor",
            "reason": "controller-preview",
        },
    )
    evidence = list_evidence_events(
        cfg,
        subject_kind="artifact_lifecycle_controller",
        subject_id=tick["tickId"],
        event_type=ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
    )

    assert tick["batchSafety"]["maxDeleteBytesApplied"] is True
    assert tick["batchSafety"]["candidateCount"] == 1
    assert tick["batchSafety"]["candidateArtifactCount"] == 1
    assert tick["batchSafety"]["limitedGroupCount"] == 1
    assert tick["batchSafety"]["limitedBytes"] == second["sizeBytes"]
    hold = next(item for item in tick["retentionHolds"]["reasons"] if item["reason"] == "max_delete_bytes")
    assert hold == {
        "reason": "max_delete_bytes",
        "groupCount": 1,
        "artifactCount": 1,
        "runCount": 1,
        "bytes": second["sizeBytes"],
    }
    assert "candidateGroupIds" not in repr(tick)
    assert "candidateGroupIds" not in repr(evidence[-1]["payload"])
    assert "storageUri" not in repr(evidence[-1]["payload"])
    assert "path" not in repr(evidence[-1]["payload"])


def test_artifact_gc_run_deletes_local_payload_and_records_tombstone_evidence_and_audit(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_delete", status="completed")
    artifact_path = Path(artifact["path"])

    with pytest.raises(ValueError, match="ARTIFACT_GC_CONFIRMATION_REQUIRED"):
        run_artifact_gc(cfg)

    result = run_artifact_gc(
        cfg,
        _confirmed_gc_payload(
            cfg,
            {
                "actor": "operator@example.test",
            },
        ),
    )
    fetched = fetch_run_results(cfg, "run_gc_delete")["artifacts"][0]
    audit = build_result_artifact_audit(cfg, "res_run_gc_delete")
    evidence = list_evidence_events(
        cfg,
        subject_kind="artifact_gc",
        subject_id=result["planId"],
        event_type="artifact.gc.v1",
    )
    governance = list_governance_audit_events(cfg, subject_kind="artifact_gc", subject_id=result["planId"])["items"]

    assert result["status"] == "completed"
    assert result["deletedCount"] == 1
    assert artifact_path.exists() is False
    assert fetched["lifecycleState"] == "deleted"
    assert fetched["deletedAt"] == result["executedAt"]
    assert fetched["gcReason"] == "retention_expired"
    assert audit["status"] == "failed"
    assert audit["artifacts"][0]["status"] == "deleted"
    assert evidence[-1]["eventType"] == "artifact.gc.v1"
    assert evidence[-1]["payload"]["deleted"][0]["artifactIds"] == [artifact["artifactId"]]
    assert governance[-1]["action"] == "artifact.gc.run"
    assert governance[-1]["details"]["deletedCount"] == 1


def test_artifact_gc_run_records_quota_pressure_reason(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _persist_managed_artifact(cfg, "run_gc_quota_delete", status="completed")

    result = run_artifact_gc(
        cfg,
        _confirmed_gc_payload(
            cfg,
            _inline_policy_payload(
                retention_days=5000,
                quota_bytes=0,
                reason="operator-retention",
            ),
        ),
    )

    fetched = fetch_run_results(cfg, "run_gc_quota_delete")["artifacts"][0]
    assert result["deleted"][0]["reason"] == "quota_pressure"
    assert fetched["lifecycleState"] == "deleted"
    assert fetched["gcReason"] == "quota_pressure"


def test_artifact_gc_run_requires_current_plan_fingerprint(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_fingerprint", status="completed")
    artifact_path = Path(artifact["path"])
    preview = preview_artifact_gc(cfg)

    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_REQUIRED"):
        run_artifact_gc(
            cfg,
            {
                "confirmation": ARTIFACT_GC_CONFIRMATION,
            },
        )
    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_artifact_gc(
            cfg,
            {
                "confirmation": ARTIFACT_GC_CONFIRMATION,
                "planFingerprint": "agcfp_" + "0" * 64,
            },
        )
    denies = list_governance_audit_events(cfg, action="artifact.gc.run")["items"]
    assert artifact_path.exists() is True
    result = run_artifact_gc(
        cfg,
        {
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "planFingerprint": preview["planFingerprint"],
        },
    )
    fetched = fetch_run_results(cfg, "run_gc_fingerprint")["artifacts"][0]

    assert artifact_path.exists() is False
    assert fetched["lifecycleState"] == "deleted"
    assert result["deletedCount"] == 1
    assert denies[-2]["reasonCode"] == "ARTIFACT_GC_PLAN_FINGERPRINT_REQUIRED"
    assert denies[-2]["details"]["deletedCount"] == 0
    assert denies[-2]["details"]["fingerprintProvided"] is False
    assert denies[-1]["reasonCode"] == "ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"
    assert denies[-1]["details"]["deletedCount"] == 0
    assert denies[-1]["details"]["fingerprintProvided"] is True


def test_artifact_gc_plan_fingerprint_is_stable_and_rejects_stale_candidates(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    first = _persist_managed_artifact(cfg, "run_gc_fingerprint_first", status="completed")
    first_path = Path(first["path"])
    first_preview = preview_artifact_gc(cfg)
    second_preview = preview_artifact_gc(cfg)

    assert first_preview["planId"]
    assert second_preview["planId"]
    assert second_preview["planFingerprint"] == first_preview["planFingerprint"]

    second = _persist_managed_artifact(cfg, "run_gc_fingerprint_second", status="completed")
    second_path = Path(second["path"])
    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_artifact_gc(
            cfg,
            {
                "confirmation": ARTIFACT_GC_CONFIRMATION,
                "planFingerprint": first_preview["planFingerprint"],
            },
        )
    denial = list_governance_audit_events(cfg, action="artifact.gc.run")["items"][-1]
    assert first_path.is_file()
    assert second_path.is_file()
    assert denial["reasonCode"] == "ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"
    assert denial["details"]["deletedCount"] == 0

    current_preview = preview_artifact_gc(cfg)
    result = run_artifact_gc(
        cfg,
        {
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "planFingerprint": current_preview["planFingerprint"],
        },
    )

    assert result["deletedCount"] == 2
    assert first_path.exists() is False
    assert second_path.exists() is False


def test_artifact_gc_plan_fingerprint_rejects_policy_changes(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_fingerprint_policy", status="completed")
    artifact_path = Path(artifact["path"])
    preview_payload = _inline_policy_payload(retention_days=30, reason="operator-preview")
    preview = preview_artifact_gc(cfg, preview_payload)

    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_artifact_gc(
            cfg,
            {
                **_inline_policy_payload(retention_days=31, reason="operator-preview"),
                "confirmation": ARTIFACT_GC_CONFIRMATION,
                "planFingerprint": preview["planFingerprint"],
            },
        )
    with pytest.raises(ValueError, match="ARTIFACT_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_artifact_gc(
            cfg,
            {
                **_inline_policy_payload(retention_days=30, reason="operator-run"),
                "confirmation": ARTIFACT_GC_CONFIRMATION,
                "planFingerprint": preview["planFingerprint"],
            },
        )
    fetched = fetch_run_results(cfg, "run_gc_fingerprint_policy")["artifacts"][0]

    assert artifact_path.is_file()
    assert fetched["lifecycleState"] == "active"


def test_artifact_gc_run_removes_managed_s3_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = make_configured_remote_runner(tmp_path)
    cfg.artifact_storage_backend = "s3"
    cfg.artifact_s3_endpoint = "minio.local:9000"
    cfg.artifact_s3_bucket = "h2ometa-artifacts"
    cfg.artifact_s3_access_key = "access"
    cfg.artifact_s3_secret_key = "secret"
    cfg.artifact_s3_prefix = "tenant-a"
    artifact = _persist_managed_artifact(cfg, "run_gc_s3", status="failed")
    bucket, object_name = _bucket_and_object(artifact["storageUri"])

    result = run_artifact_gc(
        cfg,
        _confirmed_gc_payload(cfg, {}),
    )
    fetched = fetch_run_results(cfg, "run_gc_s3")["artifacts"][0]

    assert result["deletedCount"] == 1
    assert fake.removed == [(bucket, object_name)]
    assert (bucket, object_name) not in fake.objects
    assert fetched["lifecycleState"] == "deleted"


def test_artifact_gc_run_removes_managed_s3_directory_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = make_configured_remote_runner(tmp_path)
    cfg.artifact_storage_backend = "s3"
    cfg.artifact_s3_endpoint = "minio.local:9000"
    cfg.artifact_s3_bucket = "h2ometa-artifacts"
    cfg.artifact_s3_access_key = "access"
    cfg.artifact_s3_secret_key = "secret"
    cfg.artifact_s3_prefix = "tenant-a"
    _create_run(cfg, "run_gc_s3_dir", status="failed")
    artifact_dir = Path(cfg.results_dir) / "run_gc_s3_dir" / "directory-report"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "report.txt").write_bytes(b"directory payload\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_gc_s3_dir",
        kind="directory",
        path=artifact_dir,
        mime_type="inode/directory",
        artifact_key="report",
    )
    bucket, object_name = _bucket_and_object(artifact["storageUri"])

    result = run_artifact_gc(
        cfg,
        _confirmed_gc_payload(cfg, {}),
    )
    fetched = fetch_run_results(cfg, "run_gc_s3_dir")["artifacts"][0]

    assert result["deletedCount"] == 1
    assert fake.removed == [(bucket, object_name)]
    assert (bucket, object_name) not in fake.objects
    assert fetched["lifecycleState"] == "deleted"


def test_artifact_gc_preview_protects_unmanaged_local_paths(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_unmanaged", status="completed")
    unmanaged = tmp_path / "outside-managed.txt"
    unmanaged.write_text("outside\n", encoding="utf-8")
    artifact = persist_artifact(
        cfg,
        run_id="run_unmanaged",
        kind="report",
        path=unmanaged,
        mime_type="text/plain",
        artifact_key="report",
    )

    plan = preview_artifact_gc(cfg)

    assert plan["candidateCount"] == 0
    assert plan["protected"][0]["artifactIds"] == [artifact["artifactId"]]
    assert "unmanaged_local_path" in plan["protected"][0]["reasons"]


def _persist_managed_artifact(cfg, run_id: str, *, status: str) -> dict[str, Any]:
    _create_run(cfg, run_id, status=status)
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    report = result_dir / "report.txt"
    report.write_text(f"{run_id}\n", encoding="utf-8")
    return persist_artifact(
        cfg,
        run_id=run_id,
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )


def _confirmed_gc_payload(cfg, payload: dict[str, Any]) -> dict[str, Any]:
    plan = preview_artifact_gc(cfg, payload)
    return {
        **payload,
        "confirmation": ARTIFACT_GC_CONFIRMATION,
        "planFingerprint": plan["planFingerprint"],
    }


def _inline_policy_payload(
    *,
    retention_days: int = 30,
    reason: str = "retention_expired",
    eligible_run_statuses: list[str] | None = None,
    quota_bytes: int | None = None,
    max_delete_bytes: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "retentionDays": retention_days,
        "eligibleRunStatuses": eligible_run_statuses or ["completed", "failed", "canceled", "cancelled"],
        "reason": reason,
    }
    if quota_bytes is not None:
        payload["quotaBytes"] = quota_bytes
    if max_delete_bytes is not None:
        payload["maxDeleteBytesPerTick"] = max_delete_bytes
        payload["maxDeleteBytes"] = max_delete_bytes
    normalized = normalize_artifact_lifecycle_policy_payload(payload)
    return {
        **payload,
        "policyId": "request",
        "policyVersion": 0,
        "policyFingerprint": artifact_lifecycle_policy_fingerprint(normalized),
    }


def _create_run(cfg, run_id: str, *, status: str) -> None:
    revision = _create_revision(cfg, run_id)
    create_run_record(
        cfg,
        server_id="srv_artifact_gc",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact_gc",
            "pipelineId": "pipeline_artifact_gc",
            "pipelineVersion": "0.1.0",
            "workflowRevisionId": revision["workflowRevisionId"],
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    terminal = status in {"completed", "failed", "canceled", "cancelled"}
    job_state = "completed" if status == "completed" else "failed" if status == "failed" else "cancelled"
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = ?,
                stage = ?,
                finished_at = ?,
                last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                status,
                "complete" if terminal else "execute",
                "2025-01-01T00:00:00Z" if terminal else None,
                "2025-01-01T00:00:00Z",
                run_id,
            ),
        )
        if terminal:
            connection.execute(
                "UPDATE run_jobs SET state = ?, updated_at = ? WHERE run_id = ?",
                (job_state, "2025-01-01T00:00:00Z", run_id),
            )
        connection.commit()


def _create_revision(cfg, run_id: str) -> dict[str, object]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"draft_{run_id}",
        draft_revision=1,
        manifest={
            "files": [{"path": "workflow/Snakefile", "sha256": "a" * 64}],
            "layout": {"snakefile": "workflow/Snakefile"},
        },
        graph_snapshot={"nodes": ["report"], "edges": [], "runSpec": {"runId": run_id}},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa-test", "version": "0.1.0"},
        created_by="pytest",
    )


def _protect_run_as_production_evidence(cfg, run_id: str) -> None:
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::gc-protected",
            "name": "gc-protected",
            "source": "conda-forge",
            "packageSpec": "conda-forge::gc-protected=1.0",
            "contractStatus": {
                "production": {
                    "status": "passed",
                    "runId": run_id,
                    "evidenceId": "evid_gc_protected",
                }
            },
        },
    )
    with get_connection(cfg) as connection:
        contract = {"production": {"status": "passed", "runId": run_id, "evidenceId": "evid_gc_protected"}}
        connection.execute(
            "UPDATE tools SET contract_status_json = ? WHERE tool_id = ?",
            (json.dumps(contract), "conda-forge::gc-protected"),
        )
        connection.commit()


def _assert_no_artifact_lifecycle_controller_public_leak(
    payload: dict[str, Any],
    artifact: dict[str, Any],
) -> None:
    encoded = json.dumps(payload, sort_keys=True)
    forbidden_values = {
        artifact["artifactId"],
        artifact["path"],
        artifact["storageUri"],
        artifact["sha256"],
        "run_gc_controller_route",
    }
    forbidden_tokens = {
        "artifactIds",
        "runIds",
        "storageUri",
        "localPath",
        "path",
        "sha256",
    }
    for value in forbidden_values:
        assert str(value) not in encoded
    for token in forbidden_tokens:
        assert f'"{token}"' not in encoded


def _bucket_and_object(storage_uri: str) -> tuple[str, str]:
    value = storage_uri.removeprefix("s3://")
    bucket, object_name = value.split("/", 1)
    return bucket, object_name
