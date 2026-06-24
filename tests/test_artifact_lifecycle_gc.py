from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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
from apps.remote_runner.artifact_product_service import build_result_artifact_audit, export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
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
    plan = preview_artifact_gc(cfg, {"retentionDays": 30})

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


def test_artifact_lifecycle_controller_tick_previews_without_deleting_payloads(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_controller", status="completed")
    artifact_path = Path(artifact["path"])

    tick = evaluate_artifact_lifecycle_controller_tick(
        cfg,
        {
            "retentionDays": 30,
            "quotaBytes": 0,
            "actor": "artifact-supervisor",
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
    assert tick["gcPreview"]["candidates"][0]["artifactIds"] == [artifact["artifactId"]]
    assert artifact_path.is_file()
    assert fetched["lifecycleState"] == "active"
    assert fetched["deletedAt"] is None
    assert evidence[-1]["eventType"] == ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE
    assert evidence[-1]["payload"]["deleteConfirmationRequired"] is True
    assert "storageUri" not in repr(evidence[-1]["payload"])
    assert "path" not in repr(evidence[-1]["payload"])
    assert gc_evidence == []
    assert governance[-1]["actor"] == "artifact-supervisor"
    assert governance[-1]["details"]["planId"] == tick["gcPreview"]["planId"]
    assert governance[-1]["details"]["deleteConfirmationRequired"] is True


def test_artifact_lifecycle_controller_quota_overage_does_not_broaden_gc_eligibility(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    active = _persist_managed_artifact(cfg, "run_gc_controller_active", status="running")

    tick = evaluate_artifact_lifecycle_controller_tick(
        cfg,
        {
            "retentionDays": 30,
            "quotaBytes": 0,
            "actor": "artifact-supervisor",
        },
    )

    assert tick["quotaOverageBytes"] == active["sizeBytes"]
    assert tick["wouldDeleteCount"] == 0
    assert tick["gcPreview"]["candidateCount"] == 0
    assert tick["gcPreview"]["deleteBytes"] == 0
    assert tick["gcPreview"]["protected"][0]["artifactIds"] == [active["artifactId"]]
    assert "run_not_terminal" in tick["gcPreview"]["protected"][0]["reasons"]


def test_artifact_gc_run_deletes_local_payload_and_records_tombstone_evidence_and_audit(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _persist_managed_artifact(cfg, "run_gc_delete", status="completed")
    artifact_path = Path(artifact["path"])

    with pytest.raises(ValueError, match="ARTIFACT_GC_CONFIRMATION_REQUIRED"):
        run_artifact_gc(cfg, {"retentionDays": 30})

    result = run_artifact_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "actor": "operator@example.test",
        },
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
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "eligibleRunStatuses": ["failed"],
        },
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
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
            "eligibleRunStatuses": ["failed"],
        },
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

    plan = preview_artifact_gc(cfg, {"retentionDays": 30})

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


def _bucket_and_object(storage_uri: str) -> tuple[str, str]:
    value = storage_uri.removeprefix("s3://")
    bucket, object_name = value.split("/", 1)
    return bucket, object_name
