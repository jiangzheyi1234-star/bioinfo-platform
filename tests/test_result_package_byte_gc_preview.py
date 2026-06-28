from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.result_package_byte_gc_preview_service import preview_result_package_byte_gc
from apps.remote_runner.result_package_byte_gc_run_service import (
    RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
    run_result_package_byte_gc,
)
from apps.remote_runner.result_package_byte_gc_service import delete_result_package_byte_gc_candidate
from apps.remote_runner.result_package_lifecycle_service import retire_result_package_export
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_package_byte_gc_preview_candidates_are_public_and_fingerprinted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("artifact-curator", "auditor"))
    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_preview_service._utc_now",
        lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    package = _retired_package(cfg, "run_byte_gc_preview_candidate", retired_at="2025-01-01T00:00:00Z")

    plan = preview_result_package_byte_gc(
        cfg,
        {
            "retentionDays": 30,
            "actor": "operator",
            "reason": (
                f"quota {package['packageExportId']} "
                f"{package['packagePath']} {package['sha256']}"
            ),
        },
    )
    repeated = preview_result_package_byte_gc(
        cfg,
        {
            "retentionDays": 30,
            "actor": "operator",
            "reason": (
                f"quota {package['packageExportId']} "
                f"{package['packagePath']} {package['sha256']}"
            ),
        },
    )
    audit = list_governance_audit_events(cfg, action="result.package.bytes.preview")["items"][-1]

    assert plan["schemaVersion"] == "h2ometa.result-package-byte-gc-preview.v1"
    assert plan["cutoffAt"] == "2025-12-02T00:00:00Z"
    assert plan["planFingerprint"].startswith("rpbgcfp_")
    assert plan["planFingerprint"] == repeated["planFingerprint"]
    assert plan["candidateCount"] == 1
    assert plan["protectedCount"] == 0
    assert plan["deleteBytes"] == package["sizeBytes"]
    assert plan["reasonCounts"] == {"retired_bytes_eligible": 1}
    assert "reason" not in plan["policy"]
    assert plan["policy"]["reasonProvided"] is True
    assert plan["policy"]["reasonRedacted"] is True
    assert plan["policy"]["deletionAuthorized"] is False
    assert plan["policy"]["deleteConfirmationAccepted"] is False
    assert plan["redactionPolicy"] == {
        "packageExportIdsExposed": False,
        "resultIdsExposed": False,
        "runIdsExposed": False,
        "pathsExposed": False,
        "storageUrisExposed": False,
        "sha256Exposed": False,
    }
    assert plan["candidates"] == [
        {
            "itemIndex": 0,
            "classification": "candidate",
            "reason": "retired_bytes_eligible",
            "artifactPayloadMode": "included",
            "lifecycleState": "retired",
            "packageBytesState": "available",
            "sizeBytes": package["sizeBytes"],
            "retiredAtPresent": True,
            "checksumVerified": True,
        }
    ]
    _assert_no_raw_export_identity(plan, package)
    assert audit["actor"] == "operator"
    assert audit["details"]["planFingerprint"] == plan["planFingerprint"]
    assert audit["details"]["candidateCount"] == 1
    _assert_no_raw_export_identity(audit, package)


def test_result_package_byte_gc_preview_protects_unsafe_or_ineligible_exports(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    active = _active_package(cfg, "run_byte_gc_preview_active")
    missing_retired_at = _retired_package(
        cfg,
        "run_byte_gc_preview_missing_retired_at",
        retired_at=None,
    )
    deleted = _retired_package(cfg, "run_byte_gc_preview_deleted", retired_at="2025-01-01T00:00:00Z")
    delete_result_package_byte_gc_candidate(
        cfg,
        "res_run_byte_gc_preview_deleted",
        deleted["packageExportId"],
        plan_fingerprint="rpbgcfp_test",
    )
    deleting = _retired_package(cfg, "run_byte_gc_preview_deleting", retired_at="2025-01-01T00:00:00Z")
    unmanaged = _retired_package(cfg, "run_byte_gc_preview_unmanaged", retired_at="2025-01-01T00:00:00Z")
    missing_file = _retired_package(cfg, "run_byte_gc_preview_missing_file", retired_at="2025-01-01T00:00:00Z")
    size_drift = _retired_package(cfg, "run_byte_gc_preview_size_drift", retired_at="2025-01-01T00:00:00Z")
    checksum_drift = _retired_package(
        cfg,
        "run_byte_gc_preview_checksum_drift",
        retired_at="2025-01-01T00:00:00Z",
    )
    recent = _retired_package(cfg, "run_byte_gc_preview_recent", retired_at="2099-01-01T00:00:00Z")

    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET package_bytes_state = 'deleting' WHERE package_export_id = ?",
            (deleting["packageExportId"],),
        )
        outside_path = tmp_path / "outside" / "package.zip"
        outside_path.parent.mkdir(parents=True)
        outside_path.write_bytes(Path(str(unmanaged["packagePath"])).read_bytes())
        connection.execute(
            "UPDATE result_package_exports SET package_path = ? WHERE package_export_id = ?",
            (str(outside_path), unmanaged["packageExportId"]),
        )
        connection.commit()
    Path(str(missing_file["packagePath"])).unlink()
    Path(str(size_drift["packagePath"])).write_bytes(b"short")
    checksum_path = Path(str(checksum_drift["packagePath"]))
    checksum_path.write_bytes(b"x" * int(checksum_drift["sizeBytes"]))

    plan = preview_result_package_byte_gc(cfg, {"retentionDays": 30, "scanLimit": 20})

    assert plan["candidateCount"] == 0
    assert plan["protectedCount"] == 9
    assert plan["reasonCounts"] == {
        "bytes_deleted": 1,
        "bytes_deleting": 1,
        "lifecycle_active": 1,
        "package_checksum_mismatch": 1,
        "package_file_missing": 1,
        "package_path_unmanaged": 1,
        "package_size_mismatch": 1,
        "retention_window_active": 1,
        "retired_time_missing": 1,
    }
    for package in (
        active,
        missing_retired_at,
        deleted,
        deleting,
        unmanaged,
        missing_file,
        size_drift,
        checksum_drift,
        recent,
    ):
        _assert_no_raw_export_identity(plan, package)


