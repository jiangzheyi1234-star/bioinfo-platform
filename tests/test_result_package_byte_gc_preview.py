from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.result_package_byte_gc_preview_service import preview_result_package_byte_gc
from apps.remote_runner.result_package_byte_gc_service import delete_retired_result_package_bytes
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
    delete_retired_result_package_bytes(
        cfg,
        "res_run_byte_gc_preview_deleted",
        deleted["packageExportId"],
        confirmation="delete-result-package-export-bytes",
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
