from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Callable

import pytest

from apps.remote_runner.artifact_ledger_storage import record_lineage_edge
from apps.remote_runner.artifact_product_lineage import input_artifacts_from_lineage
from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.result_package_validation import validate_result_package_archive
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("missing_sha256", "RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_REQUIRED"),
        ("invalid_sha256", "RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_INVALID"),
        ("missing_size", "RESULT_PACKAGE_INPUT_ARTIFACT_SIZE_BYTES_REQUIRED"),
        ("string_size", "RESULT_PACKAGE_INPUT_ARTIFACT_SIZE_BYTES_REQUIRED"),
        ("blank_mime", "RESULT_PACKAGE_INPUT_ARTIFACT_MIME_TYPE_REQUIRED"),
    ],
)
def test_result_package_export_rejects_incomplete_input_artifact_lineage(
    tmp_path: Path,
    mutation: str,
    error_code: str,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    result_id = "res_run_input_lineage_bad"
    _create_run_with_output(cfg, "run_input_lineage_bad")
    source = _persist_source_artifact(cfg, "run_source_lineage_bad")
    _record_input_lineage_edge(
        cfg,
        run_id="run_input_lineage_bad",
        source=source,
        payload=_mutated_input_payload(source, mutation),
    )

    with pytest.raises(ValueError, match=error_code):
        export_result_package(cfg, result_id, include_artifacts=True)

    assert not (Path(cfg.results_dir) / "packages" / result_id / f"{result_id}.zip").exists()
    assert list_evidence_events(
        cfg,
        subject_kind="result",
        subject_id=result_id,
        event_type="result.export.v1",
    ) == []
    assert list_governance_audit_events(
        cfg,
        subject_kind="result",
        subject_id=result_id,
        action="result.export",
    )["items"] == []
    with get_connection(cfg) as connection:
        export_count = connection.execute(
            "SELECT COUNT(*) FROM result_package_exports WHERE result_id = ?",
            (result_id,),
        ).fetchone()[0]
    assert export_count == 0


def test_result_package_input_lineage_rejects_content_hash_as_sha256_fallback() -> None:
    artifact_blob_id = "ablob_strict"
    source_sha256 = "a" * 64

    with pytest.raises(ValueError, match="RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_REQUIRED"):
        input_artifacts_from_lineage(
            [
                {
                    "predicate": "prov:used",
                    "objectKind": "artifact_blob",
                    "objectId": artifact_blob_id,
                    "contentHash": source_sha256,
                    "payload": {
                        "mimeType": "text/plain",
                        "sizeBytes": 10,
                    },
                }
            ]
        )


def test_result_package_input_lineage_rejects_conflicting_blob_identity() -> None:
    artifact_blob_id = "ablob_conflict"

    with pytest.raises(ValueError, match="RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_CONFLICT"):
        input_artifacts_from_lineage(
            [
                _lineage_edge(artifact_blob_id, sha256="a" * 64, size_bytes=10),
                _lineage_edge(artifact_blob_id, sha256="b" * 64, size_bytes=10),
            ]
        )


def test_result_package_validator_rejects_manifest_input_artifact_mismatch(tmp_path: Path) -> None:
    package = _valid_package_with_input(tmp_path)
    broken_package = tmp_path / "broken-input-manifest.zip"

    def break_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        manifest["inputArtifacts"][0]["sha256"] = "not-a-sha"
        return manifest

    _copy_zip_rewriting_json(
        Path(package["packagePath"]),
        broken_package,
        "manifest.json",
        break_manifest,
    )

    with pytest.raises(ValueError, match="manifest inputArtifact sha256 is invalid"):
        validate_result_package_archive(broken_package)


def test_result_package_validator_rejects_ro_crate_input_artifact_mismatch(tmp_path: Path) -> None:
    package = _valid_package_with_input(tmp_path)
    broken_package = tmp_path / "broken-input-ro-crate.zip"

    def break_ro_crate(ro_crate: dict[str, Any]) -> dict[str, Any]:
        input_entity_id = next(
            item["@id"]
            for item in ro_crate["@graph"]
            if str(item.get("@id") or "").startswith("urn:h2ometa:artifact-blob:")
        )
        ro_crate["@graph"] = [item for item in ro_crate["@graph"] if item.get("@id") != input_entity_id]
        return ro_crate

    _copy_zip_rewriting_json(
        Path(package["packagePath"]),
        broken_package,
        "ro-crate-metadata.json",
        break_ro_crate,
    )

    with pytest.raises(ValueError, match="RO-Crate input artifact entity is missing"):
        validate_result_package_archive(
            broken_package,
            expected_manifest_sha256=package["manifestSha256"],
        )


def _valid_package_with_input(tmp_path: Path) -> dict[str, Any]:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run_with_output(cfg, "run_input_lineage_valid")
    source = _persist_source_artifact(cfg, "run_source_lineage_valid")
    _record_input_lineage_edge(
        cfg,
        run_id="run_input_lineage_valid",
        source=source,
        payload=_input_payload(source),
    )
    return export_result_package(cfg, "res_run_input_lineage_valid", include_artifacts=True)


def _create_run_with_output(cfg, run_id: str) -> None:
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
    report = _managed_artifact_file(cfg, run_id, "report.txt")
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


def _persist_source_artifact(cfg, run_id: str) -> dict[str, Any]:
    source_path = _managed_artifact_file(cfg, run_id, "reads.fastq")
    source_path.write_bytes(b"reads\n")
    return persist_artifact(
        cfg,
        run_id=run_id,
        kind="reads",
        path=source_path,
        mime_type="text/plain",
        artifact_key="reads",
    )


def _record_input_lineage_edge(
    cfg,
    *,
    run_id: str,
    source: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:used",
        object_kind="artifact_blob",
        object_id=source["artifactBlobId"],
        run_id=run_id,
        workflow_revision_id=_workflow_revision_id(cfg, run_id),
        payload=payload,
        content_hash=source["sha256"],
        created_at="2099-06-07T10:00:00Z",
    )


def _input_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceType": "artifact",
        "sourceId": source["artifactId"],
        "artifactId": source["artifactId"],
        "sourceMaterializationId": source["materializationId"],
        "sourceStorageBackend": source["storageBackend"],
        "filename": "reads.fastq",
        "inputName": "reads",
        "inputRole": "reads",
        "inputIndex": 0,
        "portName": "reads",
        "mimeType": source["mimeType"],
        "sizeBytes": source["sizeBytes"],
        "sha256": source["sha256"],
        "materializationId": source["materializationId"],
        "role": "input",
        "upstreamRunId": source["runId"],
    }


