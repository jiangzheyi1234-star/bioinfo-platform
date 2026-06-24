from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.result_package_download_service import build_result_package_download
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_package_download_validates_record_and_checksum(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_download")
    package = export_result_package(cfg, "res_run_download", include_artifacts=True)

    download = build_result_package_download(
        cfg,
        result_id="res_run_download",
        package_export_id=package["packageExportId"],
    )

    assert download["schemaVersion"] == "h2ometa.result-package-download.v1"
    assert download["path"] == Path(package["packagePath"]).resolve()
    assert download["filename"] == "res_run_download.zip"
    assert download["mediaType"] == "application/zip"
    assert download["sizeBytes"] == package["sizeBytes"]
    assert download["sha256"] == package["sha256"]
    assert download["headers"]["Content-Disposition"] == 'attachment; filename="res_run_download.zip"'
    assert download["headers"]["X-Content-Type-Options"] == "nosniff"
    assert download["headers"]["Cache-Control"] == "private, no-store"
    assert download["headers"]["X-H2OMeta-Package-Export-Id"] == package["packageExportId"]


def test_result_package_download_rejects_unknown_or_invalid_export_id(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_FOUND"):
        build_result_package_download(
            cfg,
            result_id="res_missing",
            package_export_id="rpexp_1111111111111111",
        )
    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_ID_INVALID"):
        build_result_package_download(
            cfg,
            result_id="res_missing",
            package_export_id="../escape",
        )


def test_result_package_download_rejects_result_mismatch_and_inactive_record(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_download_state")
    package = export_result_package(cfg, "res_run_download_state", include_artifacts=True)

    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_RESULT_MISMATCH"):
        build_result_package_download(
            cfg,
            result_id="res_other",
            package_export_id=package["packageExportId"],
        )

    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET lifecycle_state = 'deleted' WHERE package_export_id = ?",
            (package["packageExportId"],),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_NOT_ACTIVE: deleted"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_state",
            package_export_id=package["packageExportId"],
        )

    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE result_package_exports
            SET lifecycle_state = 'active', package_bytes_state = 'deleted'
            WHERE package_export_id = ?
            """,
            (package["packageExportId"],),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RESULT_PACKAGE_EXPORT_BYTES_UNAVAILABLE: deleted"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_state",
            package_export_id=package["packageExportId"],
        )


def test_result_package_download_rejects_unmanaged_or_missing_package_path(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_download_path")
    package = export_result_package(cfg, "res_run_download_path", include_artifacts=True)

    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET package_path = ? WHERE package_export_id = ?",
            (str(tmp_path / "outside.zip"), package["packageExportId"]),
        )
        connection.commit()
    with pytest.raises(ValueError, match="RESULT_PACKAGE_PATH_UNMANAGED"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_path",
            package_export_id=package["packageExportId"],
        )

    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET package_path = ? WHERE package_export_id = ?",
            (package["packagePath"], package["packageExportId"]),
        )
        connection.commit()
    Path(package["packagePath"]).unlink()
    with pytest.raises(ValueError, match="RESULT_PACKAGE_FILE_MISSING"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_path",
            package_export_id=package["packageExportId"],
        )


def test_result_package_download_rejects_size_or_checksum_drift(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_download_drift")
    package = export_result_package(cfg, "res_run_download_drift", include_artifacts=True)
    package_path = Path(package["packagePath"])

    package_path.write_bytes(package_path.read_bytes() + b"extra")
    with pytest.raises(ValueError, match="RESULT_PACKAGE_SIZE_MISMATCH"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_drift",
            package_export_id=package["packageExportId"],
        )

    package_path.write_bytes(Path(package["packagePath"]).read_bytes()[: package["sizeBytes"]])
    data = bytearray(package_path.read_bytes())
    data[0] = data[0] ^ 1
    package_path.write_bytes(data)
    with pytest.raises(ValueError, match="RESULT_PACKAGE_CHECKSUM_MISMATCH"):
        build_result_package_download(
            cfg,
            result_id="res_run_download_drift",
            package_export_id=package["packageExportId"],
        )


def _create_exportable_result(cfg, run_id: str) -> None:
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
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact",
            "pipelineId": "file-summary-standard-v1",
            "pipelineVersion": "0.1.0",
            "workflowRevisionId": revision["workflowRevisionId"],
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    report = Path(cfg.results_dir) / run_id / f"{run_id}.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b"accepted\n")
    persist_artifact(
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
                finished_at = '2099-06-07T10:00:03Z',
                last_updated_at = '2099-06-07T10:00:03Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.commit()
