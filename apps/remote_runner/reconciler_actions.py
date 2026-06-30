from __future__ import annotations

import logging
import os
import signal
import sqlite3
import subprocess
import time
from typing import Any

from .admission_storage import mark_worker_slot_idle, release_resource_allocation
from .event_contracts import append_run_event_v2
from .execution_policy import (
    queue_ttl_exceeded,
    queue_ttl_seconds_for_job,
    retry_backoff_seconds_for_job,
)
from .metrics import record_run_attempt_fenced, record_run_job_dead_lettered
from .run_execution_state_machine import RunExecutionStateMachine
from .storage_core import now_iso


LOGGER = logging.getLogger(__name__)
RECOVERY_EVENT_TYPE = "run_control_plane_recovered"


def fence_expired_attempt(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    generation: int,
    reason: str,
    occurred_at: str,
    run: sqlite3.Row,
) -> dict[str, Any]:
    existing = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if existing is None:
        return {"fenced": False, "reason": "attempt_not_found"}
    if existing["state"] == "fenced":
        return {"fenced": False, "reason": "already_fenced"}
    connection.execute(
        """
        UPDATE run_attempts
        SET state = ?, fenced_reason = ?, finished_at = COALESCE(finished_at, ?), updated_at = ?
        WHERE attempt_id = ?
        """,
        ("fenced", reason, occurred_at, occurred_at, attempt_id),
    )
    connection.execute(
        "UPDATE run_leases SET state = ?, updated_at = ? WHERE attempt_id = ?",
        ("expired" if reason == "lease_expired" else "fenced", occurred_at, attempt_id),
    )
    connection.execute(
        """
        UPDATE run_resource_allocations
        SET state = 'released',
            released_at = COALESCE(released_at, ?),
            updated_at = ?
        WHERE attempt_id = ? AND state = 'allocated'
        """,
        (occurred_at, occurred_at, attempt_id),
    )
    mark_worker_slot_idle(
        connection,
        worker_id=str(existing["worker_id"]),
        session_id=str(existing["session_id"] or ""),
        slot_id=str(existing["slot_id"] or "slot-0"),
        updated_at=occurred_at,
    )
    append_run_event_v2(
        connection,
        run_id=str(existing["run_id"]),
        event_type="run_attempt_fenced",
        stage="fence",
        state_version=int(run["state_version"]),
        message="Run attempt fenced by active reconciler.",
        request_id=str(run["request_id"]),
        payload={"attemptId": attempt_id, "leaseGeneration": int(generation), "reason": reason},
        occurred_at=occurred_at,
    )
    record_run_attempt_fenced(reason=reason)
    return {"fenced": True, "attemptId": attempt_id, "reason": reason}