def _mutated_input_payload(source: dict[str, Any], mutation: str) -> dict[str, Any]:
    payload = _input_payload(source)
    if mutation == "missing_sha256":
        del payload["sha256"]
    elif mutation == "invalid_sha256":
        payload["sha256"] = "not-a-sha"
    elif mutation == "missing_size":
        del payload["sizeBytes"]
    elif mutation == "string_size":
        payload["sizeBytes"] = str(source["sizeBytes"])
    elif mutation == "blank_mime":
        payload["mimeType"] = " "
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")
    return payload


def _lineage_edge(artifact_blob_id: str, *, sha256: str, size_bytes: int) -> dict[str, Any]:
    return {
        "predicate": "prov:used",
        "objectKind": "artifact_blob",
        "objectId": artifact_blob_id,
        "payload": {
            "sha256": sha256,
            "mimeType": "text/plain",
            "sizeBytes": size_bytes,
        },
    }


def _managed_artifact_file(cfg, run_id: str, filename: str) -> Path:
    path = Path(cfg.results_dir) / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _workflow_revision_id(cfg, run_id: str) -> str:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return str(row["workflow_revision_id"])


def _copy_zip_rewriting_json(
    source: Path,
    target: Path,
    entry_name: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    with zipfile.ZipFile(source) as source_archive, zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as target_archive:
        for info in source_archive.infolist():
            raw = source_archive.read(info.filename)
            if info.filename == entry_name:
                payload = mutate(json.loads(raw.decode("utf-8")))
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            target_archive.writestr(info, raw)
