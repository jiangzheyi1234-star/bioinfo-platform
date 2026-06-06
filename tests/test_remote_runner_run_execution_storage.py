from __future__ import annotations

from pathlib import Path

from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.run_execution_storage import (
    claim_next_run_job,
    complete_run_attempt,
    heartbeat_run_attempt,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict[str, str]:
    return {
        "runId": run_id,
        "projectId": "proj_jobs",
        "pipelineId": "pipeline_jobs",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def _create_run(cfg, run_id: str = "run_jobs"):
    return create_run_record(
        cfg,
        server_id="srv_jobs",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id),
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def test_create_run_record_enqueues_one_job_and_replay_does_not_duplicate(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    first = _create_run(cfg, "run_enqueue")
    replay = create_run_record(
        cfg,
        server_id="srv_jobs",
        request_id="req_replay",
        run_spec=_run_spec("run_enqueue_replay"),
        idempotency_key="idem_run_enqueue",
        payload_hash="hash_run_enqueue",
    )

    assert first.created is True
    assert replay.created is False
    with get_connection(cfg) as connection:
        job_count = connection.execute("SELECT COUNT(*) AS count FROM run_jobs").fetchone()["count"]
        event_types = [
            row["event_type"]
            for row in connection.execute("SELECT event_type FROM run_events ORDER BY rowid").fetchall()
        ]
    assert job_count == 1
    assert event_types == ["accepted", "run_job_queued"]


def test_claim_next_job_creates_attempt_with_current_lease_and_work_dir(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_claim")

    claim = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2026-06-07T10:00:00Z",
        lease_seconds=30,
    )

    assert claim is not None
    assert claim["runId"] == "run_claim"
    assert claim["leaseGeneration"] == 1
    assert claim["lease"]["expiresAt"] == "2026-06-07T10:00:30Z"
    assert claim["attempt"]["workerId"] == "worker_a"
    assert Path(claim["attempt"]["workDir"]).parent == Path(cfg.work_dir) / "attempts"

    with get_connection(cfg) as connection:
        job = connection.execute("SELECT state FROM run_jobs WHERE run_id = ?", ("run_claim",)).fetchone()
        event = connection.execute(
            "SELECT event_type FROM run_events WHERE event_type = ?",
            ("run_attempt_claimed",),
        ).fetchone()
    assert job["state"] == "claimed"
    assert event["event_type"] == "run_attempt_claimed"


def test_two_workers_cannot_claim_same_unexpired_job(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_single_claim")

    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=30)
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:10Z", lease_seconds=30)

    assert first is not None
    assert second is None


def test_expired_lease_reclaim_fences_old_attempt_and_increments_generation(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_reclaim")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)

    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)

    assert first is not None
    assert second is not None
    assert second["leaseGeneration"] == 2
    assert second["attempt"]["workDir"] != first["attempt"]["workDir"]
    with get_connection(cfg) as connection:
        old_attempt = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (first["attemptId"],),
        ).fetchone()
    assert old_attempt["state"] == "fenced"
    assert old_attempt["fenced_reason"] == "lease_expired"


def test_old_heartbeat_and_completion_are_fenced_after_reclaim(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_stale_attempt")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)
    assert first is not None
    assert second is not None

    heartbeat = heartbeat_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        now="2026-06-07T10:00:12Z",
    )
    completion = complete_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        state="succeeded",
        exit_code=0,
        now="2026-06-07T10:00:13Z",
    )

    assert heartbeat["accepted"] is False
    assert heartbeat["reason"] == "stale_generation"
    assert completion["accepted"] is False
    assert completion["reason"] == "stale_generation"
    run = fetch_run(cfg, "run_stale_attempt")
    assert run["status"] == "queued"


def test_current_attempt_completion_marks_job_and_lease_terminal(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_complete_attempt")
    claim = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None

    completion = complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="succeeded",
        exit_code=0,
        now="2026-06-07T10:00:05Z",
    )

    assert completion["accepted"] is True
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state FROM run_jobs WHERE run_id = ?",
            ("run_complete_attempt",),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_complete_attempt",),
        ).fetchone()
    assert job["state"] == "completed"
    assert lease["state"] == "completed"
