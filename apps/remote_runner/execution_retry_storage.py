from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2, record_run_command
from .execution_policy import retry_backoff_seconds_for_job
from .run_execution_storage import (
    RELEASED_LEASE_STATES,
    _add_seconds,
    _fetch_run_row,
    _optional_text,
    _required_text,
)
from .storage_core import get_connection, now_iso


RETRYABLE_RUN_STATUSES = {"failed", "canceled", "cancelled"}


def request_run_retry(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
    command_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    requested_at = _optional_text(now) or now_iso()
    normalized_actor = _optional_text(actor) or "remote-runner-api"
    normalized_reason = _optional_text(reason) or "operator_requested"
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = _fetch_run_row(connection, normalized_run_id)
        run_status = str(run["status"] or "").lower()
        if run_status not in RETRYABLE_RUN_STATUSES:
            raise ValueError(f"RUN_RETRY_STATUS_NOT_RETRYABLE: {run_status}")
        job = connection.execute(
            "SELECT * FROM run_jobs WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        if job is None:
            raise ValueError("RUN_RETRY_JOB_NOT_FOUND")
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        if lease is not None and str(lease["state"]) == "active":
            raise ValueError("RUN_RETRY_ACTIVE_LEASE")
        if lease is not None and str(lease["state"]) not in RELEASED_LEASE_STATES:
            raise ValueError(f"RUN_RETRY_LEASE_NOT_RELEASED: {lease['state']}")
        attempt_count = int(job["attempt_count"])
        max_attempts = int(job["max_attempts"])
        remaining_attempts = max(0, max_attempts - attempt_count)
        if job["dead_lettered_at"] or remaining_attempts <= 0:
            raise ValueError("RUN_RETRY_MAX_ATTEMPTS_EXHAUSTED")
        job_state = str(job["state"])
        if job_state == "queued":
            raise ValueError("RUN_RETRY_ALREADY_QUEUED")
        if job_state == "claimed":
            raise ValueError("RUN_RETRY_JOB_CLAIMED")
        backoff_seconds = retry_backoff_seconds_for_job(job, fallback_seconds=0)
        available_at = _add_seconds(requested_at, backoff_seconds)
        command = record_run_command(
            connection,
            run_id=normalized_run_id,
            command_type="retry_run",
            command_id=command_id,
            payload={
                "runId": normalized_run_id,
                "scope": "run",
                "reason": normalized_reason,
            },
            actor=normalized_actor,
            requested_at=requested_at,
        )
        next_state_version = int(run["state_version"]) + 1
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?,
                started_at = NULL, finished_at = NULL, last_error_json = NULL,
                last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                "queued",
                "retry",
                next_state_version,
                "Run retry requested.",
                requested_at,
                normalized_run_id,
            ),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET state = ?, available_at = ?, wait_reason_json = '{}',
                dead_lettered_at = NULL, updated_at = ?
            WHERE job_id = ?
            """,
            ("queued", available_at, requested_at, job["job_id"]),
        )
        append_run_event_v2(
            connection,
            run_id=normalized_run_id,
            event_type="run_retry_requested",
            from_status=run["status"],
            to_status="queued",
            stage="retry",
            state_version=next_state_version,
            message="Run retry requested.",
            request_id=str(run["request_id"]),
            command_id=command["commandId"],
            actor=normalized_actor,
            payload={
                "runId": normalized_run_id,
                "jobId": job["job_id"],
                "scope": "run",
                "reason": normalized_reason,
                "attemptCount": attempt_count,
                "maxAttempts": max_attempts,
                "remainingAttempts": remaining_attempts,
                "backoffSeconds": backoff_seconds,
                "availableAt": available_at,
            },
            occurred_at=requested_at,
            command_derived=True,
        )
        connection.commit()
        return {
            "runId": normalized_run_id,
            "status": "queued",
            "stage": "retry",
            "commandId": command["commandId"],
            "jobId": job["job_id"],
            "attemptCount": attempt_count,
            "maxAttempts": max_attempts,
            "remainingAttempts": remaining_attempts,
            "availableAt": available_at,
            "retryRequestedAt": requested_at,
        }
