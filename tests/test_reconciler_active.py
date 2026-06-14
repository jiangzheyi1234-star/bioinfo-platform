from __future__ import annotations

import logging

from apps.remote_runner.reconciler import run_active_reconciler_once
from apps.remote_runner import reconciler
from apps.remote_runner.execution_diagnostics import build_execution_diagnostics
from apps.remote_runner.metrics import collect_queue_metrics
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_worker_storage import register_run_worker, register_run_worker_slot
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict:
    return {
        "runId": run_id,
        "projectId": "proj_reconcile",
        "pipelineId": "pipeline_reconcile",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def _create_run(cfg, run_id: str, *, execution: dict | None = None):
    run_spec = _run_spec(run_id)
    if execution is not None:
        run_spec["execution"] = execution
    result = create_run_record(
        cfg,
        server_id="srv_reconcile",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_jobs SET available_at = ?, created_at = ?, updated_at = ? WHERE run_id = ?",
            (
                "2099-06-07T10:00:00Z",
                "2099-06-07T10:00:00Z",
                "2099-06-07T10:00:00Z",
                run_id,
            ),
        )
        connection.commit()
    return result


def _register_worker_slot(cfg, *, worker_id: str, session_id: str, slot_id: str) -> None:
    register_run_worker(
        cfg,
        worker_id=worker_id,
        session_id=session_id,
        pid=789,
        hostname=f"host-{worker_id}",
        now="2099-06-07T09:59:59Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id=worker_id,
        session_id=session_id,
        slot_id=slot_id,
        now="2099-06-07T09:59:59Z",
    )


def test_active_reconciler_fences_expired_lease_and_requeues_retryable_job(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_retry")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None
    assert claim["attempt"]["attemptNumber"] == 1

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    recovery_actions = [a for a in actions if a.get("type") == "run_attempt_recovered"]
    assert len(recovery_actions) == 1
    assert recovery_actions[0]["action"] == "requeued"
    assert recovery_actions[0]["runId"] == "run_retry"

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_retry",),
        ).fetchone()
        job = connection.execute(
            "SELECT state, attempt_count, dead_lettered_at FROM run_jobs WHERE run_id = ?",
            ("run_retry",),
        ).fetchone()
        allocation = connection.execute(
            "SELECT state, released_at FROM run_resource_allocations WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
    assert attempt["state"] == "fenced"
    assert attempt["fenced_reason"] == "lease_expired"
    assert lease["state"] == "expired"
    assert job["state"] == "queued"
    assert job["attempt_count"] == 1
    assert job["dead_lettered_at"] is None
    assert allocation["state"] == "released"
    assert allocation["released_at"] == "2099-06-07T10:00:11Z"
    assert collect_queue_metrics(cfg)["recovery"]["requeuedJobs"] == 1
    assert collect_queue_metrics(cfg)["recovery"]["controlPlaneRecoveries"] == 1


def test_active_reconciler_uses_retry_backoff_policy(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_backoff", execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 17}})
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_backoff",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z", retry_delay_seconds=5)

    recovery = next(action for action in actions if action.get("type") == "run_attempt_recovered")
    assert recovery["availableAt"] == "2099-06-07T10:00:28Z"
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT available_at FROM run_jobs WHERE run_id = ?", ("run_backoff",)).fetchone()
        event = connection.execute(
            "SELECT details_json FROM run_events WHERE run_id = ? AND event_type = ?",
            ("run_backoff", "run_job_requeued"),
        ).fetchone()
    assert job["available_at"] == "2099-06-07T10:00:28Z"
    assert '"backoffSeconds":17' in event["details_json"]


def test_active_reconciler_dead_letters_queued_job_after_queue_ttl(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_queue_ttl", execution={"timeoutPolicy": {"queueTtlSeconds": 5}})

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:05Z")

    assert any(
        action.get("action") == "dead_letter_queue_ttl_exceeded"
        and action.get("reasonCode") == "QUEUE_TTL_EXCEEDED"
        for action in actions
    )
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state, dead_lettered_at FROM run_jobs WHERE run_id = ?",
            ("run_queue_ttl",),
        ).fetchone()
        run = connection.execute("SELECT status, stage FROM runs WHERE run_id = ?", ("run_queue_ttl",)).fetchone()
        recovery = connection.execute(
            "SELECT details_json FROM run_events WHERE run_id = ? AND event_type = ?",
            ("run_queue_ttl", "run_control_plane_recovered"),
        ).fetchone()
    assert job["state"] == "failed"
    assert job["dead_lettered_at"] == "2099-06-07T10:00:05Z"
    assert run["status"] == "failed"
    assert run["stage"] == "dead_letter"
    assert "QUEUE_TTL_EXCEEDED" in recovery["details_json"]


def test_active_reconciler_fences_attempt_after_start_to_close_timeout(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_attempt_timeout",
        execution={"timeoutPolicy": {"startToCloseTimeoutSeconds": 5}},
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_timeout",
        now="2099-06-07T10:00:00Z",
        lease_seconds=60,
    )
    assert claim is not None

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:05Z")

    recovery = next(action for action in actions if action.get("type") == "run_attempt_recovered")
    assert recovery["reasonCode"] == "ATTEMPT_TIMEOUT"
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        lease = connection.execute("SELECT state FROM run_leases WHERE run_id = ?", ("run_attempt_timeout",)).fetchone()
        recovery_event = connection.execute(
            "SELECT details_json FROM run_events WHERE run_id = ? AND event_type = ?",
            ("run_attempt_timeout", "run_control_plane_recovered"),
        ).fetchone()
    assert attempt["state"] == "fenced"
    assert attempt["fenced_reason"] == "attempt_timeout"
    assert lease["state"] == "fenced"
    assert "ATTEMPT_TIMEOUT" in recovery_event["details_json"]


def test_active_reconciler_marks_slot_idle_and_reports_recovery_evidence(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_slot_recovery")
    _register_worker_slot(cfg, worker_id="worker_slot", session_id="session_slot", slot_id="slot-0")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_slot",
        session_id="session_slot",
        slot_id="slot-0",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    assert any(
        action.get("type") == "run_attempt_recovered"
        and action.get("reasonCode") == "LEASE_EXPIRED"
        for action in actions
    )
    with get_connection(cfg) as connection:
        slot = connection.execute(
            "SELECT state, current_attempt_id FROM run_worker_slots WHERE worker_id = ? AND slot_id = ?",
            ("worker_slot", "slot-0"),
        ).fetchone()
    assert slot["state"] == "idle"
    assert slot["current_attempt_id"] is None

    diagnostics = build_execution_diagnostics(cfg, run_ids=["run_slot_recovery"])
    recovery = diagnostics["recoveryEvidence"]
    assert any(
        event["eventType"] == "run_control_plane_recovered"
        and event["payload"]["action"] == "requeue_after_lease_expiry"
        and event["payload"]["reasonCode"] == "LEASE_EXPIRED"
        for event in recovery
    )
    assert diagnostics["readiness"]["ok"] is True


def test_active_reconciler_closes_terminal_attempt_active_lease(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_terminal_lease")
    _register_worker_slot(cfg, worker_id="worker_terminal", session_id="session_terminal", slot_id="slot-0")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_terminal",
        session_id="session_terminal",
        slot_id="slot-0",
        now="2099-06-07T10:00:00Z",
        lease_seconds=60,
    )
    assert claim is not None
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET status = ?, stage = ?, last_updated_at = ? WHERE run_id = ?",
            ("completed", "finalize", "2099-06-07T10:00:05Z", "run_terminal_lease"),
        )
        connection.execute(
            """
            UPDATE run_attempts
            SET state = ?, finished_at = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            ("succeeded", "2099-06-07T10:00:05Z", "2099-06-07T10:00:05Z", claim["attemptId"]),
        )
        connection.commit()

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:06Z")

    assert any(
        action.get("action") == "close_active_lease_without_running_attempt"
        and action.get("reasonCode") == "ACTIVE_LEASE_WITHOUT_RUNNING_ATTEMPT"
        for action in actions
    )
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state FROM run_jobs WHERE run_id = ?",
            ("run_terminal_lease",),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_terminal_lease",),
        ).fetchone()
        allocation = connection.execute(
            "SELECT state FROM run_resource_allocations WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        slot = connection.execute(
            "SELECT state, current_attempt_id FROM run_worker_slots WHERE worker_id = ? AND slot_id = ?",
            ("worker_terminal", "slot-0"),
        ).fetchone()
    assert job["state"] == "completed"
    assert lease["state"] == "completed"
    assert allocation["state"] == "released"
    assert slot["state"] == "idle"
    assert slot["current_attempt_id"] is None
    assert build_execution_diagnostics(cfg, run_ids=["run_terminal_lease"])["ok"] is True


def test_active_reconciler_requeues_claimed_job_without_active_lease(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_claimed_without_lease")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_orphan",
        now="2099-06-07T10:00:00Z",
        lease_seconds=60,
    )
    assert claim is not None
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_leases SET state = ?, updated_at = ? WHERE run_id = ?",
            ("fenced", "2099-06-07T10:00:05Z", "run_claimed_without_lease"),
        )
        connection.commit()

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:06Z")

    assert any(
        action.get("action") == "requeue_claimed_job_without_active_lease"
        and action.get("reasonCode") == "CLAIMED_JOB_WITHOUT_ACTIVE_LEASE"
        for action in actions
    )
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state, attempt_count FROM run_jobs WHERE run_id = ?",
            ("run_claimed_without_lease",),
        ).fetchone()
        allocation = connection.execute(
            "SELECT state FROM run_resource_allocations WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
    assert job["state"] == "queued"
    assert job["attempt_count"] == 1
    assert allocation["state"] == "released"


def test_active_reconciler_dead_letters_exhausted_job(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_exhaust")

    claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    claim2 = claim_next_run_job(
        cfg,
        worker_id="worker_b",
        now="2099-06-07T10:01:00Z",
        lease_seconds=10,
    )
    assert claim2["attempt"]["attemptNumber"] == 2
    run_active_reconciler_once(cfg, now="2099-06-07T10:01:11Z")

    claim3 = claim_next_run_job(
        cfg,
        worker_id="worker_c",
        now="2099-06-07T10:02:00Z",
        lease_seconds=10,
    )
    assert claim3["attempt"]["attemptNumber"] == 3
    run_active_reconciler_once(cfg, now="2099-06-07T10:02:11Z")

    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state, attempt_count, dead_lettered_at FROM run_jobs WHERE run_id = ?",
            ("run_exhaust",),
        ).fetchone()
        run = connection.execute(
            "SELECT status, stage FROM runs WHERE run_id = ?",
            ("run_exhaust",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_type FROM run_events WHERE event_type = ? AND run_id = ?",
            ("run_job_dead_lettered", "run_exhaust"),
        ).fetchone()
    assert job["state"] == "failed"
    assert job["attempt_count"] == 3
    assert job["dead_lettered_at"] is not None
    assert run["status"] == "failed"
    assert run["stage"] == "dead_letter"
    assert event is not None


def test_active_reconciler_is_idempotent(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_idem")
    claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )

    actions1 = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")
    actions2 = run_active_reconciler_once(cfg, now="2099-06-07T10:00:12Z")

    recovery1 = [a for a in actions1 if a.get("type") == "run_attempt_recovered"]
    recovery2 = [a for a in actions2 if a.get("type") == "run_attempt_recovered"]
    assert len(recovery1) == 1
    assert len(recovery2) == 0

    with get_connection(cfg) as connection:
        events = connection.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE event_type = ? AND run_id = ?",
            ("run_attempt_fenced", "run_idem"),
        ).fetchone()
    assert events["count"] == 1


def test_active_reconciler_handles_worker_crash_recovery(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_crash")

    claim1 = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    attempt1_id = claim1["attemptId"]

    run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    claim2 = claim_next_run_job(
        cfg,
        worker_id="worker_b",
        now="2099-06-07T10:01:00Z",
        lease_seconds=10,
    )
    attempt2_id = claim2["attemptId"]
    assert attempt2_id != attempt1_id

    with get_connection(cfg) as connection:
        attempt1 = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (attempt1_id,),
        ).fetchone()
        attempt2 = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (attempt2_id,),
        ).fetchone()
        lease = connection.execute(
            "SELECT attempt_id, lease_generation FROM run_leases WHERE run_id = ?",
            ("run_crash",),
        ).fetchone()
    assert attempt1["state"] == "fenced"
    assert attempt1["fenced_reason"] == "lease_expired"
    assert attempt2["state"] == "running"
    assert attempt2["fenced_reason"] is None
    assert lease["attempt_id"] == attempt2_id
    assert lease["lease_generation"] == 2


def test_active_reconciler_logs_attempt_and_slot_context(tmp_path, caplog):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_reconciler_log")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_log",
        session_id="session_log",
        slot_id="slot-log",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None

    with caplog.at_level(logging.INFO, logger="apps.remote_runner.reconciler"):
        run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    record = next(record for record in caplog.records if record.message.startswith("Fenced attempt termination checked"))
    assert "run_reconciler_log" in record.message
    assert claim["attemptId"] in record.message
    assert "slot-log" in record.message
    assert record.runId == "run_reconciler_log"
    assert record.attemptId == claim["attemptId"]
    assert record.slotId == "slot-log"


def test_active_reconciler_detects_clock_jump(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    for index in range(3):
        run_id = f"run_clock_{index}"
        _create_run(cfg, run_id)
        claim_next_run_job(
            cfg,
            worker_id=f"worker_{index}",
            max_active_slots=3,
            now="2099-06-07T10:00:00Z",
            lease_seconds=10,
        )

    actions = run_active_reconciler_once(
        cfg,
        now="2099-06-07T10:10:00Z",
        clock_jump_expiry_threshold=3,
    )

    clock_jump = next((a for a in actions if a.get("type") == "clock_jump_suspected"), None)
    assert clock_jump is not None
    assert clock_jump["expiredLeaseCount"] == 3
    assert clock_jump["threshold"] == 3


def test_active_reconciler_does_not_touch_valid_lease(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_valid")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=60,
    )

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:30Z")

    recovery_actions = [a for a in actions if a.get("type") == "run_attempt_recovered"]
    assert len(recovery_actions) == 0

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_valid",),
        ).fetchone()
    assert attempt["state"] == "running"
    assert attempt["fenced_reason"] is None
    assert lease["state"] == "active"


def test_active_reconciler_terminates_outside_fencing_transaction(tmp_path, monkeypatch):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_transaction_boundary")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )

    def terminate_while_writing(_process_group_id):
        with get_connection(cfg) as connection:
            connection.execute(
                "UPDATE run_attempts SET killed_at = ? WHERE attempt_id = ?",
                ("2099-06-07T10:00:12Z", claim["attemptId"]),
            )
            connection.commit()
        return {"terminated": True, "confirmedStopped": True}

    monkeypatch.setattr(reconciler, "terminate_process_group", terminate_while_writing)

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    assert actions[0]["action"] == "requeued"
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, killed_at FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
    assert attempt["state"] == "fenced"
    assert attempt["killed_at"] == "2099-06-07T10:00:12Z"


def test_active_reconciler_does_not_requeue_until_termination_is_confirmed(tmp_path, monkeypatch):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_termination_blocked")
    claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    monkeypatch.setattr(
        reconciler,
        "terminate_process_group",
        lambda _process_group_id: {"terminated": False, "reason": "permission_denied"},
    )

    actions = run_active_reconciler_once(cfg, now="2099-06-07T10:00:11Z")

    assert actions == [
        {
            "type": "run_attempt_recovery_blocked",
            "runId": "run_termination_blocked",
            "jobId": actions[0]["jobId"],
            "attemptId": actions[0]["attemptId"],
            "reason": "permission_denied",
        }
    ]
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state FROM run_jobs WHERE run_id = ?",
            ("run_termination_blocked",),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_termination_blocked",),
        ).fetchone()
        event = connection.execute(
            """
            SELECT event_type, details_json
            FROM run_events
            WHERE run_id = ? AND event_type = 'run_attempt_recovery_blocked'
            """,
            ("run_termination_blocked",),
        ).fetchone()
    assert job["state"] == "claimed"
    assert lease["state"] == "expired"
    assert event is not None
    assert event["event_type"] == "run_attempt_recovery_blocked"
    assert "permission_denied" in event["details_json"]
    assert collect_queue_metrics(cfg)["recovery"]["recoveryBlocked"] == 1
