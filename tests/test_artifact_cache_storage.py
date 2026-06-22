from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from apps.remote_runner.artifact_cache_storage import (
    list_artifact_cache_entries,
    lookup_artifact_cache_entry,
)
from apps.remote_runner.artifact_lifecycle_service import ARTIFACT_GC_CONFIRMATION, run_artifact_gc
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.upload_storage import persist_upload
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_cache_records_workflow_revision_key_and_verified_lookup_hit(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_hit", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    artifact_path = _managed_report(cfg, "run_cache_hit", b"cached output\n")

    artifact = persist_artifact(
        cfg,
        run_id="run_cache_hit",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    entries = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"]
    events = list_evidence_events(cfg, subject_kind="artifact_cache", subject_id=lookup["cacheKey"])

    assert artifact["artifactCacheEligible"] is True
    assert artifact["artifactCacheKey"] == lookup["cacheKey"]
    assert lookup["hit"] is True
    assert lookup["reason"] == "hit"
    assert lookup["entry"]["artifactId"] == artifact["artifactId"]
    assert lookup["entry"]["hitCount"] == 1
    assert entries[0]["cacheKey"] == lookup["cacheKey"]
    assert entries[0]["hitCount"] == 1
    assert events[-1]["eventType"] == "artifact.cache.lookup.v1"
    assert events[-1]["payload"]["hit"] is True


def test_artifact_cache_lookup_misses_when_relevant_inputs_change(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_miss", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_miss",
        kind="report",
        path=_managed_report(cfg, "run_cache_miss", b"cached output\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    changed = _lookup_payload(revision["workflowRevisionId"])
    changed["params"] = {"threshold": 9}
    lookup = lookup_artifact_cache_entry(cfg, changed)

    assert lookup["hit"] is False
    assert lookup["reason"] == "cache_key_not_found"


def test_artifact_cache_key_uses_upload_content_digest_for_inputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    first_upload = _upload(cfg, "first.fastq", b"same reads\n")
    second_upload = _upload(cfg, "renamed.fastq", b"same reads\n")
    run_spec = _run_spec(
        "run_cache_upload",
        revision["workflowRevisionId"],
        inputs=[{"name": "reads", "uploadId": first_upload["uploadId"], "filename": "first.fastq"}],
    )
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_upload",
        kind="report",
        path=_managed_report(cfg, "run_cache_upload", b"content keyed\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    lookup = lookup_artifact_cache_entry(
        cfg,
        _lookup_payload(
            revision["workflowRevisionId"],
            inputs=[{"name": "reads", "uploadId": second_upload["uploadId"], "filename": "renamed.fastq"}],
        ),
    )

    assert lookup["hit"] is True
    assert lookup["reason"] == "hit"


def test_artifact_cache_key_conflict_does_not_overwrite_existing_entry(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    first_spec = _run_spec("run_cache_original", revision["workflowRevisionId"])
    second_spec = _run_spec("run_cache_conflict", revision["workflowRevisionId"])
    _create_terminal_run(cfg, first_spec)
    _create_terminal_run(cfg, second_spec)
    first = persist_artifact(
        cfg,
        run_id="run_cache_original",
        kind="report",
        path=_managed_report(cfg, "run_cache_original", b"original\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    conflict = persist_artifact(
        cfg,
        run_id="run_cache_conflict",
        kind="report",
        path=_managed_report(cfg, "run_cache_conflict", b"different\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    entries = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"]

    assert first["artifactCacheEligible"] is True
    assert conflict["artifactCacheEligible"] is False
    assert conflict["artifactCacheIneligibleReason"] == "cache_key_conflict"
    assert [entry["artifactId"] for entry in entries] == [first["artifactId"]]


def test_artifact_cache_does_not_index_outputs_without_workflow_revision(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_spec = _run_spec("run_cache_ineligible", "")
    run_spec.pop("workflowRevisionId")
    _create_terminal_run(cfg, run_spec)

    artifact = persist_artifact(
        cfg,
        run_id="run_cache_ineligible",
        kind="report",
        path=_managed_report(cfg, "run_cache_ineligible", b"uncached\n"),
        mime_type="text/plain",
        artifact_key="report",
    )

    assert artifact["artifactCacheEligible"] is False
    assert artifact["artifactCacheIneligibleReason"] == "workflow_revision_missing"
    assert list_artifact_cache_entries(cfg)["items"] == []


def test_artifact_cache_marks_entry_deleted_after_gc(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    run_spec = _run_spec("run_cache_gc", revision["workflowRevisionId"])
    _create_terminal_run(cfg, run_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_gc",
        kind="report",
        path=_managed_report(cfg, "run_cache_gc", b"gc cached\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    run_artifact_gc(
        cfg,
        {
            "retentionDays": 30,
            "confirmation": ARTIFACT_GC_CONFIRMATION,
        },
    )
    lookup = lookup_artifact_cache_entry(cfg, _lookup_payload(revision["workflowRevisionId"]))
    entry = list_artifact_cache_entries(cfg, workflow_revision_id=revision["workflowRevisionId"])["items"][0]

    assert entry["lifecycleState"] == "deleted"
    assert lookup["hit"] is False
    assert lookup["reason"] == "cache_entry_not_active"


def _create_revision(cfg) -> dict[str, Any]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_cache",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "snake"}]},
        graph_snapshot={"nodes": [{"id": "summarize", "toolRevisionId": "tool#1"}]},
        runtime_lock={"snakemake": "9.23.1", "python": "3.12"},
        compiler={"name": "h2ometa", "version": "cache-test"},
    )


def _run_spec(run_id: str, workflow_revision_id: str, *, inputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "runId": run_id,
        "projectId": "proj_cache",
        "pipelineId": "pipeline_cache",
        "pipelineVersion": "0.1.0",
        "workflowRevisionId": workflow_revision_id,
        "inputs": inputs or [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _lookup_payload(workflow_revision_id: str, *, inputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "workflowRevisionId": workflow_revision_id,
        "artifactKey": "report",
        "stepId": "summarize",
        "role": "output",
        "inputs": inputs or [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _create_terminal_run(cfg, run_spec: dict[str, Any]) -> None:
    create_run_record(
        cfg,
        server_id="srv_cache",
        request_id=f"req_{run_spec['runId']}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_spec['runId']}",
        payload_hash=f"hash_{run_spec['runId']}",
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
            (run_spec["runId"],),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = '2025-01-01T00:00:00Z' WHERE run_id = ?",
            (run_spec["runId"],),
        )
        connection.commit()


def _managed_report(cfg, run_id: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / "report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _upload(cfg, filename: str, payload: bytes) -> dict[str, Any]:
    return persist_upload(
        cfg,
        filename=filename,
        content_base64=base64.b64encode(payload).decode("ascii"),
        mime_type="text/plain",
    )
