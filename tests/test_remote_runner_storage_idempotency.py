from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.api_models import RunCreateRequest
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage import create_run_record
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
