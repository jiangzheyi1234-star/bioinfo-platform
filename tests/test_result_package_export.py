from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from apps.remote_runner.artifact_product_service import (
    build_result_artifact_audit,
    export_result_package,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.rule_execution_storage import append_run_rule_event, upsert_run_rule_state
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
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
    revision = _create_run(cfg, "run_export", complete=False)
    _seed_rule_state(cfg, "run_export")
    _mark_run_terminal(cfg, "run_export")
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

    package = export_result_package(cfg, "res_run_export", include_artifacts=True)
    package_path = Path(package["packagePath"])

    assert package["schemaVersion"] == "h2ometa.result-package.v2"
    assert package_path.is_file()
    assert package["sizeBytes"] == package_path.stat().st_size
    assert len(package["sha256"]) == 64
    assert package["packageProfile"] == "h2ometa.result-evidence-package.v1"
    assert package["workflowRevisionId"] == revision["workflowRevisionId"]
    assert package["manifest"]["audit"]["status"] == "passed"
    assert package["manifest"]["runSpec"]["workflowRevisionId"] == revision["workflowRevisionId"]
    assert package["manifest"]["workflowRevision"]["contentHash"] == revision["contentHash"]
    assert package["manifest"]["artifacts"][0]["artifactId"] == artifact["artifactId"]
    assert package["manifest"]["lineageEdges"][0]["predicate"] == "prov:generated"
    assert package["manifest"]["eventCounts"]["runEvents"] >= 2
    assert package["manifest"]["eventCounts"]["rules"] == 1
    assert package["manifest"]["eventCounts"]["ruleEvents"] == 1
    assert package["manifest"]["eventCounts"]["evidenceEvents"] >= 1
    assert {item["path"] for item in package["manifest"]["metadataFiles"]} == {
        "metadata/artifact-audit.json",
        "metadata/evidence-events.json",
        "metadata/lineage.json",
        "metadata/rules.json",
        "metadata/run-events.json",
        "metadata/run.json",
        "metadata/workflow-revision.json",
    }
    export_evidence = list_evidence_events(
        cfg,
        subject_kind="result",
        subject_id="res_run_export",
        event_type="result.export.v1",
    )
    assert export_evidence[-1]["payload"]["sha256"] == package["sha256"]
    assert export_evidence[-1]["payload"]["manifestSha256"] == package["manifestSha256"]
    audit_events = list_governance_audit_events(
        cfg,
        subject_kind="result",
        subject_id="res_run_export",
        action="result.export",
    )["items"]
    assert audit_events[0]["details"]["artifactCount"] == 1
    assert audit_events[0]["details"]["packageSha256"] == package["sha256"]
    assert audit_events[0]["details"]["evidenceId"] == package["evidenceId"]
    assert audit_events[0]["details"]["packageExportId"] == package["packageExportId"]
    with get_connection(cfg) as connection:
        export_row = connection.execute(
            "SELECT * FROM result_package_exports WHERE package_export_id = ?",
            (package["packageExportId"],),
        ).fetchone()
    assert export_row["result_id"] == "res_run_export"
    assert export_row["workflow_revision_id"] == revision["workflowRevisionId"]
    assert export_row["manifest_sha256"] == package["manifestSha256"]
    assert json.loads(export_row["artifact_ids_json"]) == [artifact["artifactId"]]
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        manifest_raw = archive.read("manifest.json")
        manifest = json.loads(manifest_raw.decode("utf-8"))
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        ro_crate = json.loads(archive.read("ro-crate-metadata.json").decode("utf-8"))
        rules = json.loads(archive.read("metadata/rules.json").decode("utf-8"))
        workflow_revision = json.loads(archive.read("metadata/workflow-revision.json").decode("utf-8"))
        payload = archive.read(f"artifacts/{artifact['artifactId']}/report.txt").decode("utf-8")

    assert {
        f"artifacts/{artifact['artifactId']}/report.txt",
        "manifest.json",
        "ro-crate-metadata.json",
        "metadata/run.json",
        "metadata/workflow-revision.json",
        "metadata/run-events.json",
        "metadata/rules.json",
        "metadata/lineage.json",
        "metadata/evidence-events.json",
        "metadata/artifact-audit.json",
    } <= names
    assert manifest["resultId"] == "res_run_export"
    assert manifest_sha256 == package["manifestSha256"]
    assert ro_crate["@context"] == "https://w3id.org/ro/crate/1.1/context"
    assert ro_crate["@graph"][0]["@id"] == "ro-crate-metadata.json"
    assert workflow_revision["workflowRevisionId"] == revision["workflowRevisionId"]
    assert rules["items"][0]["ruleName"] == "summarize"
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
        export_result_package(cfg, "res_run_export_failed", include_artifacts=True)


def test_result_package_export_requires_workflow_revision(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id="req_run_export_unversioned",
        run_spec={
            "runId": "run_export_unversioned",
            "projectId": "proj_artifact",
            "pipelineId": "file-summary-standard-v1",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key="idem_run_export_unversioned",
        payload_hash="hash_run_export_unversioned",
    )
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_export_unversioned",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    with pytest.raises(ValueError, match="RESULT_WORKFLOW_REVISION_REQUIRED"):
        export_result_package(cfg, "res_run_export_unversioned", include_artifacts=True)


def test_result_package_export_rejects_invalid_result_id(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="RESULT_ID_INVALID"):
        export_result_package(cfg, "res_../escape", include_artifacts=True)


def test_result_package_export_rejects_non_boolean_include_artifacts(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_export_non_bool")
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_export_non_bool",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    with pytest.raises(ValueError, match="RESULT_PACKAGE_INCLUDE_ARTIFACTS_BOOL_REQUIRED"):
        export_result_package(cfg, "res_run_export_non_bool", include_artifacts="false")  # type: ignore[arg-type]


def test_result_package_export_rejects_non_terminal_run(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_export_running", complete=False)
    report = tmp_path / "running-report.txt"
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_export_running",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    with pytest.raises(ValueError, match="RESULT_RUN_NOT_TERMINAL: queued"):
        export_result_package(cfg, "res_run_export_running", include_artifacts=True)


def test_result_package_export_redacts_secret_run_spec_fields(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_export_secret",
        params={"apiToken": "secret-token", "artifactKey": "report", "threshold": 7},
    )
    report = tmp_path / "secret-report.txt"
    report.write_bytes(b"accepted\n")
    persist_artifact(
        cfg,
        run_id="run_export_secret",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    package = export_result_package(cfg, "res_run_export_secret", include_artifacts=True)
    with zipfile.ZipFile(package["packagePath"]) as archive:
        run_metadata = json.loads(archive.read("metadata/run.json").decode("utf-8"))

    assert package["manifest"]["runSpec"]["params"]["apiToken"] == "<redacted>"
    assert package["manifest"]["runSpec"]["params"]["artifactKey"] == "report"
    assert package["manifest"]["runSpec"]["params"]["threshold"] == 7
    assert package["manifest"]["redactedSecretPaths"] == ["runSpec.params.apiToken"]
    assert run_metadata["runSpec"]["params"]["apiToken"] == "<redacted>"


def test_result_package_metadata_only_export_references_artifacts_without_payloads(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_run(cfg, "run_export_metadata_only")
    report = tmp_path / "metadata-only-report.txt"
    report.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_export_metadata_only",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    package = export_result_package(
        cfg,
        "res_run_export_metadata_only",
        include_artifacts=False,
        actor="operator@example.test",
    )

    assert package["includeArtifacts"] is False
    assert package["artifactPayloadMode"] == "metadata-only"
    assert package["workflowRevisionId"] == revision["workflowRevisionId"]
    manifest_artifact = package["manifest"]["artifacts"][0]
    assert manifest_artifact["includedInPackage"] is False
    assert manifest_artifact["packagePath"] is None
    assert manifest_artifact["externalUri"] == artifact["storageUri"]
    assert manifest_artifact["sha256"] == artifact["sha256"]
    with get_connection(cfg) as connection:
        export_row = connection.execute(
            "SELECT include_artifacts, artifact_payload_mode FROM result_package_exports WHERE package_export_id = ?",
            (package["packageExportId"],),
        ).fetchone()
    assert export_row["include_artifacts"] == 0
    assert export_row["artifact_payload_mode"] == "metadata-only"
    with zipfile.ZipFile(package["packagePath"]) as archive:
        names = set(archive.namelist())
        ro_crate = json.loads(archive.read("ro-crate-metadata.json").decode("utf-8"))

    assert f"artifacts/{artifact['artifactId']}/metadata-only-report.txt" not in names
    assert "manifest.json" in names
    assert "metadata/artifact-audit.json" in names
    graph_by_id = {item["@id"]: item for item in ro_crate["@graph"]}
    assert artifact["storageUri"] in graph_by_id
    assert graph_by_id[artifact["storageUri"]]["h2ometa:includedInPackage"] is False


def test_result_package_full_and_metadata_only_exports_do_not_overwrite_each_other(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_export_modes")
    report = tmp_path / "report.txt"
    report.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_export_modes",
        kind="report",
        path=report,
        mime_type="text/plain",
        artifact_key="report",
    )

    full_package = export_result_package(cfg, "res_run_export_modes", include_artifacts=True)
    metadata_package = export_result_package(cfg, "res_run_export_modes", include_artifacts=False)

    assert Path(full_package["packagePath"]).name == "res_run_export_modes.zip"
    assert Path(metadata_package["packagePath"]).name == "res_run_export_modes.metadata-only.zip"
    assert Path(full_package["packagePath"]).is_file()
    assert Path(metadata_package["packagePath"]).is_file()
    with zipfile.ZipFile(full_package["packagePath"]) as archive:
        full_names = set(archive.namelist())
    with zipfile.ZipFile(metadata_package["packagePath"]) as archive:
        metadata_names = set(archive.namelist())
    assert f"artifacts/{artifact['artifactId']}/report.txt" in full_names
    assert f"artifacts/{artifact['artifactId']}/report.txt" not in metadata_names
    with get_connection(cfg) as connection:
        export_count = connection.execute(
            "SELECT COUNT(*) FROM result_package_exports WHERE result_id = 'res_run_export_modes'"
        ).fetchone()[0]
    assert export_count == 2


def _create_run(
    cfg,
    run_id: str,
    *,
    params: dict[str, object] | None = None,
    complete: bool = True,
) -> dict[str, object]:
    revision = _create_revision(cfg, run_id)
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
            **({"params": params} if params else {}),
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    if complete:
        _mark_run_terminal(cfg, run_id)
    return revision


def _create_revision(cfg, run_id: str) -> dict[str, object]:
    return create_or_fetch_workflow_revision(
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


def _seed_rule_state(cfg, run_id: str) -> None:
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_result_package",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    upsert_run_rule_state(
        cfg,
        run_id=run_id,
        rule_name="summarize",
        step_id="summarize",
        runtime_status_key="summarize",
        status="succeeded",
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        started_at="2099-06-07T10:00:01Z",
        finished_at="2099-06-07T10:00:02Z",
        command_summary="python summarize.py",
        inputs=["input.txt"],
        outputs=["report.txt"],
    )
    append_run_rule_event(
        cfg,
        run_id=run_id,
        rule_name="summarize",
        step_id="summarize",
        event_type="JOB_FINISHED",
        status="succeeded",
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        message="Rule finished.",
        occurred_at="2099-06-07T10:00:02Z",
    )


def _mark_run_terminal(cfg, run_id: str) -> None:
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
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'completed',
                updated_at = '2099-06-07T10:00:03Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.commit()
