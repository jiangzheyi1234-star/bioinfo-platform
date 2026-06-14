from __future__ import annotations

import logging
import sqlite3
from typing import Any

from core.logging_config import clear_log_context, set_log_context

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2
from .reconciler_actions import (
    dead_letter_job,
    fence_expired_attempt,
    requeue_retryable_job,
    terminate_process_group,
)
from .reconciler_rules import (
    clock_jump_observation,
)
from .storage_core import get_connection, now_iso


LOGGER = logging.getLogger(__name__)


def run_active_reconciler_once(
    cfg: RemoteRunnerConfig,
    *,
    now: str | None = None,
    clock_jump_expiry_threshold: int = 10,
    retry_delay_seconds: int = 5,
) -> list[dict[str, Any]]:
    reconciled_at = str(now or now_iso())
    actions: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    with get_connection(cfg) as connection:
        expired_rows = _expired_lease_rows(connection, reconciled_at)
        clock_jump = clock_jump_observation(
            expired_lease_count=len(expired_rows),
            threshold=int(clock_jump_expiry_threshold),
        )
        if clock_jump is not None:
            actions.append(clock_jump)
            _append_observation_to_runs(
                connection,
                rows=expired_rows,
                event_type="clock_jump_suspected",
                observation=clock_jump,
                observed_at=reconciled_at,
            )

        for raw_row in expired_rows:
            row = dict(raw_row)
            run_id = str(row["run_id"])
            attempt_id = str(row["attempt_id"])
            generation = int(row["lease_generation"])
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                continue
            fence_result = fence_expired_attempt(
                connection,
                attempt_id=attempt_id,
                generation=generation,
                reason="lease_expired",
                occurred_at=reconciled_at,
                run=run,
            )
            if fence_result.get("fenced") or fence_result.get("reason") == "already_fenced":
                recoveries.append(row)
        connection.commit()

    for row in recoveries:
        attempt_id = str(row["attempt_id"])
        set_log_context(
            run_id=str(row["run_id"]),
            attempt_id=attempt_id,
            slot_id=str(row.get("slot_id") or ""),
        )
        try:
            terminate_result = terminate_process_group(row.get("process_group_id"))
            LOGGER.info(
                "Fenced attempt termination checked run_id=%s attempt_id=%s slot_id=%s",
                str(row["run_id"]),
                attempt_id,
                str(row.get("slot_id") or ""),
                extra={
                    "runId": str(row["run_id"]),
                    "jobId": str(row["job_id"]),
                    "attemptId": attempt_id,
                    "slotId": str(row.get("slot_id") or ""),
                    "termination": terminate_result,
                },
            )
        finally:
            clear_log_context()
        if not _termination_confirmed(terminate_result):
            blocked_reason = str(terminate_result.get("reason") or "termination_unconfirmed")
            _record_recovery_blocked(
                cfg,
                row=row,
                reason=blocked_reason,
                blocked_at=reconciled_at,
            )
            actions.append(
                {
                    "type": "run_attempt_recovery_blocked",
                    "runId": str(row["run_id"]),
                    "jobId": str(row["job_id"]),
                    "attemptId": attempt_id,
                    "reason": blocked_reason,
                }
            )
            continue
        with get_connection(cfg) as connection:
            job = connection.execute(
                "SELECT * FROM run_jobs WHERE job_id = ?",
                (str(row["job_id"]),),
            ).fetchone()
            if job is None or str(job["state"]) != "claimed":
                continue
            attempt_count = int(job["attempt_count"])
            max_attempts = int(job["max_attempts"])
            if attempt_count < max_attempts:
                requeue_result = requeue_retryable_job(
                    connection,
                    job_id=str(row["job_id"]),
                    run_id=str(row["run_id"]),
                    retry_delay_seconds=retry_delay_seconds,
                    requeued_at=reconciled_at,
                )
                actions.append({
                    "type": "run_attempt_recovered",
                    "runId": str(row["run_id"]),
                    "jobId": str(row["job_id"]),
                    "attemptId": attempt_id,
                    "action": "requeued",
                    "availableAt": requeue_result.get("availableAt"),
                })
            else:
                dead_letter_result = dead_letter_job(
                    connection,
                    job_id=str(row["job_id"]),
                    run_id=str(row["run_id"]),
                    reason="max_attempts_exceeded",
                    dead_lettered_at=reconciled_at,
                )
                actions.append({
                    "type": "run_attempt_recovered",
                    "runId": str(row["run_id"]),
                    "jobId": str(row["job_id"]),
                    "attemptId": attempt_id,
                    "action": "dead_lettered",
                    "reason": dead_letter_result.get("reason"),
                })
            connection.commit()
    return actions


def _expired_lease_rows(connection: sqlite3.Connection, now: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            jobs.job_id,
            jobs.run_id,
            leases.attempt_id,
            leases.lease_generation,
            leases.expires_at,
            leases.slot_id,
            attempts.process_group_id
        FROM run_jobs AS jobs
        JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        JOIN run_attempts AS attempts ON attempts.attempt_id = leases.attempt_id
        WHERE jobs.state = 'claimed'
          AND leases.state IN ('active', 'expired', 'fenced')
          AND leases.expires_at < ?
        ORDER BY leases.expires_at ASC, jobs.run_id ASC
        """,
        (now,),
    ).fetchall()


def _termination_confirmed(result: dict[str, Any]) -> bool:
    return bool(
        result.get("terminated")
        or result.get("confirmedStopped")
        or result.get("reason") in {"no_process_group", "process_group_not_found"}
    )


def _record_recovery_blocked(
    cfg: RemoteRunnerConfig,
    *,
    row: dict[str, Any],
    reason: str,
    blocked_at: str,
) -> None:
    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (str(row["run_id"]),),
        ).fetchone()
        if run is None:
            return
        append_run_event_v2(
            connection,
            run_id=str(row["run_id"]),
            event_type="run_attempt_recovery_blocked",
            stage="reconcile",
            state_version=int(run["state_version"]),
            message="Run attempt recovery blocked.",
            request_id=str(run["request_id"]),
            payload={
                "jobId": str(row["job_id"]),
                "attemptId": str(row["attempt_id"]),
                "leaseGeneration": int(row["lease_generation"]),
                "slotId": str(row.get("slot_id") or ""),
                "reason": reason,
            },
            occurred_at=blocked_at,
        )
        connection.commit()


def _append_observation_to_runs(
    connection: sqlite3.Connection,
    *,
    rows: list[sqlite3.Row],
    event_type: str,
    observation: dict[str, Any],
    observed_at: str,
) -> None:
    seen: set[str] = set()
    for row in rows:
        run_id = str(row["run_id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        _append_observation_event(
            connection,
            run_id=run_id,
            event_type=event_type,
            observation=observation,
            observed_at=observed_at,
        )


def _append_observation_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    event_type: str,
    observation: dict[str, Any],
    observed_at: str,
) -> None:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        return
    append_run_event_v2(
        connection,
        run_id=run_id,
        event_type=event_type,
        stage="reconcile",
        state_version=int(run["state_version"]),
        message="Active reconciler observation.",
        request_id=str(run["request_id"]),
        payload=observation,
        occurred_at=observed_at,
    )
