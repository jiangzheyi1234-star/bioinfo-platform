from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.artifact_ledger_storage import (
    list_artifact_materializations,
    list_lineage_edges_for_run,
    list_run_artifact_edges,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.reconciler import run_active_reconciler_once
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from tests.helpers.reference_database import make_configured_remote_runner


def _create_run(cfg, run_id: str, *, execution: dict | None = None) -> None:
    run_spec = {
        "runId": run_id,
        "projectId": "proj_artifact",
        "pipelineId": "pipeline_artifact",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }
    if execution is not None:
        run_spec["execution"] = execution
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def test_persist_artifact_records_storage_backend_and_uri(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_artifact_uri")
    artifact_path = tmp_path / "result.txt"
    artifact_path.write_text("accepted\n", encoding="utf-8")

    artifact = persist_artifact(
        cfg,
        run_id="run_artifact_uri",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
    )
    fetched = fetch_run_results(cfg, "run_artifact_uri")["artifacts"][0]

    assert artifact["storageBackend"] == "local"
    assert artifact["storageUri"] == artifact_path.resolve().as_uri()
    assert fetched["storageBackend"] == "local"
    assert fetched["storageUri"] == artifact_path.resolve().as_uri()


def test_persist_artifact_records_blob_materialization_and_output_edge(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_artifact_ledger")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_text("accepted\n", encoding="utf-8")

    artifact = persist_artifact(
        cfg,
        run_id="run_artifact_ledger",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    edges = list_run_artifact_edges(cfg, "run_artifact_ledger")
    assert len(edges) == 1
    assert edges[0]["role"] == "output"
    assert edges[0]["portName"] == "report"
    assert edges[0]["stepId"] == "summarize"
    assert edges[0]["contentHash"] == artifact["sha256"]
    assert artifact["artifactBlobId"] == edges[0]["artifactBlobId"]
    materializations = list_artifact_materializations(cfg, edges[0]["artifactBlobId"])
    assert len(materializations) == 1
    assert materializations[0]["storageBackend"] == "local"
    assert materializations[0]["storageUri"] == artifact_path.resolve().as_uri()
    lineage_edges = list_lineage_edges_for_run(cfg, "run_artifact_ledger")
    assert len(lineage_edges) == 1
    assert lineage_edges[0]["subjectKind"] == "run"
    assert lineage_edges[0]["subjectId"] == "run_artifact_ledger"
    assert lineage_edges[0]["predicate"] == "prov:generated"
    assert lineage_edges[0]["objectKind"] == "artifact_blob"
    assert lineage_edges[0]["objectId"] == artifact["artifactBlobId"]
    assert lineage_edges[0]["contentHash"] == artifact["sha256"]
    assert lineage_edges[0]["payload"]["artifactKey"] == "report"
    assert artifact["lineageEdgeId"] == lineage_edges[0]["lineageEdgeId"]


def test_persist_artifact_records_materialization_evidence_event(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_artifact_evidence")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_text("accepted\n", encoding="utf-8")

    artifact = persist_artifact(
        cfg,
        run_id="run_artifact_evidence",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )

    events = list_evidence_events(
        cfg,
        subject_kind="artifact_blob",
        subject_id=artifact["artifactBlobId"],
    )
    lineage_edges = list_lineage_edges_for_run(cfg, "run_artifact_evidence")

    assert [event["eventType"] for event in events] == ["artifact.materialization.v1"]
    assert artifact["evidenceEventId"] == events[0]["eventId"]
    assert lineage_edges[0]["evidenceEventId"] == events[0]["eventId"]
    assert events[0]["schema"]["name"] == "ArtifactMaterializationEvidence"
    assert events[0]["payload"]["runId"] == "run_artifact_evidence"
    assert events[0]["payload"]["artifactId"] == artifact["artifactId"]
    assert events[0]["payload"]["artifactKey"] == "report"
    assert events[0]["payload"]["materializationId"] == artifact["materializationId"]
    assert events[0]["payload"]["storageBackend"] == "local"
    assert events[0]["payload"]["storageUri"] == artifact_path.resolve().as_uri()
    assert events[0]["payload"]["sha256"] == artifact["sha256"]


def test_stale_attempt_cannot_publish_official_artifact(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_stale_artifact", execution={"retryPolicy": {"backoffSeconds": 0}})
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2099-06-07T10:00:00Z", lease_seconds=10)
    run_active_reconciler_once(
        cfg,
        now="2099-06-07T10:00:11Z",
        retry_delay_seconds=0,
    )
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2099-06-07T10:00:11Z", lease_seconds=10)
    artifact_path = tmp_path / "stale-result.txt"
    artifact_path.write_text("stale output\n", encoding="utf-8")
    assert first is not None
    assert second is not None

    with pytest.raises(StaleRunAttemptError) as raised:
        persist_artifact(
            cfg,
            run_id="run_stale_artifact",
            kind="report",
            path=artifact_path,
            mime_type="text/plain",
            attempt_id=first["attemptId"],
            lease_generation=first["leaseGeneration"],
        )

    assert str(raised.value) == "RUN_ATTEMPT_STALE"
    assert fetch_run_results(cfg, "run_stale_artifact")["artifacts"] == []


def test_legacy_artifact_table_gets_storage_columns(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute("DROP TABLE artifacts")
        connection.execute(
            """
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()

    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(artifacts)").fetchall()}

    assert "storage_backend" in columns
    assert "storage_uri" in columns