def test_result_package_byte_gc_preview_honors_max_delete_bytes_without_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    first = _retired_package(cfg, "run_byte_gc_preview_limit_first", retired_at="2025-01-01T00:00:00Z")
    second = _retired_package(cfg, "run_byte_gc_preview_limit_second", retired_at="2025-01-02T00:00:00Z")

    plan = preview_result_package_byte_gc(
        cfg,
        {"retentionDays": 30, "maxDeleteBytes": first["sizeBytes"]},
    )

    assert plan["candidateCount"] == 1
    assert plan["deleteBytes"] == first["sizeBytes"]
    assert plan["protectedCount"] == 1
    assert plan["reasonCounts"] == {
        "max_delete_bytes_limited": 1,
        "retired_bytes_eligible": 1,
    }
    assert Path(str(first["packagePath"])).is_file()
    assert Path(str(second["packagePath"])).is_file()
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT package_export_id, lifecycle_state, package_bytes_state
            FROM result_package_exports
            WHERE package_export_id IN (?, ?)
            """,
            (first["packageExportId"], second["packageExportId"]),
        ).fetchall()
    states = {row["package_export_id"]: dict(row) for row in rows}
    assert states[first["packageExportId"]]["lifecycle_state"] == "retired"
    assert states[first["packageExportId"]]["package_bytes_state"] == "available"
    assert states[second["packageExportId"]]["lifecycle_state"] == "retired"
    assert states[second["packageExportId"]]["package_bytes_state"] == "available"


def test_result_package_byte_gc_preview_fingerprint_excludes_wall_clock_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _retired_package(cfg, "run_byte_gc_preview_time_stable", retired_at="2025-01-01T00:00:00Z")
    clock = iter(
        [
            datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_preview_service._utc_now",
        lambda: next(clock),
    )

    first = preview_result_package_byte_gc(cfg, {"retentionDays": 30})
    second = preview_result_package_byte_gc(cfg, {"retentionDays": 30})

    assert first["cutoffAt"] != second["cutoffAt"]
    assert first["planFingerprint"] == second["planFingerprint"]


def test_result_package_byte_gc_run_requires_current_fingerprint_and_deletes_candidates(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("artifact-curator",))
    package = _retired_package(cfg, "run_byte_gc_run_candidate", retired_at="2025-01-01T00:00:00Z")
    package_path = Path(str(package["packagePath"]))
    reason = f"quota {package['packagePath']} {package['sha256']}"
    preview = preview_result_package_byte_gc(
        cfg,
        {"retentionDays": 30, "actor": "operator", "reason": reason},
    )

    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_REQUIRED"):
        run_result_package_byte_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
                "actor": "operator",
            },
        )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_result_package_byte_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
                "planFingerprint": "stale",
                "actor": "operator",
            },
        )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION_REQUIRED"):
        run_result_package_byte_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": "delete-package-bytes",
                "planFingerprint": preview["planFingerprint"],
                "actor": "operator",
                "reason": reason,
            },
        )
    denials = list_governance_audit_events(cfg, action="result.package.bytes.run")["items"]

    result = run_result_package_byte_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
            "planFingerprint": preview["planFingerprint"],
            "actor": "operator",
            "reason": reason,
        },
    )
    audit = list_governance_audit_events(cfg, action="result.package.bytes.run")["items"][-1]
    evidence = list_evidence_events(
        cfg,
        subject_kind="result_package_export",
        subject_id="byte-gc-run",
        event_type="result.package.bytes.gc.run.v1",
    )[-1]

    assert package_path.exists() is False
    assert result["schemaVersion"] == "h2ometa.result-package-byte-gc-run.v1"
    assert result["status"] == "completed"
    assert result["deletedCount"] == 1
    assert result["deletedBytes"] == package["sizeBytes"]
    assert result["deleteConfirmationAccepted"] is True
    assert result["plan"]["planFingerprint"] == preview["planFingerprint"]
    assert result["deleted"][0]["packageBytesState"] == "deleted"
    assert result["deleted"][0]["packageFileDeleted"] is True
    assert result["deleted"][0]["checksumVerified"] is True
    with get_connection(cfg) as connection:
        state = connection.execute(
            "SELECT package_bytes_state FROM result_package_exports WHERE package_export_id = ?",
            (package["packageExportId"],),
        ).fetchone()["package_bytes_state"]
    assert state == "deleted"
    assert denials[-3]["reasonCode"] == "RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_REQUIRED"
    assert denials[-3]["details"]["deletedCount"] == 0
    assert denials[-2]["reasonCode"] == "RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH"
    assert denials[-2]["details"]["fingerprintProvided"] is True
    assert denials[-1]["reasonCode"] == "RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION_REQUIRED"
    assert denials[-1]["details"]["fingerprintProvided"] is True
    assert audit["decision"] == "allow"
    assert audit["details"]["deletedCount"] == 1
    assert audit["details"]["planFingerprint"] == preview["planFingerprint"]
    assert evidence["payload"]["reasonRedacted"] is True
    assert evidence["payload"]["deletedCount"] == 1
    _assert_no_raw_export_identity(result, package)
    _assert_no_raw_export_identity(audit, package)
    _assert_no_raw_export_identity(evidence, package)


def test_result_package_byte_gc_run_rejects_stale_candidate_set(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    first = _retired_package(cfg, "run_byte_gc_run_stale_first", retired_at="2025-01-01T00:00:00Z")
    first_path = Path(str(first["packagePath"]))
    preview = preview_result_package_byte_gc(cfg, {"retentionDays": 30})
    second = _retired_package(cfg, "run_byte_gc_run_stale_second", retired_at="2025-01-02T00:00:00Z")
    second_path = Path(str(second["packagePath"]))

    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH"):
        run_result_package_byte_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
                "planFingerprint": preview["planFingerprint"],
            },
        )
    denial = list_governance_audit_events(cfg, action="result.package.bytes.run")["items"][-1]
    current = preview_result_package_byte_gc(cfg, {"retentionDays": 30})
    result = run_result_package_byte_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
            "planFingerprint": current["planFingerprint"],
        },
    )

    assert first_path.exists() is False
    assert second_path.exists() is False
    assert result["deletedCount"] == 2
    assert denial["reasonCode"] == "RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH"
    assert denial["details"]["deletedCount"] == 0


def test_result_package_byte_gc_run_delete_error_is_stable_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_byte_gc_run_error", retired_at="2025-01-01T00:00:00Z")
    preview = preview_result_package_byte_gc(cfg, {"retentionDays": 30})

    def fail_delete(*_args, **_kwargs):
        raise ValueError(f"RESULT_PACKAGE_CHECKSUM_MISMATCH: {package['packagePath']}")

    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_run_service.delete_result_package_byte_gc_candidate",
        fail_delete,
    )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_RUN_DELETE_FAILED"):
        run_result_package_byte_gc(
            cfg,
            {
                "retentionDays": 30,
                "confirmation": RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION,
                "planFingerprint": preview["planFingerprint"],
            },
        )
    audit = list_governance_audit_events(cfg, action="result.package.bytes.run")["items"][-1]
    evidence = list_evidence_events(
        cfg,
        subject_kind="result_package_export",
        subject_id="byte-gc-run",
        event_type="result.package.bytes.gc.run.v1",
    )[-1]

    assert Path(str(package["packagePath"])).is_file()
    assert audit["decision"] == "error"
    assert audit["details"]["errorCount"] == 1
    assert evidence["payload"]["errors"] == [
        {
            "itemIndex": 0,
            "classification": "error",
            "reason": "delete_failed",
            "errorCode": "RESULT_PACKAGE_CHECKSUM_MISMATCH",
            "artifactPayloadMode": "included",
            "lifecycleState": "retired",
            "packageBytesState": "available",
            "sizeBytes": package["sizeBytes"],
        }
    ]
    _assert_no_raw_export_identity(audit, package)
    _assert_no_raw_export_identity(evidence, package)


def _active_package(cfg: Any, run_id: str) -> dict[str, Any]:
    _create_exportable_result(cfg, run_id)
    return export_result_package(cfg, f"res_{run_id}", include_artifacts=True)


def _retired_package(cfg: Any, run_id: str, *, retired_at: str | None) -> dict[str, Any]:
    package = _active_package(cfg, run_id)
    retire_result_package_export(
        cfg,
        f"res_{run_id}",
        package["packageExportId"],
        confirmation="retire-result-package-export",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET retired_at = ? WHERE package_export_id = ?",
            (retired_at, package["packageExportId"]),
        )
        connection.commit()
    return package


def _create_exportable_result(cfg: Any, run_id: str) -> dict[str, object]:
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


def _assert_no_raw_export_identity(container: object, package: dict[str, Any]) -> None:
    rendered = repr(container)
    forbidden = {
        str(package["packageExportId"]),
        str(package["resultId"]),
        str(package["runId"]),
        str(package["packagePath"]),
        str(package["packageUri"]),
        str(package["sha256"]),
    }
    for value in forbidden:
        assert value not in rendered
