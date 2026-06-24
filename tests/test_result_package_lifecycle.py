from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.artifact_lifecycle_service import preview_artifact_gc
from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.result_package_download_service import build_result_package_download
from apps.remote_runner.result_package_lifecycle_service import retire_result_package_export
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_package_retire_tombstones_record_without_deleting_package(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _create_exportable_result(cfg, "run_retire")
    package = export_result_package(cfg, "res_run_retire", include_artifacts=True)
    package_path = Path(package["packagePath"])

    protected = preview_artifact_gc(cfg, {"retentionDays": 30})
    result = retire_result_package_export(
        cfg,
        "res_run_retire",
        package["packageExportId"],
        confirmation="retire-result-package-export",
        actor="operator",
        reason="superseded package",
    )
    unprotected = preview_artifact_gc(cfg, {"retentionDays": 30})
    evidence = list_evidence_events(
        cfg,
        subject_kind="result_package_export",
        subject_id=package["packageExportId"],
        event_type="result.package.retire.v1",
    )
    audit = list_governance_audit_events(
        cfg,
        action="result.package.retire",
        subject_kind="result_package_export",
        subject_id=package["packageExportId"],
    )["items"]

    assert result["schemaVersion"] == "h2ometa.result-package-retire.v1"
    assert result["lifecycleState"] == "retired"
    assert result["packageFileDeleted"] is False
    assert package_path.is_file()
    with get_connection(cfg) as connection:
        state = connection.execute(
            "SELECT lifecycle_state FROM result_package_exports WHERE package_export_id = ?",
            (package["packageExportId"],),
        ).fetchone()["lifecycle_state"]
    assert state == "retired"
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_ACTIVE: retired"):
        build_result_package_download(
            cfg,
            result_id="res_run_retire",
            package_export_id=package["packageExportId"],
        )
    assert protected["candidateCount"] == 0
    assert protected["protected"][0]["artifactIds"] == [artifact["artifactId"]]
    assert "export_package" in protected["protected"][0]["reasons"]
    assert unprotected["candidateCount"] == 1
    assert unprotected["candidates"][0]["artifactIds"] == [artifact["artifactId"]]
    assert evidence[-1]["payload"]["packageFileDeleted"] is False
    assert "packagePath" not in repr(evidence[-1])
    assert "packageUri" not in repr(evidence[-1])
    assert audit[-1]["details"]["packageFileDeleted"] is False
    assert audit[-1]["details"]["reason"] == "superseded package"
    assert "packagePath" not in repr(audit[-1])
    assert "packageUri" not in repr(audit[-1])


def test_result_package_retire_rejects_bad_confirmation_and_repeat(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_retire_guard")
    package = export_result_package(cfg, "res_run_retire_guard", include_artifacts=False)

    with pytest.raises(ValueError, match="RESULT_PACKAGE_RETIRE_CONFIRMATION_REQUIRED"):
        retire_result_package_export(
            cfg,
            "res_run_retire_guard",
            package["packageExportId"],
            confirmation="delete",
        )

    retire_result_package_export(
        cfg,
        "res_run_retire_guard",
        package["packageExportId"],
        confirmation="retire-result-package-export",
    )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_ACTIVE: retired"):
        retire_result_package_export(
            cfg,
            "res_run_retire_guard",
            package["packageExportId"],
            confirmation="retire-result-package-export",
        )
    with pytest.raises(RuntimeError, match="RESULT_PACKAGE_EXPORT_RECORD_FAILED"):
        export_result_package(cfg, "res_run_retire_guard", include_artifacts=False)


def _create_exportable_result(cfg, run_id: str) -> dict[str, object]:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"draft_{run_id}",
        draft_revision=1,
        manifest={
            "files": [{"path": "workflow/Snakefile", "sha256": "a" * 64}],
            "layout": {"snakefile": "workflow/Snakefile"},
        },
        graph_snapshot={"nodes": ["summarize"], "edges": [], "runSpec": {"runId": run_id}},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa-test", "version": "0.1.0"},
        created_by="pytest",
    )
    create_run_record(
        cfg,
        server_id="srv_result_package",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_result_package",
            "pipelineId": "file-summary-standard-v1",
            "pipelineVersion": "0.1.0",
            "workflowRevisionId": revision["workflowRevisionId"],
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    report = result_dir / "report.txt"
    report.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id=run_id,
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2025-01-01T00:00:00Z',
                last_updated_at = '2025-01-01T00:00:00Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = ? WHERE run_id = ?",
            ("2025-01-01T00:00:00Z", run_id),
        )
        connection.commit()
    return artifact
