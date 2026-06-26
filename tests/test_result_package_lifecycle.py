from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.artifact_lifecycle_service import preview_artifact_gc
from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.result_package_byte_gc_service import delete_retired_result_package_bytes
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
        row = connection.execute(
            "SELECT lifecycle_state, retired_at FROM result_package_exports WHERE package_export_id = ?",
            (package["packageExportId"],),
        ).fetchone()
    assert row["lifecycle_state"] == "retired"
    assert row["retired_at"] == result["retiredAt"]
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
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_ACTIVE: retired"):
        export_result_package(cfg, "res_run_retire_guard", include_artifacts=False)


def test_result_package_byte_delete_removes_only_retired_package_zip(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    artifact = _create_exportable_result(cfg, "run_package_byte_delete")
    package = export_result_package(cfg, "res_run_package_byte_delete", include_artifacts=True)
    package_path = Path(package["packagePath"])
    artifact_path = Path(str(artifact["path"]))

    retire_result_package_export(
        cfg,
        "res_run_package_byte_delete",
        package["packageExportId"],
        confirmation="retire-result-package-export",
        actor="operator",
        reason="superseded package",
    )
    result = delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="operator",
        reason="storage quota",
    )
    evidence = list_evidence_events(
        cfg,
        subject_kind="result_package_export",
        subject_id=package["packageExportId"],
        event_type="result.package.bytes.delete.v1",
    )
    audit = list_governance_audit_events(
        cfg,
        action="result.package.bytes.delete",
        subject_kind="result_package_export",
        subject_id=package["packageExportId"],
    )["items"]

    assert result["schemaVersion"] == "h2ometa.result-package-bytes-delete.v1"
    assert result["lifecycleState"] == "retired"
    assert result["packageBytesState"] == "deleted"
    assert result["packageFileDeleted"] is True
    assert result["deletedBytes"] == package["sizeBytes"]
    assert not package_path.exists()
    assert artifact_path.is_file()
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT lifecycle_state, package_bytes_state, package_bytes_deleted_at,
                   package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert dict(row) == {
        "lifecycle_state": "retired",
        "package_bytes_state": "deleted",
        "package_bytes_deleted_at": result["deletedAt"],
        "package_bytes_gc_reason": "storage quota",
    }
    assert evidence[-1]["payload"]["packageFileDeleted"] is True
    assert evidence[-1]["payload"]["packageBytesState"] == "deleted"
    assert "packagePath" not in repr(evidence[-1])
    assert "packageUri" not in repr(evidence[-1])
    assert audit[-1]["details"]["packageFileDeleted"] is True
    assert audit[-1]["details"]["packageBytesState"] == "deleted"
    assert audit[-1]["details"]["reason"] == "storage quota"
    assert "packagePath" not in repr(audit[-1])
    assert "packageUri" not in repr(audit[-1])


def test_result_package_byte_delete_blocks_reexport_without_recreating_zip(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_byte_delete_no_reexport")
    package = export_result_package(cfg, "res_run_package_byte_delete_no_reexport", include_artifacts=True)
    package_path = Path(package["packagePath"])
    retire_result_package_export(
        cfg,
        "res_run_package_byte_delete_no_reexport",
        package["packageExportId"],
        confirmation="retire-result-package-export",
    )
    delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_no_reexport",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
    )
    before_evidence = list_evidence_events(
        cfg,
        subject_kind="result",
        subject_id="res_run_package_byte_delete_no_reexport",
        event_type="result.export.v1",
    )

    assert not package_path.exists()
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_ACTIVE: retired"):
        export_result_package(cfg, "res_run_package_byte_delete_no_reexport", include_artifacts=True)
    after_evidence = list_evidence_events(
        cfg,
        subject_kind="result",
        subject_id="res_run_package_byte_delete_no_reexport",
        event_type="result.export.v1",
    )

    assert not package_path.exists()
    assert [event["eventId"] for event in after_evidence] == [
        event["eventId"] for event in before_evidence
    ]


