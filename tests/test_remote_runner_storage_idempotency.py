from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from apps.remote_runner.api_models import RunCreateRequest
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage import create_run_record, fetch_run
from apps.remote_runner.submission_service import create_run_from_request
from tests.helpers.remote_runner_control_plane import _write_file_summary_pipeline
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict[str, str]:
    return {
        "runId": run_id,
        "projectId": "proj_idem",
        "pipelineId": "pipeline_idem",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def test_idempotency_key_reuse_with_different_payload_raises_domain_error(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    create_run_record(
        cfg,
        server_id="srv_idem",
        request_id="req_idem_first",
        run_spec=_run_spec("run_idem_first"),
        idempotency_key="idem_same",
        payload_hash="payload_hash_first",
    )

    with pytest.raises(IdempotencyKeyReusedError) as raised:
        create_run_record(
            cfg,
            server_id="srv_idem",
            request_id="req_idem_second",
            run_spec=_run_spec("run_idem_second"),
            idempotency_key="idem_same",
            payload_hash="payload_hash_second",
        )

    assert str(raised.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
    assert raised.value.status_code == 422


def test_run_storage_migrates_workflow_revision_id_column(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    legacy = sqlite3.connect(str(cfg.db_path))
    legacy.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            pipeline_id TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            run_spec_version TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            state_version INTEGER NOT NULL,
            message TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            result_dir TEXT NOT NULL,
            last_error_json TEXT,
            last_updated_at TEXT NOT NULL,
            request_id TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            run_spec_json TEXT NOT NULL
        );
        """
    )
    legacy.close()

    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}

    assert "workflow_revision_id" in columns


def test_create_run_record_persists_top_level_workflow_revision_id(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_spec = {**_run_spec("run_revision_id"), "workflowRevisionId": "wfrev_idem"}

    created = create_run_record(
        cfg,
        server_id="srv_idem",
        request_id="req_revision_id",
        run_spec=run_spec,
        idempotency_key="idem_revision_id",
        payload_hash="payload_hash_revision_id",
    )
    fetched = fetch_run(cfg, "run_revision_id")

    assert created.run["workflowRevisionId"] == "wfrev_idem"
    assert fetched is not None
    assert fetched["workflowRevisionId"] == "wfrev_idem"
    assert fetched["runSpec"]["workflowRevisionId"] == "wfrev_idem"
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
            ("run_revision_id",),
        ).fetchone()
    assert row["workflow_revision_id"] == "wfrev_idem"


def test_create_run_record_reports_idempotency_replay_without_new_rows(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    first = create_run_record(
        cfg,
        server_id="srv_idem",
        request_id="req_idem_first",
        run_spec=_run_spec("run_idem_first"),
        idempotency_key="idem_same",
        payload_hash="payload_hash_first",
    )
    replay = create_run_record(
        cfg,
        server_id="srv_idem",
        request_id="req_idem_second",
        run_spec=_run_spec("run_idem_second"),
        idempotency_key="idem_same",
        payload_hash="payload_hash_first",
    )

    assert first.created is True
    assert first.reason == "created"
    assert replay.created is False
    assert replay.reason == "idempotency_replay"
    assert replay.run["runId"] == first.run["runId"]

    with get_connection(cfg) as connection:
        run_count = connection.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"]
        event_count = connection.execute("SELECT COUNT(*) AS count FROM run_events").fetchone()["count"]
        job_count = connection.execute("SELECT COUNT(*) AS count FROM run_jobs").fetchone()["count"]
    assert run_count == 1
    assert event_count == 2
    assert job_count == 1


def test_submission_records_durable_job_without_starting_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        managed_conda_command="python",
        snakemake_command="snakemake",
    )
    _write_file_summary_pipeline(Path(cfg.release_dir))

    monkeypatch.setattr("apps.remote_runner.submission_service.ensure_submission_ready", lambda cfg: None)
    monkeypatch.setattr("apps.remote_runner.submission_service.ensure_execution_admission_ready", lambda cfg: None)

    request = RunCreateRequest(
        serverId="srv_idem",
        requestId="req_idem",
        runSpec={
            "projectId": "proj_idem",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_demo"}],
        },
    )

    first = create_run_from_request(cfg, request, idempotency_key="idem_same", x_request_id="req_idem")
    replay = create_run_from_request(cfg, request, idempotency_key="idem_same", x_request_id="req_idem")

    assert first["data"]["runId"] == replay["data"]["runId"]
    with get_connection(cfg) as connection:
        job_rows = connection.execute(
            "SELECT state FROM run_jobs WHERE run_id = ?",
            (first["data"]["runId"],),
        ).fetchall()
    assert [row["state"] for row in job_rows] == ["queued"]
