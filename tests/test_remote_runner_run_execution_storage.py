from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError, update_run_state
from apps.remote_runner.run_execution_storage import (
    claim_next_run_job,
    complete_run_attempt,
    heartbeat_run_attempt,
    record_run_attempt_process_group,
    request_run_cancel,
    run_attempt_cancel_requested,
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


def test_run_execution_storage_migrates_retry_timeout_and_publish_columns(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    legacy = sqlite3.connect(str(cfg.db_path))
    legacy.executescript(
        """
        CREATE TABLE run_jobs (
            job_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            state TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id)
        );
        CREATE TABLE run_attempts (
            attempt_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            lease_generation INTEGER NOT NULL,
            state TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            work_dir TEXT NOT NULL,
            process_group_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            fenced_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    legacy.close()

    with get_connection(cfg) as connection:
        job_columns = _column_names(connection, "run_jobs")
        attempt_columns = _column_names(connection, "run_attempts")

    assert {
        "queue_name",
        "attempt_count",
        "max_attempts",
        "retry_policy_json",
        "timeout_policy_json",
        "dead_lettered_at",
    }.issubset(job_columns)
    assert {
        "attempt_number",
        "process_pid",
        "cancel_requested_at",
        "killed_at",
        "output_adoption_state",
    }.issubset(attempt_columns)


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
    assert claim["job"]["queueName"] == "default"
    assert claim["job"]["attemptCount"] == 1
    assert claim["job"]["maxAttempts"] == 3
    assert claim["job"]["retryPolicy"] == {}
    assert claim["job"]["timeoutPolicy"] == {}
    assert claim["attempt"]["workerId"] == "worker_a"
    assert claim["attempt"]["attemptNumber"] == 1
    assert claim["attempt"]["outputAdoptionState"] == "pending"
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
    assert second["job"]["attemptCount"] == 2
    assert second["attempt"]["attemptNumber"] == 2
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


def test_process_group_recording_is_fenced_by_current_generation(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_process_group")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)
    assert first is not None

    accepted = record_run_attempt_process_group(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        process_group_id="4242",
    )
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)
    assert second is not None
    rejected = record_run_attempt_process_group(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        process_group_id="9999",
    )

    assert accepted == {"accepted": True, "processGroupId": "4242"}
    assert rejected == {"accepted": False, "reason": "stale_generation"}
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT process_group_id, process_pid FROM run_attempts WHERE attempt_id = ?",
            (first["attemptId"],),
        ).fetchone()
    assert attempt["process_group_id"] == "4242"
    assert attempt["process_pid"] == 4242


def test_request_run_cancel_records_command_event_and_marks_active_attempt(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_cancel")
    claim = claim_next_run_job(cfg, worker_id="worker_cancel", now="2026-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None

    result = request_run_cancel(
        cfg,
        "run_cancel",
        actor="api-test",
        command_id="cmd_cancel_run",
        now="2026-06-07T10:00:05Z",
    )

    assert result == {
        "runId": "run_cancel",
        "status": "canceling",
        "stage": "cancel",
        "commandId": "cmd_cancel_run",
        "attemptId": claim["attemptId"],
        "cancelRequestedAt": "2026-06-07T10:00:05Z",
    }
    assert run_attempt_cancel_requested(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    ) is True
    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage, state_version FROM runs WHERE run_id = ?",
            ("run_cancel",),
        ).fetchone()
        attempt = connection.execute(
            "SELECT cancel_requested_at FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        command = connection.execute(
            "SELECT command_type, actor FROM run_commands WHERE command_id = ?",
            ("cmd_cancel_run",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_type, command_id FROM run_events WHERE event_type = ?",
            ("run_cancel_requested",),
        ).fetchone()
    assert dict(run) == {"status": "canceling", "stage": "cancel", "state_version": 2}
    assert attempt["cancel_requested_at"] == "2026-06-07T10:00:05Z"
    assert dict(command) == {"command_type": "cancel_run", "actor": "api-test"}
    assert dict(event) == {"event_type": "run_cancel_requested", "command_id": "cmd_cancel_run"}


def test_run_attempt_cancel_requested_treats_stale_generation_as_cancelled(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_stale_cancel_check")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)
    assert first is not None
    assert second is not None

    assert run_attempt_cancel_requested(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
    ) is True
    assert run_attempt_cancel_requested(
        cfg,
        second["attemptId"],
        lease_generation=second["leaseGeneration"],
    ) is False


def test_stale_attempt_cannot_update_run_projection(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_stale_projection")
    first = claim_next_run_job(cfg, worker_id="worker_a", now="2026-06-07T10:00:00Z", lease_seconds=10)
    second = claim_next_run_job(cfg, worker_id="worker_b", now="2026-06-07T10:00:11Z", lease_seconds=10)
    assert first is not None
    assert second is not None

    with pytest.raises(StaleRunAttemptError) as raised:
        update_run_state(
            cfg,
            run_id="run_stale_projection",
            status="completed",
            stage="finalize",
            message="Stale completion should not publish.",
            request_id="req_run_stale_projection",
            attempt_id=first["attemptId"],
            lease_generation=first["leaseGeneration"],
        )

    assert str(raised.value) == "RUN_ATTEMPT_STALE"
    run = fetch_run(cfg, "run_stale_projection")
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


def _column_names(connection, table_name: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
