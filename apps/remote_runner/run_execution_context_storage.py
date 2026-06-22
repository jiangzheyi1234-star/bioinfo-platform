from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .execution_policy import retry_policy_from_job, timeout_policy_from_job
from .execution_query_storage import require_run
from .storage_core import get_connection, now_iso


TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled", "cancelled"}
RETRYABLE_TERMINAL_RUN_STATUSES = {"failed", "canceled", "cancelled"}
TERMINAL_JOB_STATES = {"completed", "failed", "cancelled", "canceled"}


def fetch_run_execution_context(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    run = require_run(cfg, run_id)
    generated_at = now_iso()
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        attempts = connection.execute(
            """
            SELECT *
            FROM run_attempts
            WHERE run_id = ?
            ORDER BY attempt_number ASC, lease_generation ASC, created_at ASC
            """,
            (run_id,),
        ).fetchall()
        lease = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()

    job_payload = _job_context(job) if job is not None else None
    current_lease = _lease_context(lease) if lease is not None else None
    active_lease = current_lease if current_lease and current_lease["state"] == "active" else None
    return {
        "schemaVersion": "run-execution-context.v1",
        "runId": run_id,
        "generatedAt": generated_at,
        "run": _run_context(run),
        "job": job_payload,
        "attempts": [_attempt_context(row) for row in attempts],
        "currentLease": current_lease,
        "activeLease": active_lease,
        "retryPolicy": job_payload.get("retryPolicy") if job_payload else None,
        "timeoutPolicy": job_payload.get("timeoutPolicy") if job_payload else None,
        "retryEligibility": _retry_eligibility(
            run=run,
            job=job_payload,
            active_lease=active_lease,
            generated_at=generated_at,
        ),
        "resumeSupported": False,
        "resumeEligibility": {
            "eligible": False,
            "reasonCode": "RESUME_UNSUPPORTED",
            "message": "Run resume is not supported until durable artifact reuse is proven.",
        },
    }


def _run_context(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": run.get("status"),
        "stage": run.get("stage"),
        "stateVersion": run.get("stateVersion"),
        "message": run.get("message"),
        "startedAt": run.get("startedAt"),
        "finishedAt": run.get("finishedAt"),
        "lastUpdatedAt": run.get("lastUpdatedAt"),
    }


def _job_context(row: Any) -> dict[str, Any]:
    retry_policy = retry_policy_from_job(row).as_dict()
    timeout_policy = timeout_policy_from_job(row).as_dict()
    return {
        "jobId": row["job_id"],
        "runId": row["run_id"],
        "state": row["state"],
        "queueName": row["queue_name"],
        "priority": int(row["priority"]),
        "availableAt": row["available_at"],
        "waitReason": _json_object(row["wait_reason_json"]),
        "attemptCount": int(row["attempt_count"]),
        "maxAttempts": int(row["max_attempts"]),
        "retryPolicy": retry_policy,
        "timeoutPolicy": timeout_policy,
        "deadLetteredAt": row["dead_lettered_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _attempt_context(row: Any) -> dict[str, Any]:
    return {
        "attemptId": row["attempt_id"],
        "runId": row["run_id"],
        "jobId": row["job_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "attemptNumber": int(row["attempt_number"]),
        "state": row["state"],
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "slotId": row["slot_id"],
        "cancelRequestedAt": row["cancel_requested_at"],
        "killedAt": row["killed_at"],
        "outputAdoptionState": row["output_adoption_state"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "exitCode": row["exit_code"],
        "fencedReason": row["fenced_reason"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _lease_context(row: Any) -> dict[str, Any]:
    return {
        "runId": row["run_id"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "slotId": row["slot_id"],
        "heartbeatAt": row["heartbeat_at"],
        "expiresAt": row["expires_at"],
        "state": row["state"],
        "updatedAt": row["updated_at"],
    }


def _retry_eligibility(
    *,
    run: dict[str, Any],
    job: dict[str, Any] | None,
    active_lease: dict[str, Any] | None,
    generated_at: str,
) -> dict[str, Any]:
    if job is None:
        return _eligibility(False, False, 0, None, "JOB_NOT_FOUND")
    attempts = int(job["attemptCount"])
    max_attempts = int(job["maxAttempts"])
    remaining = max(0, max_attempts - attempts)
    next_attempt_at = job.get("availableAt")
    if job.get("deadLetteredAt") or remaining <= 0:
        return _eligibility(False, False, remaining, next_attempt_at, "MAX_ATTEMPTS_EXHAUSTED")
    run_status = str(run.get("status") or "").lower()
    job_state = str(job.get("state") or "").lower()
    if active_lease is not None:
        return _eligibility(False, False, remaining, next_attempt_at, "ACTIVE_LEASE")
    if run_status in RETRYABLE_TERMINAL_RUN_STATUSES and job_state in TERMINAL_JOB_STATES:
        return _eligibility(True, True, remaining, next_attempt_at, "RUN_RETRYABLE_TERMINAL")
    if run_status in TERMINAL_RUN_STATUSES or job_state in TERMINAL_JOB_STATES:
        return _eligibility(False, False, remaining, next_attempt_at, "RUN_TERMINAL")
    if job["state"] == "queued":
        eligible_now = not next_attempt_at or str(next_attempt_at) <= generated_at
        return _eligibility(True, eligible_now, remaining, next_attempt_at, "QUEUED" if eligible_now else "RETRY_BACKOFF")
    if job["state"] == "claimed":
        return _eligibility(False, False, remaining, next_attempt_at, "RECOVERY_REQUIRED")
    return _eligibility(False, False, remaining, next_attempt_at, "JOB_STATE_NOT_RETRYABLE")


def _eligibility(
    eligible: bool,
    eligible_now: bool,
    remaining_attempts: int,
    next_attempt_at: Any,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "eligible": eligible,
        "eligibleNow": eligible_now,
        "remainingAttempts": remaining_attempts,
        "nextAttemptAt": next_attempt_at,
        "reasonCode": reason_code,
    }


def _json_object(value: str | None) -> dict[str, Any]:
    import json

    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}
