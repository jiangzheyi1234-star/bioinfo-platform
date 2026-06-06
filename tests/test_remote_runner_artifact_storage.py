from __future__ import annotations

from pathlib import Path

from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
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
