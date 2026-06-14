from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2, record_run_command
from .execution_decision_logging import log_admission_wait, log_claim_accepted
from .admission_storage import (
    admission_wait_reason,
    mark_worker_slot_idle,
    mark_worker_slot_running,
    record_resource_allocation,
    release_resource_allocation,
)
from .resource_pool import ResourceRequest
from .storage_core import get_connection, now_iso


TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled", "cancelled"}


def enqueue_run_job(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    queue_name: str = "default",
    priority: int = 0,
    available_at: str | None = None,
    wait_reason: dict[str, Any] | None = None,
    max_attempts: int = 3,
    retry_policy: dict[str, Any] | None = None,
    timeout_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    queued_at = _optional_text(available_at) or now_iso()
    with get_connection(cfg) as connection:
        row = enqueue_run_job_record(
            connection,
            run_id=run_id,
            queue_name=queue_name,
            priority=priority,
            available_at=queued_at,
            wait_reason=wait_reason,
            max_attempts=max_attempts,
            retry_policy=retry_policy,
            timeout_policy=timeout_policy,
        )
        connection.commit()
        return _job_row_to_dict(row)


def enqueue_run_job_record(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    queue_name: str = "default",
    priority: int = 0,
    available_at: str,
    wait_reason: dict[str, Any] | None = None,
    max_attempts: int = 3,
    retry_policy: dict[str, Any] | None = None,
    timeout_policy: dict[str, Any] | None = None,
) -> sqlite3.Row:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_queue_name = _required_text(queue_name, "QUEUE_NAME_REQUIRED")
    normalized_max_attempts = max(1, int(max_attempts))
    existing = connection.execute(
        "SELECT * FROM run_jobs WHERE run_id = ?",
        (normalized_run_id,),
    ).fetchone()
    if existing is not None:
        return existing

    run = _fetch_run_row(connection, normalized_run_id)
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO run_jobs (
            job_id, run_id, state, queue_name, priority, available_at,
            wait_reason_json, attempt_count, max_attempts, retry_policy_json, timeout_policy_json,
            dead_lettered_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            normalized_run_id,
            "queued",
            normalized_queue_name,
            int(priority),
            available_at,
            _stable_json(wait_reason or {}),
            0,
            normalized_max_attempts,
            _stable_json(retry_policy or {}),
            _stable_json(timeout_policy or {}),
            None,
            available_at,
            available_at,
        ),
    )
    append_run_event_v2(
        connection,
        run_id=normalized_run_id,
        event_type="run_job_queued",
        stage="queue",
        state_version=int(run["state_version"]),
        message="Run job queued.",
        request_id=str(run["request_id"]),
        payload={
            "jobId": job_id,
            "queueName": normalized_queue_name,
            "maxAttempts": normalized_max_attempts,
        },
        occurred_at=available_at,
    )
    return connection.execute("SELECT * FROM run_jobs WHERE job_id = ?", (job_id,)).fetchone()


