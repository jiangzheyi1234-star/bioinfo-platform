from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2
from .storage_core import get_connection, now_iso


def enqueue_run_job(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    priority: int = 0,
    available_at: str | None = None,
) -> dict[str, Any]:
    queued_at = _optional_text(available_at) or now_iso()
    with get_connection(cfg) as connection:
        row = enqueue_run_job_record(
            connection,
            run_id=run_id,
            priority=priority,
            available_at=queued_at,
        )
        connection.commit()
        return _job_row_to_dict(row)


def enqueue_run_job_record(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    priority: int = 0,
    available_at: str,
) -> sqlite3.Row:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
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
            job_id, run_id, state, priority, available_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, normalized_run_id, "queued", int(priority), available_at, available_at, available_at),
    )
    append_run_event_v2(
        connection,
        run_id=normalized_run_id,
        event_type="run_job_queued",
        stage="queue",
        state_version=int(run["state_version"]),
        message="Run job queued.",
        request_id=str(run["request_id"]),
        payload={"jobId": job_id},
        occurred_at=available_at,
    )
    return connection.execute("SELECT * FROM run_jobs WHERE job_id = ?", (job_id,)).fetchone()


def claim_next_run_job(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    now: str | None = None,
    lease_seconds: int = 60,
) -> dict[str, Any] | None:
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    claimed_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        job = _select_claimable_job(connection, claimed_at)
        if job is None:
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
            _fence_attempt_record(
                connection,
                attempt_id=str(current_lease["attempt_id"]),
                generation=int(current_lease["lease_generation"]),
                reason="lease_expired",
                occurred_at=claimed_at,
                run=run,
            )

        attempt_id = f"att_{uuid.uuid4().hex[:12]}"
        work_dir = str(Path(cfg.work_dir) / "attempts" / attempt_id)
        expires_at = _add_seconds(claimed_at, int(lease_seconds))
        connection.execute(
            """
            INSERT INTO run_attempts (
                attempt_id, run_id, job_id, lease_generation, state, worker_id,
                work_dir, process_group_id, started_at, finished_at, exit_code,
                fenced_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                job["run_id"],
                job["job_id"],
                next_generation,
                "running",
                normalized_worker_id,
                work_dir,
                None,
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
                expires_at, state, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                attempt_id = excluded.attempt_id,
                lease_generation = excluded.lease_generation,
                worker_id = excluded.worker_id,
                heartbeat_at = excluded.heartbeat_at,
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
                expires_at,
                "active",
                claimed_at,
            ),
        )
        connection.execute(
            "UPDATE run_jobs SET state = ?, updated_at = ? WHERE job_id = ?",
            ("claimed", claimed_at, job["job_id"]),
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
                "workerId": normalized_worker_id,
            },
            occurred_at=claimed_at,
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
        terminal_job_state = "completed" if normalized_state == "succeeded" else "failed"
        connection.execute(
            "UPDATE run_jobs SET state = ?, updated_at = ? WHERE job_id = ?",
            (terminal_job_state, finished_at, attempt["job_id"]),
        )
        connection.execute(
            "UPDATE run_leases SET state = ?, updated_at = ? WHERE run_id = ?",
            (terminal_job_state, finished_at, attempt["run_id"]),
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


def _select_claimable_job(connection: sqlite3.Connection, now: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT jobs.*
        FROM run_jobs AS jobs
        LEFT JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        WHERE (
            jobs.state = 'queued'
            AND jobs.available_at <= ?
        ) OR (
            jobs.state = 'claimed'
            AND leases.state = 'active'
            AND leases.expires_at < ?
        )
        ORDER BY jobs.priority DESC, jobs.available_at ASC, jobs.created_at ASC, jobs.job_id ASC
        LIMIT 1
        """,
        (now, now),
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
        "priority": int(row["priority"]),
        "availableAt": row["available_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _attempt_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "attemptId": row["attempt_id"],
        "runId": row["run_id"],
        "jobId": row["job_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "state": row["state"],
        "workerId": row["worker_id"],
        "workDir": row["work_dir"],
        "processGroupId": row["process_group_id"],
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


def _add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
