from __future__ import annotations

from apps.remote_runner.reconciler import run_shadow_reconciler_once
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict[str, str]:
    return {
        "runId": run_id,
        "projectId": "proj_reconcile",
        "pipelineId": "pipeline_reconcile",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def _create_run(cfg, run_id: str):
    return create_run_record(
        cfg,
        server_id="srv_reconcile",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id),
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def test_shadow_reconciler_observes_queued_job_without_claiming(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_waiting")

    observations = run_shadow_reconciler_once(cfg, now="2026-06-07T10:00:00Z")

    assert observations == [
        {
            "type": "run_job_claimable_observed",
            "runId": "run_waiting",
            "jobId": observations[0]["jobId"],
        }
    ]
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT state FROM run_jobs WHERE run_id = ?", ("run_waiting",)).fetchone()
    assert job["state"] == "queued"


def test_shadow_reconciler_observes_expired_lease_without_fencing(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_expired")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_a",
        now="2026-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None

    observations = run_shadow_reconciler_once(cfg, now="2026-06-07T10:00:11Z")

    assert observations == [
        {
            "type": "run_lease_expired_observed",
            "runId": "run_expired",
            "jobId": claim["jobId"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": 1,
            "expiresAt": "2026-06-07T10:00:10Z",
        }
    ]
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, fenced_reason FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        lease = connection.execute("SELECT state FROM run_leases WHERE run_id = ?", ("run_expired",)).fetchone()
        run = connection.execute("SELECT status FROM runs WHERE run_id = ?", ("run_expired",)).fetchone()
        event = connection.execute(
            "SELECT event_type FROM run_events WHERE event_type = ? AND run_id = ?",
            ("run_lease_expired_observed", "run_expired"),
        ).fetchone()
    assert attempt["state"] == "running"
    assert attempt["fenced_reason"] is None
    assert lease["state"] == "active"
    assert run["status"] == "queued"
    assert event["event_type"] == "run_lease_expired_observed"


def test_shadow_reconciler_reports_mass_expiry_as_clock_jump_suspected(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    for index in range(3):
        run_id = f"run_clock_{index}"
        _create_run(cfg, run_id)
        claim_next_run_job(
            cfg,
            worker_id=f"worker_{index}",
            now="2026-06-07T10:00:00Z",
            lease_seconds=10,
        )

    observations = run_shadow_reconciler_once(
        cfg,
        now="2026-06-07T10:10:00Z",
        clock_jump_expiry_threshold=3,
    )

    assert observations[0] == {
        "type": "clock_jump_suspected",
        "expiredLeaseCount": 3,
        "threshold": 3,
    }
    assert [item["type"] for item in observations[1:]] == [
        "run_lease_expired_observed",
        "run_lease_expired_observed",
        "run_lease_expired_observed",
    ]
    with get_connection(cfg) as connection:
        lease_states = [
            row["state"]
            for row in connection.execute("SELECT state FROM run_leases ORDER BY run_id").fetchall()
        ]
        event = connection.execute(
            "SELECT event_type FROM run_events WHERE event_type = ? LIMIT 1",
            ("clock_jump_suspected",),
        ).fetchone()
    assert lease_states == ["active", "active", "active"]
    assert event["event_type"] == "clock_jump_suspected"