def test_result_package_byte_delete_restores_file_when_deleting_state_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_package_byte_delete_state_failure")
    package_path = Path(package["packagePath"])

    def fail_deleting_state(*args, **kwargs):
        raise RuntimeError("forced state failure")

    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_service._mark_result_package_bytes_deleting",
        fail_deleting_state,
    )
    with pytest.raises(RuntimeError, match="forced state failure"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_state_failure",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
            actor="operator",
            reason="quota",
        )

    assert package_path.is_file()
    assert list(package_path.parent.glob(f".{package_path.name}.*.deleting")) == []
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_deleted_at, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert dict(row) == {
        "package_bytes_state": "available",
        "package_bytes_deleted_at": None,
        "package_bytes_gc_reason": "",
    }


def test_result_package_byte_delete_resumes_when_final_evidence_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_package_byte_delete_finalize_failure")
    package_path = Path(package["packagePath"])

    def fail_evidence(*args, **kwargs):
        raise RuntimeError("forced evidence failure")

    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_service.append_evidence_event",
        fail_evidence,
    )
    with pytest.raises(RuntimeError, match="forced evidence failure"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_finalize_failure",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
            actor="operator",
            reason="quota",
        )

    assert not package_path.exists()
    assert list(package_path.parent.glob(f".{package_path.name}.*.deleting")) == []
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_deleted_at, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert row["package_bytes_state"] == "deleting"
    assert row["package_bytes_deleted_at"]
    assert row["package_bytes_gc_reason"] == "quota"

    monkeypatch.undo()
    result = delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_finalize_failure",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="operator",
        reason="quota",
    )

    assert result["packageBytesState"] == "deleted"
    assert result["packageFileDeleted"] is True
    with get_connection(cfg) as connection:
        final_row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_deleted_at, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert final_row["package_bytes_state"] == "deleted"
    assert final_row["package_bytes_gc_reason"] == "quota"


def test_result_package_byte_delete_keeps_deleting_state_when_reserve_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_package_byte_delete_reserve_failure")
    package_path = Path(package["packagePath"])

    def fail_reserve(path):
        raise RuntimeError("forced reserve failure")

    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_service._reserve_package_file_for_deletion",
        fail_reserve,
    )
    with pytest.raises(RuntimeError, match="forced reserve failure"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_reserve_failure",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
            actor="operator",
            reason="quota",
        )

    assert package_path.is_file()
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert row["package_bytes_state"] == "deleting"
    assert row["package_bytes_gc_reason"] == "quota"

    monkeypatch.undo()
    result = delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_reserve_failure",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="operator",
        reason="quota",
    )

    assert result["packageBytesState"] == "deleted"
    assert not package_path.exists()


def test_result_package_byte_delete_keeps_deleting_state_when_reserved_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_package_byte_delete_unlink_failure")
    package_path = Path(package["packagePath"])

    def fail_delete(path):
        raise RuntimeError("forced reserved delete failure")

    monkeypatch.setattr(
        "apps.remote_runner.result_package_byte_gc_service._delete_reserved_package_file",
        fail_delete,
    )
    with pytest.raises(RuntimeError, match="forced reserved delete failure"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_unlink_failure",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
            actor="operator",
            reason="quota",
        )

    assert package_path.is_file()
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert row["package_bytes_state"] == "deleting"
    assert row["package_bytes_gc_reason"] == "quota"

    monkeypatch.undo()
    result = delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_unlink_failure",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="operator",
        reason="quota",
    )

    assert result["packageBytesState"] == "deleted"
    assert not package_path.exists()