def claim_next_run_job(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    session_id: str = "",
    slot_id: str = "slot-0",
    queue_name: str = "default",
    resource_request: ResourceRequest | None = None,
    resource_capacity: ResourceRequest | None = None,
    max_active_slots: int = 1,
    now: str | None = None,
    lease_seconds: int = 60,
) -> dict[str, Any] | None:
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    normalized_session_id = _optional_text(session_id) or ""
    normalized_slot_id = _required_text(slot_id, "SLOT_ID_REQUIRED")
    normalized_queue_name = _required_text(queue_name, "QUEUE_NAME_REQUIRED")
    claimed_at = _optional_text(now) or now_iso()
    request = resource_request or ResourceRequest()
    capacity = resource_capacity or ResourceRequest(cpu=max(1, int(max_active_slots)))
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = _select_claimable_job(connection, claimed_at, normalized_queue_name)
        if job is None:
            connection.commit()
            return None
        wait_reason = admission_wait_reason(
            connection,
            worker_id=normalized_worker_id,
            slot_id=normalized_slot_id,
            request=request,
            capacity=capacity,
            max_active_slots=max_active_slots,
        )
        if wait_reason is not None:
            connection.execute(
                """
                UPDATE run_jobs
                SET wait_reason_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (_stable_json(wait_reason), claimed_at, job["job_id"]),
            )
            log_admission_wait(
                wait_reason=wait_reason,
                job=job,
                queue_name=normalized_queue_name,
                worker_id=normalized_worker_id,
                session_id=normalized_session_id,
                slot_id=normalized_slot_id,
                request=request,
            )
            connection.commit()
            return None
        run = _fetch_run_row(connection, str(job["run_id"]))
        current_lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (job["run_id"],),
        ).fetchone()
        next_generation = 1
        if current_lease is not None:
            next_generation = int(current_lease["lease_generation"]) + 1
            lease_state = str(current_lease["state"])
            if lease_state not in {"expired", "fenced"}:
                raise RuntimeError(f"RUN_JOB_LEASE_NOT_RELEASED: {lease_state}")

        attempt_id = f"att_{uuid.uuid4().hex[:12]}"
        attempt_number = int(job["attempt_count"]) + 1
        work_dir = str(Path(cfg.work_dir) / "attempts" / attempt_id)
        expires_at = _add_seconds(claimed_at, int(lease_seconds))
        connection.execute(
            """
            INSERT INTO run_attempts (
                attempt_id, run_id, job_id, lease_generation, attempt_number,
                state, worker_id, work_dir, process_pid, process_group_id,
                session_id, slot_id,
                cancel_requested_at, killed_at, output_adoption_state,
                started_at, finished_at, exit_code, fenced_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                job["run_id"],
                job["job_id"],
                next_generation,
                attempt_number,
                "running",
                normalized_worker_id,
                work_dir,
                None,
                None,
                normalized_session_id,
                normalized_slot_id,
                None,
                None,
                "pending",
                claimed_at,
                None,
                None,
                None,
                claimed_at,
                claimed_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO run_leases (
                run_id, attempt_id, lease_generation, worker_id, heartbeat_at,
                session_id, slot_id, expires_at, state, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                attempt_id = excluded.attempt_id,
                lease_generation = excluded.lease_generation,
                worker_id = excluded.worker_id,
                heartbeat_at = excluded.heartbeat_at,
                session_id = excluded.session_id,
                slot_id = excluded.slot_id,
                expires_at = excluded.expires_at,
                state = excluded.state,
                updated_at = excluded.updated_at
            """,
            (
                job["run_id"],
                attempt_id,
                next_generation,
                normalized_worker_id,
                claimed_at,
                normalized_session_id,
                normalized_slot_id,
                expires_at,
                "active",
                claimed_at,
            ),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET state = ?, wait_reason_json = '{}', attempt_count = ?, updated_at = ?
            WHERE job_id = ?
            """,
            ("claimed", attempt_number, claimed_at, job["job_id"]),
        )
        append_run_event_v2(
            connection,
            run_id=str(job["run_id"]),
            event_type="run_attempt_claimed",
            stage="claim",
            state_version=int(run["state_version"]),
            message="Run attempt claimed.",
            request_id=str(run["request_id"]),
            payload={
                "jobId": job["job_id"],
                "attemptId": attempt_id,
                "leaseGeneration": next_generation,
                "attemptNumber": attempt_number,
                "workerId": normalized_worker_id,
                "sessionId": normalized_session_id,
                "slotId": normalized_slot_id,
            },
            occurred_at=claimed_at,
        )
        record_resource_allocation(
            connection,
            run_id=str(job["run_id"]),
            attempt_id=attempt_id,
            worker_id=normalized_worker_id,
            session_id=normalized_session_id,
            slot_id=normalized_slot_id,
            request=request,
            created_at=claimed_at,
        )
        mark_worker_slot_running(
            connection,
            worker_id=normalized_worker_id,
            session_id=normalized_session_id,
            slot_id=normalized_slot_id,
            attempt_id=attempt_id,
            updated_at=claimed_at,
        )
        log_claim_accepted(
            job=job,
            attempt_id=attempt_id,
            lease_generation=next_generation,
            queue_name=normalized_queue_name,
            worker_id=normalized_worker_id,
            session_id=normalized_session_id,
            slot_id=normalized_slot_id,
            request=request,
        )
        connection.commit()

        attempt = connection.execute(
            "SELECT * FROM run_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (job["run_id"],),
        ).fetchone()
        claimed_job = connection.execute(
            "SELECT * FROM run_jobs WHERE job_id = ?",
            (job["job_id"],),
        ).fetchone()
        return _claim_to_dict(claimed_job, attempt, lease)


def heartbeat_run_attempt(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
    now: str | None = None,
    lease_seconds: int = 60,
) -> dict[str, Any]:
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    heartbeat_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        attempt = _fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        if not _is_current_lease(lease, normalized_attempt_id, lease_generation):
            return {"accepted": False, "reason": "stale_generation"}
        expires_at = _add_seconds(heartbeat_at, int(lease_seconds))
        connection.execute(
            """
            UPDATE run_leases
            SET heartbeat_at = ?, expires_at = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (heartbeat_at, expires_at, heartbeat_at, attempt["run_id"]),
        )
        connection.commit()
        return {"accepted": True, "expiresAt": expires_at}


def record_run_attempt_process_group(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
    process_group_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_process_group_id = _required_text(process_group_id, "PROCESS_GROUP_ID_REQUIRED")
    updated_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        attempt = _fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        if not _is_current_lease(lease, normalized_attempt_id, lease_generation):
            return {"accepted": False, "reason": "stale_generation"}
        connection.execute(
            """
            UPDATE run_attempts
            SET process_group_id = ?, process_pid = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            (
                normalized_process_group_id,
                _optional_positive_int(normalized_process_group_id),
                updated_at,
                normalized_attempt_id,
            ),
        )
        connection.commit()
        return {"accepted": True, "processGroupId": normalized_process_group_id}


def request_run_cancel(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    actor: str | None = None,
    command_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    requested_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = _fetch_run_row(connection, normalized_run_id)
        command = record_run_command(
            connection,
            run_id=normalized_run_id,
            command_type="cancel_run",
            command_id=command_id,
            payload={"runId": normalized_run_id},
            actor=actor,
            requested_at=requested_at,
        )
        lease = connection.execute(
            """
            SELECT *
            FROM run_leases
            WHERE run_id = ? AND state = 'active'
            """,
            (normalized_run_id,),
        ).fetchone()
        attempt_id = str(lease["attempt_id"]) if lease is not None else None
        if attempt_id:
            connection.execute(
                """
                UPDATE run_attempts
                SET cancel_requested_at = COALESCE(cancel_requested_at, ?),
                    updated_at = ?
                WHERE attempt_id = ?
                """,
                (requested_at, requested_at, attempt_id),
            )

        next_state_version = int(run["state_version"])
        target_status = str(run["status"])
        if target_status not in TERMINAL_RUN_STATUSES:
            next_state_version += 1
            target_status = "canceling"
            connection.execute(
                """
                UPDATE runs
                SET status = ?, stage = ?, state_version = ?, message = ?,
                    last_updated_at = ?
                WHERE run_id = ?
                """,
                (
                    target_status,
                    "cancel",
                    next_state_version,
                    "Cancellation requested.",
                    requested_at,
                    normalized_run_id,
                ),
            )
        append_run_event_v2(
            connection,
            run_id=normalized_run_id,
            event_type="run_cancel_requested",
            from_status=run["status"],
            to_status=target_status,
            stage="cancel",
            state_version=next_state_version,
            message="Run cancellation requested.",
            request_id=str(run["request_id"]),
            command_id=command["commandId"],
            actor=actor,
            payload={
                "runId": normalized_run_id,
                "attemptId": attempt_id,
            },
            occurred_at=requested_at,
            command_derived=True,
        )
        connection.commit()
        return {
            "runId": normalized_run_id,
            "status": target_status,
            "stage": "cancel",
            "commandId": command["commandId"],
            "attemptId": attempt_id,
            "cancelRequestedAt": requested_at,
        }


def run_attempt_cancel_requested(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
) -> bool:
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    with get_connection(cfg) as connection:
        attempt = _fetch_attempt_row(connection, normalized_attempt_id)
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        if not _is_current_lease(lease, normalized_attempt_id, lease_generation):
            return True
        run = _fetch_run_row(connection, str(attempt["run_id"]))
        return bool(attempt["cancel_requested_at"] or run["status"] == "canceling")


def complete_run_attempt(
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    *,
    lease_generation: int,
    state: str,
    exit_code: int | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_state = _required_text(state, "ATTEMPT_STATE_REQUIRED")
    finished_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        attempt = _fetch_attempt_row(connection, normalized_attempt_id)
        run = _fetch_run_row(connection, str(attempt["run_id"]))
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (attempt["run_id"],),
        ).fetchone()
        if str(attempt["state"]) in {"succeeded", "failed"} and lease is not None and str(lease["state"]) in TERMINAL_RUN_STATUSES:
            release_resource_allocation(connection, attempt_id=normalized_attempt_id, released_at=finished_at)
            connection.commit()
            return {"accepted": False, "reason": "already_terminal"}
        if not _is_current_lease(lease, normalized_attempt_id, lease_generation):
            _fence_attempt_record(
                connection,
                attempt_id=normalized_attempt_id,
                generation=lease_generation,
                reason="stale_generation",
                occurred_at=finished_at,
                run=run,
            )
            connection.commit()
            return {"accepted": False, "reason": "stale_generation"}

        connection.execute(
            """
            UPDATE run_attempts
            SET state = ?, finished_at = ?, exit_code = ?, updated_at = ?
            WHERE attempt_id = ?
            """,
            (normalized_state, finished_at, exit_code, finished_at, normalized_attempt_id),
        )
        terminal_job_state = _terminal_job_state_for_attempt_state(normalized_state)
        connection.execute(
            "UPDATE run_jobs SET state = ?, updated_at = ? WHERE job_id = ?",
            (terminal_job_state, finished_at, attempt["job_id"]),
        )
        connection.execute(
            "UPDATE run_leases SET state = ?, updated_at = ? WHERE run_id = ?",
            (terminal_job_state, finished_at, attempt["run_id"]),
        )
        release_resource_allocation(connection, attempt_id=normalized_attempt_id, released_at=finished_at)
        mark_worker_slot_idle(
            connection,
            worker_id=str(attempt["worker_id"]),
            session_id=str(attempt["session_id"] or ""),
            slot_id=str(attempt["slot_id"] or "slot-0"),
            updated_at=finished_at,
        )
        append_run_event_v2(
            connection,
            run_id=str(attempt["run_id"]),
            event_type="run_attempt_completed",
            stage="complete",
            state_version=int(run["state_version"]),
            message="Run attempt completed.",
            request_id=str(run["request_id"]),
            payload={
                "attemptId": normalized_attempt_id,
                "leaseGeneration": int(lease_generation),
                "state": normalized_state,
                "exitCode": exit_code,
            },
            occurred_at=finished_at,
        )
        connection.commit()
        return {"accepted": True, "state": normalized_state}


def _terminal_job_state_for_attempt_state(state: str) -> str:
    normalized = str(state or "").strip().lower()
    if normalized == "succeeded":
        return "completed"
    if normalized in {"canceled", "cancelled"}:
        return "cancelled"
    return "failed"


def _select_claimable_job(connection: sqlite3.Connection, now: str, queue_name: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT jobs.*
        FROM run_jobs AS jobs
        WHERE jobs.state = 'queued'
          AND jobs.available_at <= ?
          AND jobs.dead_lettered_at IS NULL
          AND jobs.queue_name = ?
        ORDER BY jobs.priority DESC, jobs.available_at ASC, jobs.created_at ASC, jobs.job_id ASC
        LIMIT 1
        """,
        (now, queue_name),
    ).fetchone()


def _fence_attempt_record(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    generation: int,
    reason: str,
    occurred_at: str,
    run: sqlite3.Row,
) -> None:
    existing = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if existing is None:
        return
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
    release_resource_allocation(connection, attempt_id=attempt_id, released_at=occurred_at)
    append_run_event_v2(
        connection,
        run_id=str(existing["run_id"]),
        event_type="run_attempt_fenced",
        stage="fence",
        state_version=int(run["state_version"]),
        message="Run attempt fenced.",
        request_id=str(run["request_id"]),
        payload={"attemptId": attempt_id, "leaseGeneration": int(generation), "reason": reason},
        occurred_at=occurred_at,
    )


def _is_current_lease(lease: sqlite3.Row | None, attempt_id: str, generation: int) -> bool:
    return bool(
        lease is not None
        and lease["attempt_id"] == attempt_id
        and int(lease["lease_generation"]) == int(generation)
        and lease["state"] == "active"
    )


def _claim_to_dict(job: sqlite3.Row, attempt: sqlite3.Row, lease: sqlite3.Row) -> dict[str, Any]:
    attempt_payload = _attempt_row_to_dict(attempt)
    lease_payload = _lease_row_to_dict(lease)
    return {
        "jobId": job["job_id"],
        "runId": job["run_id"],
        "attemptId": attempt["attempt_id"],
        "leaseGeneration": int(lease["lease_generation"]),
        "job": _job_row_to_dict(job),
        "attempt": attempt_payload,
        "lease": lease_payload,
    }


def _job_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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
        "retryPolicy": _json_object(row["retry_policy_json"]),
        "timeoutPolicy": _json_object(row["timeout_policy_json"]),
        "deadLetteredAt": row["dead_lettered_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _attempt_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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
        "workDir": row["work_dir"],
        "processPid": row["process_pid"],
        "processGroupId": row["process_group_id"],
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


def _lease_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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


def _fetch_run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    return row


def _fetch_attempt_row(connection: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise KeyError(attempt_id)
    return row


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_object(value: str | None) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _optional_positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
