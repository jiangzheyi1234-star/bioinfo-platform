from __future__ import annotations

import sqlite3

from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_worker_storage import (
    build_run_worker_health,
    heartbeat_run_worker,
    heartbeat_run_worker_slot,
    mark_run_worker_stopped,
    register_run_worker_slot,
    register_run_worker,
    request_run_worker_drain,
    run_worker_is_draining,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_worker_storage_migrates_legacy_worker_rows(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    legacy = sqlite3.connect(str(cfg.db_path))
    legacy.execute("CREATE TABLE run_workers (worker_id TEXT PRIMARY KEY)")
    legacy.close()

    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(run_workers)").fetchall()}

    assert {
        "session_id",
        "pid",
        "hostname",
        "state",
        "queue_name",
        "concurrency_limit",
        "current_attempt_id",
        "heartbeat_at",
        "last_error_json",
        "drain_requested_at",
        "started_at",
        "stopped_at",
        "updated_at",
    }.issubset(columns)


def test_run_worker_register_heartbeat_drain_and_stop_are_visible_in_health(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    registered = register_run_worker(
        cfg,
        worker_id="worker-a",
        session_id="session-a",
        pid=123,
        hostname="host-a",
        now="2099-06-07T10:00:00Z",
    )
    running = heartbeat_run_worker(
        cfg,
        worker_id="worker-a",
        session_id="session-a",
        state="running",
        current_attempt_id="att_123",
        last_error={"code": "LAST_TRANSIENT_ERROR"},
        now="2099-06-07T10:00:05Z",
    )
    draining = request_run_worker_drain(cfg, "worker-a", now="2099-06-07T10:00:06Z")

    health = build_run_worker_health(cfg, now="2099-06-07T10:00:08Z")

    assert registered["state"] == "idle"
    assert running["currentAttemptId"] == "att_123"
    assert draining["draining"] is True
    assert run_worker_is_draining(cfg, "worker-a") is True
    assert health["queueDepth"] == 0
    assert health["claimedJobs"] == 0
    assert health["workers"] == [
        {
            "workerId": "worker-a",
            "sessionId": "session-a",
            "pid": 123,
            "hostname": "host-a",
            "state": "running",
            "queueName": "default",
            "concurrencyLimit": 1,
            "currentAttemptId": "att_123",
            "heartbeatAt": "2099-06-07T10:00:05Z",
            "heartbeatAgeSeconds": 3,
            "lastError": {"code": "LAST_TRANSIENT_ERROR"},
            "drainRequestedAt": "2099-06-07T10:00:06Z",
            "draining": True,
            "startedAt": "2099-06-07T10:00:00Z",
            "stoppedAt": None,
            "updatedAt": "2099-06-07T10:00:06Z",
            "slots": [],
        }
    ]

    stopped = mark_run_worker_stopped(
        cfg,
        worker_id="worker-a",
        session_id="session-a",
        now="2099-06-07T10:00:09Z",
    )

    assert stopped["state"] == "stopped"
    assert stopped["currentAttemptId"] is None
    assert stopped["stoppedAt"] == "2099-06-07T10:00:09Z"


def test_run_worker_rejects_stale_session_heartbeat(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-session",
        session_id="session-old",
        pid=111,
        hostname="host",
        now="2099-06-07T10:00:00Z",
    )
    register_run_worker(
        cfg,
        worker_id="worker-session",
        session_id="session-new",
        pid=222,
        hostname="host",
        now="2099-06-07T10:00:05Z",
    )

    stale = heartbeat_run_worker(
        cfg,
        worker_id="worker-session",
        session_id="session-old",
        state="running",
        current_attempt_id="att_old",
        now="2099-06-07T10:00:06Z",
    )
    current = build_run_worker_health(cfg, now="2099-06-07T10:00:07Z")["workers"][0]

    assert stale == {"accepted": False, "reason": "stale_session", "currentSessionId": "session-new"}
    assert current["sessionId"] == "session-new"
    assert current["currentAttemptId"] is None


def test_run_worker_slots_have_independent_state_and_stale_session_fencing(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        pid=333,
        hostname="host",
        concurrency_limit=2,
        now="2099-06-07T10:00:00Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        slot_id="slot-0",
        now="2099-06-07T10:00:01Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        slot_id="slot-1",
        now="2099-06-07T10:00:01Z",
    )
    heartbeat_run_worker_slot(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        slot_id="slot-0",
        state="running",
        current_attempt_id="att_slot_0",
        now="2099-06-07T10:00:02Z",
    )
    heartbeat_run_worker_slot(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        slot_id="slot-1",
        state="idle",
        current_attempt_id=None,
        now="2099-06-07T10:00:03Z",
    )
    register_run_worker(
        cfg,
        worker_id="worker-slots",
        session_id="session-b",
        pid=444,
        hostname="host",
        concurrency_limit=2,
        now="2099-06-07T10:00:04Z",
    )

    stale = heartbeat_run_worker_slot(
        cfg,
        worker_id="worker-slots",
        session_id="session-a",
        slot_id="slot-0",
        state="running",
        current_attempt_id="att_stale",
        now="2099-06-07T10:00:05Z",
    )
    health = build_run_worker_health(cfg, now="2099-06-07T10:00:06Z")

    assert stale == {"accepted": False, "reason": "stale_session", "currentSessionId": "session-b"}
    assert health["workers"][0]["sessionId"] == "session-b"
    slots = {slot["slotId"]: slot for slot in health["workers"][0]["slots"]}
    assert slots["slot-0"]["currentAttemptId"] is None
    assert slots["slot-1"]["currentAttemptId"] is None


def test_run_worker_health_reports_queue_depth_and_claimed_jobs(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="srv_worker_health",
        request_id="req_worker_health",
        run_spec={
            "runId": "run_worker_health",
            "projectId": "proj_worker_health",
            "pipelineId": "pipeline_worker_health",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key="idem_worker_health",
        payload_hash="hash_worker_health",
    )
    register_run_worker(
        cfg,
        worker_id="worker-health",
        session_id="session-health",
        pid=456,
        hostname="host-health",
        now="2099-06-07T10:00:00Z",
    )

    queued = build_run_worker_health(cfg, now="2999-01-01T00:00:00Z")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-health",
        now="2999-01-01T00:00:01Z",
        lease_seconds=60,
    )
    heartbeat_run_worker(
        cfg,
        worker_id="worker-health",
        session_id="session-health",
        state="running",
        current_attempt_id=claim["attemptId"],
        now="2999-01-01T00:00:02Z",
    )
    claimed = build_run_worker_health(cfg, now="2999-01-01T00:00:03Z")

    assert queued["queueDepth"] == 1
    assert queued["claimedJobs"] == 0
    assert claimed["queueDepth"] == 0
    assert claimed["claimedJobs"] == 1
    assert claimed["workers"][0]["currentAttemptId"] == claim["attemptId"]