def test_result_package_byte_delete_recovers_available_reserved_file(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    package = _retired_package(cfg, "run_package_byte_delete_available_reserved")
    package_path = Path(package["packagePath"])
    reserved_path = package_path.with_name(f".{package_path.name}.crash.deleting")
    package_path.replace(reserved_path)

    result = delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_available_reserved",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="operator",
        reason="quota",
    )

    assert result["packageBytesState"] == "deleted"
    assert result["packageFileDeleted"] is True
    assert not package_path.exists()
    assert not reserved_path.exists()
    with get_connection(cfg) as connection:
        final_row = connection.execute(
            """
            SELECT package_bytes_state, package_bytes_gc_reason
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        ).fetchone()
    assert final_row["package_bytes_state"] == "deleted"
    assert final_row["package_bytes_gc_reason"] == "quota"


def test_result_package_byte_delete_rejects_confirmation_state_and_identity_errors(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_byte_delete_guard")
    package = export_result_package(cfg, "res_run_package_byte_delete_guard", include_artifacts=False)

    with pytest.raises(ValueError, match="RESULT_PACKAGE_BYTE_GC_CONFIRMATION_REQUIRED"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_guard",
            package["packageExportId"],
            confirmation="delete",
        )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_RETIRED: active"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_guard",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )

    retire_result_package_export(
        cfg,
        "res_run_package_byte_delete_guard",
        package["packageExportId"],
        confirmation="retire-result-package-export",
    )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_RESULT_MISMATCH"):
        delete_retired_result_package_bytes(
            cfg,
            "res_other",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )
    delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_guard",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
    )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_BYTES_ALREADY_DELETED"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_byte_delete_guard",
            package["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )


def test_result_package_byte_delete_rejects_unmanaged_missing_and_drifted_files(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    unmanaged = _retired_package(cfg, "run_package_unmanaged")
    unmanaged_path = tmp_path / "outside" / "package.zip"
    unmanaged_path.parent.mkdir(parents=True)
    unmanaged_path.write_bytes(Path(unmanaged["packagePath"]).read_bytes())
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET package_path = ? WHERE package_export_id = ?",
            (str(unmanaged_path), unmanaged["packageExportId"]),
        )
        connection.commit()
    with pytest.raises(ValueError, match="RESULT_PACKAGE_PATH_UNMANAGED"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_unmanaged",
            unmanaged["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )

    missing = _retired_package(cfg, "run_package_missing_zip")
    Path(missing["packagePath"]).unlink()
    with pytest.raises(ValueError, match="RESULT_PACKAGE_FILE_MISSING"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_missing_zip",
            missing["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )

    size_drift = _retired_package(cfg, "run_package_size_drift")
    Path(size_drift["packagePath"]).write_bytes(b"short")
    with pytest.raises(ValueError, match="RESULT_PACKAGE_SIZE_MISMATCH"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_size_drift",
            size_drift["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )

    checksum_drift = _retired_package(cfg, "run_package_checksum_drift")
    checksum_path = Path(checksum_drift["packagePath"])
    checksum_path.write_bytes(b"x" * int(checksum_drift["sizeBytes"]))
    with pytest.raises(ValueError, match="RESULT_PACKAGE_CHECKSUM_MISMATCH"):
        delete_retired_result_package_bytes(
            cfg,
            "res_run_package_checksum_drift",
            checksum_drift["packageExportId"],
            confirmation="delete-result-package-export-bytes",
        )


def test_result_package_byte_delete_audit_records_actor_roles(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("artifact-curator", "auditor"))
    package = _retired_package(cfg, "run_package_byte_delete_actor_roles")

    delete_retired_result_package_bytes(
        cfg,
        "res_run_package_byte_delete_actor_roles",
        package["packageExportId"],
        confirmation="delete-result-package-export-bytes",
        actor="curator@example.test",
    )

    audit = list_governance_audit_events(cfg, action="result.package.bytes.delete")["items"][-1]
    assert audit["actor"] == "curator@example.test"
    assert audit["actorRoles"] == ["artifact-curator", "auditor"]


def _retired_package(cfg, run_id: str) -> dict[str, object]:
    _create_exportable_result(cfg, run_id)
    package = export_result_package(cfg, f"res_{run_id}", include_artifacts=True)
    retire_result_package_export(
        cfg,
        f"res_{run_id}",
        package["packageExportId"],
        confirmation="retire-result-package-export",
    )
    return package


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