def recover_control_plane_invariants(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
    retry_delay_seconds: int = 5,
    blocked_job_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    actions.extend(_close_active_leases_without_running_attempts(connection, occurred_at=occurred_at))
    actions.extend(_release_orphaned_allocations(connection, occurred_at=occurred_at))
    actions.extend(_idle_orphaned_running_slots(connection, occurred_at=occurred_at))
    actions.extend(
        _recover_claimed_jobs_without_active_leases(
            connection,
            occurred_at=occurred_at,
            retry_delay_seconds=retry_delay_seconds,
            blocked_job_ids=blocked_job_ids or set(),
        )
    )
    return actions


def expire_queued_jobs_over_ttl(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM run_jobs
        WHERE state = 'queued'
          AND dead_lettered_at IS NULL
        ORDER BY created_at ASC, job_id ASC
        """
    ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in rows:
        if not queue_ttl_exceeded(row, now=occurred_at):
            continue
        result = dead_letter_job(
            connection,
            job_id=str(row["job_id"]),
            run_id=str(row["run_id"]),
            reason="queue_ttl_exceeded",
            dead_lettered_at=occurred_at,
        )
        action = {
            "type": RECOVERY_EVENT_TYPE,
            "action": "dead_letter_queue_ttl_exceeded",
            "reasonCode": "QUEUE_TTL_EXCEEDED",
            "runId": str(row["run_id"]),
            "jobId": str(row["job_id"]),
            "queueTtlSeconds": queue_ttl_seconds_for_job(row),
            "reason": result.get("reason"),
        }
        append_control_plane_recovery_event(
            connection,
            run_id=str(row["run_id"]),
            action=str(action["action"]),
            reason_code=str(action["reasonCode"]),
            occurred_at=occurred_at,
            payload={
                "jobId": action["jobId"],
                "queueTtlSeconds": action["queueTtlSeconds"],
                "reason": action["reason"],
            },
        )
        actions.append(action)
    return actions


def terminate_process_group(
    process_group_id: str | int | None,
    *,
    terminate_timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.05,
) -> dict[str, Any]:
    if process_group_id is None:
        return {"terminated": False, "reason": "no_process_group"}
    try:
        pgid = int(process_group_id)
    except (TypeError, ValueError):
        return {"terminated": False, "reason": "invalid_process_group_id"}
    if pgid <= 0:
        return {"terminated": False, "reason": "invalid_process_group_id"}
    if _uses_windows_process_groups():
        return _terminate_windows_process_tree(pgid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return {"terminated": False, "reason": "process_group_not_found"}
    except PermissionError:
        return {"terminated": False, "reason": "permission_denied"}
    except OSError as exc:
        return {"terminated": False, "reason": f"os_error: {exc}"}
    if _wait_for_process_group_exit(
        pgid,
        timeout_seconds=max(0.0, float(terminate_timeout_seconds)),
        poll_interval_seconds=max(0.001, float(poll_interval_seconds)),
    ):
        return {"terminated": True, "confirmedStopped": True, "processGroupId": pgid, "signal": "SIGTERM"}
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return {"terminated": True, "confirmedStopped": True, "processGroupId": pgid, "signal": "SIGTERM"}
    except PermissionError:
        return {"terminated": False, "reason": "permission_denied"}
    except OSError as exc:
        return {"terminated": False, "reason": f"os_error: {exc}"}
    confirmed = _wait_for_process_group_exit(
        pgid,
        timeout_seconds=max(0.0, float(terminate_timeout_seconds)),
        poll_interval_seconds=max(0.001, float(poll_interval_seconds)),
    )
    return {
        "terminated": confirmed,
        "confirmedStopped": confirmed,
        "processGroupId": pgid,
        "signal": "SIGKILL",
        **({} if confirmed else {"reason": "process_group_still_running"}),
    }


def _wait_for_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval_seconds)


def _uses_windows_process_groups() -> bool:
    return os.name == "nt"


def _terminate_windows_process_tree(process_id: int) -> dict[str, Any]:
    result = subprocess.run(
        ["taskkill", "/PID", str(process_id), "/T"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return {"terminated": True, "processGroupId": process_id}
    detail = str(result.stderr or result.stdout or "").strip()
    return {
        "terminated": False,
        "reason": "process_group_not_found" if result.returncode == 128 else "taskkill_failed",
        **({"detail": detail} if detail else {}),
    }


def requeue_retryable_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    run_id: str,
    retry_delay_seconds: int = 5,
    requeued_at: str | None = None,
) -> dict[str, Any]:
    timestamp = requeued_at or now_iso()
    job = connection.execute(
        "SELECT * FROM run_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        return {"requeued": False, "reason": "job_not_found"}
    if job["state"] != "claimed":
        return {"requeued": False, "reason": f"unexpected_state: {job['state']}"}
    attempt_count = int(job["attempt_count"])
    max_attempts = int(job["max_attempts"])
    if attempt_count >= max_attempts:
        return {"requeued": False, "reason": "max_attempts_exceeded"}
    from datetime import datetime, timedelta, timezone
    backoff_seconds = retry_backoff_seconds_for_job(job, fallback_seconds=retry_delay_seconds)
    available_at = (
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        + timedelta(seconds=backoff_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection.execute(
        """
        UPDATE run_jobs
        SET state = ?, available_at = ?, updated_at = ?
        WHERE job_id = ?
        """,
        ("queued", available_at, timestamp, job_id),
    )
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is not None:
        append_run_event_v2(
            connection,
            run_id=run_id,
            event_type="run_job_requeued",
            stage="requeue",
            state_version=int(run["state_version"]),
            message="Run job re-queued for retry.",
            request_id=str(run["request_id"]),
            payload={
                "jobId": job_id,
                "attemptCount": attempt_count,
                "maxAttempts": max_attempts,
                "backoffSeconds": backoff_seconds,
                "availableAt": available_at,
            },
            occurred_at=timestamp,
        )
    return {"requeued": True, "jobId": job_id, "availableAt": available_at, "backoffSeconds": backoff_seconds}


def dead_letter_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    run_id: str,
    reason: str,
    dead_lettered_at: str | None = None,
) -> dict[str, Any]:
    timestamp = dead_lettered_at or now_iso()
    job = connection.execute(
        "SELECT * FROM run_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        return {"deadLettered": False, "reason": "job_not_found"}
    if job["dead_lettered_at"] is not None:
        return {"deadLettered": False, "reason": "already_dead_lettered"}
    connection.execute(
        """
        UPDATE run_jobs
        SET state = ?, dead_lettered_at = ?, updated_at = ?
        WHERE job_id = ?
        """,
        ("failed", timestamp, timestamp, job_id),
    )
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is not None:
        transition = RunExecutionStateMachine.dead_letter_job(
            current_status=str(run["status"]),
            state_version=int(run["state_version"]),
        )
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?, last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                transition.to_status,
                transition.stage,
                transition.state_version,
                transition.row_message,
                timestamp,
                run_id,
            ),
        )
        append_run_event_v2(
            connection,
            run_id=run_id,
            event_type=transition.event_type,
            from_status=transition.from_status,
            to_status=transition.to_status,
            stage=transition.stage,
            state_version=transition.state_version,
            message=transition.event_message,
            request_id=str(run["request_id"]),
            payload={
                "jobId": job_id,
                "attemptCount": int(job["attempt_count"]),
                "maxAttempts": int(job["max_attempts"]),
                "reason": reason,
            },
            occurred_at=timestamp,
        )
    record_run_job_dead_lettered()
    return {"deadLettered": True, "jobId": job_id, "reason": reason}


def append_control_plane_recovery_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    action: str,
    reason_code: str,
    occurred_at: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        return None
    return append_run_event_v2(
        connection,
        run_id=run_id,
        event_type=RECOVERY_EVENT_TYPE,
        stage="reconcile",
        state_version=int(run["state_version"]),
        message="Execution control-plane recovery applied.",
        request_id=str(run["request_id"]),
        payload={
            "action": action,
            "reasonCode": reason_code,
            **payload,
        },
        occurred_at=occurred_at,
    )


def _close_active_leases_without_running_attempts(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT leases.run_id, leases.attempt_id, leases.lease_generation,
               leases.worker_id, leases.session_id, leases.slot_id,
               attempts.state AS attempt_state
        FROM run_leases AS leases
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = leases.attempt_id
        WHERE leases.state = 'active'
          AND COALESCE(attempts.state, '') <> 'running'
        ORDER BY leases.expires_at ASC, leases.run_id ASC
        """
    ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in rows:
        attempt_state = str(row["attempt_state"] or "")
        target_lease_state = RunExecutionStateMachine.lease_state_for_non_running_attempt(attempt_state)
        connection.execute(
            "UPDATE run_leases SET state = ?, updated_at = ? WHERE run_id = ?",
            (target_lease_state, occurred_at, row["run_id"]),
        )
        if target_lease_state in {"completed", "failed", "cancelled"}:
            connection.execute(
                "UPDATE run_jobs SET state = ?, updated_at = ? WHERE run_id = ? AND state = 'claimed'",
                (target_lease_state, occurred_at, row["run_id"]),
            )
        release_resource_allocation(connection, attempt_id=str(row["attempt_id"]), released_at=occurred_at)
        mark_worker_slot_idle(
            connection,
            worker_id=str(row["worker_id"]),
            session_id=str(row["session_id"] or ""),
            slot_id=str(row["slot_id"] or "slot-0"),
            updated_at=occurred_at,
        )
        action = {
            "type": RECOVERY_EVENT_TYPE,
            "action": "close_active_lease_without_running_attempt",
            "reasonCode": "ACTIVE_LEASE_WITHOUT_RUNNING_ATTEMPT",
            "runId": str(row["run_id"]),
            "attemptId": str(row["attempt_id"]),
            "leaseGeneration": int(row["lease_generation"]),
            "attemptState": attempt_state or "missing",
            "leaseState": target_lease_state,
        }
        append_control_plane_recovery_event(
            connection,
            run_id=str(row["run_id"]),
            action=str(action["action"]),
            reason_code=str(action["reasonCode"]),
            occurred_at=occurred_at,
            payload={
                "attemptId": action["attemptId"],
                "leaseGeneration": action["leaseGeneration"],
                "attemptState": action["attemptState"],
                "leaseState": action["leaseState"],
            },
        )
        actions.append(action)
    return actions


def _release_orphaned_allocations(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT allocations.run_id, allocations.allocation_id, allocations.attempt_id,
               allocations.worker_id, allocations.session_id, allocations.slot_id,
               leases.state AS lease_state
        FROM run_resource_allocations AS allocations
        LEFT JOIN run_leases AS leases ON leases.attempt_id = allocations.attempt_id
        WHERE allocations.state = 'allocated'
          AND COALESCE(leases.state, '') <> 'active'
        ORDER BY allocations.created_at ASC
        """
    ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in rows:
        release_resource_allocation(connection, attempt_id=str(row["attempt_id"]), released_at=occurred_at)
        action = {
            "type": RECOVERY_EVENT_TYPE,
            "action": "release_orphaned_allocation",
            "reasonCode": "ALLOCATED_RESOURCE_WITHOUT_ACTIVE_LEASE",
            "runId": str(row["run_id"]),
            "attemptId": str(row["attempt_id"]),
            "allocationId": str(row["allocation_id"]),
            "leaseState": str(row["lease_state"] or "missing"),
        }
        append_control_plane_recovery_event(
            connection,
            run_id=str(row["run_id"]),
            action=str(action["action"]),
            reason_code=str(action["reasonCode"]),
            occurred_at=occurred_at,
            payload={
                "attemptId": action["attemptId"],
                "allocationId": action["allocationId"],
                "leaseState": action["leaseState"],
            },
        )
        actions.append(action)
    return actions


def _idle_orphaned_running_slots(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT slots.worker_id, slots.session_id, slots.slot_id, slots.current_attempt_id,
               attempts.run_id, attempts.state AS attempt_state
        FROM run_worker_slots AS slots
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = slots.current_attempt_id
        WHERE slots.state = 'running'
          AND (slots.current_attempt_id IS NULL OR COALESCE(attempts.state, '') <> 'running')
        ORDER BY slots.worker_id ASC, slots.slot_id ASC
        """
    ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in rows:
        connection.execute(
            """
            UPDATE run_worker_slots
            SET state = 'idle', current_attempt_id = NULL, heartbeat_at = ?, updated_at = ?
            WHERE worker_id = ? AND slot_id = ? AND session_id = ?
            """,
            (occurred_at, occurred_at, row["worker_id"], row["slot_id"], row["session_id"]),
        )
        action = {
            "type": RECOVERY_EVENT_TYPE,
            "action": "idle_orphaned_running_slot",
            "reasonCode": "RUNNING_SLOT_WITHOUT_RUNNING_ATTEMPT",
            "workerId": str(row["worker_id"]),
            "sessionId": str(row["session_id"]),
            "slotId": str(row["slot_id"]),
            "attemptId": str(row["current_attempt_id"] or ""),
            "runId": str(row["run_id"] or ""),
            "attemptState": str(row["attempt_state"] or "missing"),
        }
        if action["runId"]:
            append_control_plane_recovery_event(
                connection,
                run_id=str(action["runId"]),
                action=str(action["action"]),
                reason_code=str(action["reasonCode"]),
                occurred_at=occurred_at,
                payload={
                    "attemptId": action["attemptId"],
                    "workerId": action["workerId"],
                    "sessionId": action["sessionId"],
                    "slotId": action["slotId"],
                    "attemptState": action["attemptState"],
                },
            )
        actions.append(action)
    return actions


def _recover_claimed_jobs_without_active_leases(
    connection: sqlite3.Connection,
    *,
    occurred_at: str,
    retry_delay_seconds: int,
    blocked_job_ids: set[str],
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT jobs.job_id, jobs.run_id, jobs.attempt_count, jobs.max_attempts,
               leases.attempt_id, leases.lease_generation, leases.state AS lease_state,
               attempts.process_group_id
        FROM run_jobs AS jobs
        LEFT JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = leases.attempt_id
        WHERE jobs.state = 'claimed'
          AND COALESCE(leases.state, '') <> 'active'
          AND COALESCE(attempts.process_group_id, '') = ''
        ORDER BY jobs.updated_at ASC
        """
    ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in rows:
        if str(row["job_id"]) in blocked_job_ids:
            continue
        attempt_count = int(row["attempt_count"])
        max_attempts = int(row["max_attempts"])
        if attempt_count < max_attempts:
            result = requeue_retryable_job(
                connection,
                job_id=str(row["job_id"]),
                run_id=str(row["run_id"]),
                retry_delay_seconds=retry_delay_seconds,
                requeued_at=occurred_at,
            )
            action_name = "requeue_claimed_job_without_active_lease"
            action = {
                "type": RECOVERY_EVENT_TYPE,
                "action": action_name,
                "reasonCode": "CLAIMED_JOB_WITHOUT_ACTIVE_LEASE",
                "runId": str(row["run_id"]),
                "jobId": str(row["job_id"]),
                "attemptId": str(row["attempt_id"] or ""),
                "leaseGeneration": int(row["lease_generation"] or 0),
                "availableAt": result.get("availableAt"),
            }
        else:
            result = dead_letter_job(
                connection,
                job_id=str(row["job_id"]),
                run_id=str(row["run_id"]),
                reason="claimed_job_without_active_lease",
                dead_lettered_at=occurred_at,
            )
            action_name = "dead_letter_claimed_job_without_active_lease"
            action = {
                "type": RECOVERY_EVENT_TYPE,
                "action": action_name,
                "reasonCode": "CLAIMED_JOB_WITHOUT_ACTIVE_LEASE",
                "runId": str(row["run_id"]),
                "jobId": str(row["job_id"]),
                "attemptId": str(row["attempt_id"] or ""),
                "leaseGeneration": int(row["lease_generation"] or 0),
                "reason": result.get("reason"),
            }
        append_control_plane_recovery_event(
            connection,
            run_id=str(row["run_id"]),
            action=action_name,
            reason_code="CLAIMED_JOB_WITHOUT_ACTIVE_LEASE",
            occurred_at=occurred_at,
            payload={
                "jobId": str(row["job_id"]),
                "attemptId": str(row["attempt_id"] or ""),
                "leaseGeneration": int(row["lease_generation"] or 0),
                "leaseState": str(row["lease_state"] or "missing"),
            },
        )
        actions.append(action)
    return actions
