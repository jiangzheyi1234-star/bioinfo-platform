from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from apps.remote_runner.artifact_product_service import (
    build_result_artifact_audit,
    export_result_package,
)
from apps.remote_runner.storage import create_run_record, persist_artifact
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_artifact_audit_detects_checksum_drift(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_audit")
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_audit",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    passed = build_result_artifact_audit(cfg, "res_run_audit")
    report.write_bytes(b"tampered\n")
    failed = build_result_artifact_audit(cfg, "res_run_audit")

    assert passed["status"] == "passed"
    assert passed["artifacts"][0]["artifactId"] == artifact["artifactId"]
    assert passed["artifacts"][0]["checksumOk"] is True
    assert failed["status"] == "failed"
    assert failed["failedCount"] == 1
    assert failed["artifacts"][0]["checksumOk"] is False


def test_result_package_export_includes_manifest_artifacts_and_lineage(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_export")
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_export",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    package = export_result_package(cfg, "res_run_export")
    package_path = Path(package["packagePath"])

    assert package["schemaVersion"] == "h2ometa.result-package.v1"
    assert package_path.is_file()
    assert package["sizeBytes"] == package_path.stat().st_size
    assert len(package["sha256"]) == 64
    assert package["manifest"]["audit"]["status"] == "passed"
    assert package["manifest"]["artifacts"][0]["artifactId"] == artifact["artifactId"]
    assert package["manifest"]["lineageEdges"][0]["predicate"] == "prov:generated"
    with zipfile.ZipFile(package_path) as archive:
        names = sorted(archive.namelist())
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        payload = archive.read(f"artifacts/{artifact['artifactId']}/report.txt").decode("utf-8")

    assert names == [f"artifacts/{artifact['artifactId']}/report.txt", "manifest.json"]
    assert manifest["resultId"] == "res_run_export"
    assert payload == "accepted\n"


def test_result_package_export_refuses_failed_checksum_audit(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_export_failed")
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_export_failed",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )
    report.write_bytes(b"tampered\n")

    with pytest.raises(ValueError, match="RESULT_ARTIFACT_AUDIT_FAILED"):
        export_result_package(cfg, "res_run_export_failed")


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact",
            "pipelineId": "file-summary-standard-v1",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
