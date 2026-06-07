from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.artifact_ledger_storage import list_artifact_materializations, list_run_artifact_edges
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from tests.helpers.reference_database import make_configured_remote_runner


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact",
            "pipelineId": "pipeline_artifact",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
        },
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


def test_stale_attempt_cannot_publish_official_artifact(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_stale_artifact")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)
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
