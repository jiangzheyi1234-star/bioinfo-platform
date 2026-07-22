"""Lease-aware attempt polling and process ownership mutations."""

from __future__ import annotations

import sqlite3
from typing import Any

from .config import RemoteRunnerConfig
from .execution_policy import heartbeat_timeout_seconds_for_job
from .execution_lease_time import (
    execution_lease_expiry_is_future,
    execution_timestamp_at_or_after,
    require_execution_utc_timestamp,
)
from .execution_storage_primitives import (
    add_seconds,
    fetch_attempt_row,
    fetch_run_row,
    optional_positive_int,
    optional_text,
    required_text,
)
from .run_execution_state_machine import (
    RunAttemptLeaseGuardDecision,
    RunExecutionStateMachine,
)
from .storage_core import get_connection, now_iso


def current_attempt_lease_guard(
    lease: sqlite3.Row | None,
    attempt_id: str,
    generation: int,
    *,
    observed_at: str | None = None,
) -> RunAttemptLeaseGuardDecision:
    """Require current identity, active state, and an unexpired lease."""

    decision = RunExecutionStateMachine.current_lease_guard(
        attempt_id=attempt_id,
        lease_generation=generation,
        current_attempt_id=str(lease["attempt_id"]) if lease is not None else None,
        current_lease_generation=(
            int(lease["lease_generation"]) if lease is not None else None
        ),
        current_lease_state=str(lease["state"]) if lease is not None else None,
    )
    if (
        decision.accepted
        and lease is not None
        and not execution_lease_expiry_is_future(
            lease["expires_at"], observed_at=observed_at
        )
    ):
        return RunAttemptLeaseGuardDecision(accepted=False, reason="lease_expired")
    return decision


def record_run_attempt_process_group(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
    process_group_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_attempt_id = required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_process_group_id = required_text(
        process_group_id, "PROCESS_GROUP_ID_REQUIRED"
    )
    requested_at = optional_text(now)
    if requested_at is not None:
        require_execution_utc_timestamp(requested_at)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        updated_at = execution_timestamp_at_or_after(
            requested_at=requested_at,
            current_at=now_iso(),
        )
        attempt = fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        lease_guard = current_attempt_lease_guard(
            lease,
            normalized_attempt_id,
            lease_generation,
            observed_at=updated_at,
        )
        if not lease_guard.accepted:
            connection.rollback()
            return {"accepted": False, "reason": lease_guard.reason}
        updated = connection.execute(
            """
            UPDATE run_attempts
            SET process_group_id = ?, process_pid = ?, updated_at = ?
            WHERE attempt_id = ?
              AND lease_generation = ?
              AND state = 'running'
              AND EXISTS (
                  SELECT 1
                  FROM run_leases
                  WHERE run_id = run_attempts.run_id
                    AND attempt_id = run_attempts.attempt_id
                    AND lease_generation = ?
                    AND state = 'active'
                    AND expires_at > ?
              )
              AND EXISTS (
                  SELECT 1
                  FROM run_jobs
                  WHERE job_id = run_attempts.job_id
                    AND state = 'claimed'
              )
            """,
            (
                normalized_process_group_id,
                optional_positive_int(normalized_process_group_id),
                updated_at,
                normalized_attempt_id,
                lease_generation,
                lease_generation,
                updated_at,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            return {"accepted": False, "reason": "stale_generation"}
        connection.commit()
        return {"accepted": True, "processGroupId": normalized_process_group_id}


def heartbeat_run_attempt(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
    now: str | None = None,
    lease_seconds: int = 60,
) -> dict[str, Any]:
    """Renew only the same still-running attempt under one writer transaction."""

    normalized_attempt_id = required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    requested_at = optional_text(now)
    if requested_at is not None:
        require_execution_utc_timestamp(requested_at)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        heartbeat_at = execution_timestamp_at_or_after(
            requested_at=requested_at,
            current_at=now_iso(),
        )
        attempt = fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?", (attempt["run_id"],)
        ).fetchone()
        lease_guard = current_attempt_lease_guard(
            lease,
            normalized_attempt_id,
            lease_generation,
            observed_at=heartbeat_at,
        )
        if not lease_guard.accepted:
            connection.rollback()
            return {"accepted": False, "reason": lease_guard.reason}
        job = connection.execute(
            "SELECT * FROM run_jobs WHERE job_id = ?", (attempt["job_id"],)
        ).fetchone()
        expires_at = add_seconds(
            heartbeat_at,
            heartbeat_timeout_seconds_for_job(job, fallback_seconds=lease_seconds),
        )
        updated = connection.execute(
            """
            UPDATE run_leases
            SET heartbeat_at = ?, expires_at = ?, updated_at = ?
            WHERE run_id = ?
              AND attempt_id = ?
              AND lease_generation = ?
              AND state = 'active'
              AND expires_at > ?
              AND EXISTS (
                  SELECT 1
                  FROM run_attempts
                  JOIN run_jobs ON run_jobs.job_id = run_attempts.job_id
                  WHERE run_attempts.attempt_id = run_leases.attempt_id
                    AND run_attempts.run_id = run_leases.run_id
                    AND run_attempts.lease_generation = run_leases.lease_generation
                    AND run_attempts.state = 'running'
                    AND run_jobs.state = 'claimed'
              )
            """,
            (
                heartbeat_at,
                expires_at,
                heartbeat_at,
                attempt["run_id"],
                normalized_attempt_id,
                lease_generation,
                heartbeat_at,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            return {"accepted": False, "reason": "stale_generation"}
        connection.commit()
        return {"accepted": True, "expiresAt": expires_at}


def run_attempt_cancel_requested(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
) -> bool:
    normalized_attempt_id = required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    with get_connection(cfg) as connection:
        attempt = fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        lease_guard = current_attempt_lease_guard(
            lease, normalized_attempt_id, lease_generation
        )
        if not lease_guard.accepted:
            return True
        run = fetch_run_row(connection, str(attempt["run_id"]))
        return bool(attempt["cancel_requested_at"] or run["status"] == "canceling")


__all__ = [
    "current_attempt_lease_guard",
    "heartbeat_run_attempt",
    "record_run_attempt_process_group",
    "run_attempt_cancel_requested",
]
