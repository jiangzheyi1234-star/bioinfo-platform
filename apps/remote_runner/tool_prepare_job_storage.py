from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage_core import get_connection, now_iso
from .tool_prepare_job_records import (
    event_row_to_dict,
    job_row_to_dict,
)
from .tool_platform_storage import record_prepare_job_validation_result
from .tool_prepare_reservations import tool_prepare_job_reservation


TERMINAL_PREPARE_JOB_STATUSES = {"succeeded", "failed", "cancelled", "waiting_resource", "exhausted"}
TERMINAL_PREPARE_JOB_STATUS_SQL = "(" + ", ".join(f"'{status}'" for status in sorted(TERMINAL_PREPARE_JOB_STATUSES)) + ")"


def create_tool_prepare_job(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    now = now_iso()
    job_id = f"toolprep_{uuid.uuid4().hex[:12]}"
    tool_id = str(payload.get("id") or "").strip()
    reservation = tool_prepare_job_reservation(payload, tool_id)
    max_attempts = _positive_int(payload.get("maxAttempts"), default=3)
    backoff_seconds = _positive_int(payload.get("backoffSeconds"), default=30)
    with get_connection(cfg) as connection:
        existing_row = _fetch_active_prepare_job_by_reservation(connection, reservation["key"])
        if existing_row is not None:
            job = _job_with_events(connection, existing_row)
            job["reusedExisting"] = True
            return job
        try:
            connection.execute(
                """
                INSERT INTO tool_prepare_jobs (
                    job_id, status, stage, message, tool_id,
                    reservation_key, reservation_package_spec, reservation_validation_target,
                    request_json, result_json, error_code,
                    max_attempts, backoff_seconds,
                    created_at, updated_at,
                    started_at, finished_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "queued",
                    "queued",
                    "Prepare job queued.",
                    tool_id,
                    reservation["key"],
                    reservation["packageSpec"],
                    reservation["validationTarget"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    None,
                    None,
                    max_attempts,
                    backoff_seconds,
                    now,
                    now,
                    None,
                    None,
                    None,
                ),
            )
        except sqlite3.IntegrityError:
            existing_row = _fetch_active_prepare_job_by_reservation(connection, reservation["key"])
            if existing_row is None:
                raise
            job = _job_with_events(connection, existing_row)
            job["reusedExisting"] = True
            return job
        _insert_prepare_job_event(
            connection,
            job_id=job_id,
            stage="queued",
            level="info",
            message="Prepare job queued.",
            details={"toolId": tool_id, "reservation": _reservation_payload(reservation)},
        )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    job["reusedExisting"] = False
    return job


def fetch_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str) -> dict[str, Any] | None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return None
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM tool_prepare_jobs WHERE job_id = ?", (normalized,)).fetchone()
        event_rows = (
            connection.execute(
                """
                SELECT * FROM tool_prepare_job_events
                WHERE job_id = ?
                ORDER BY rowid ASC
                """,
                (normalized,),
            ).fetchall()
            if row is not None
            else []
        )
    return job_row_to_dict(row, [event_row_to_dict(event_row) for event_row in event_rows]) if row is not None else None


def _fetch_active_prepare_job_by_reservation(connection: sqlite3.Connection, reservation_key: str) -> sqlite3.Row | None:
    normalized_key = str(reservation_key or "")
    if not normalized_key:
        return None
    return connection.execute(
        """
        SELECT *
        FROM tool_prepare_jobs
        WHERE reservation_key = ? AND status IN ('queued', 'running')
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (normalized_key,),
    ).fetchone()


def _job_with_events(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    event_rows = connection.execute(
        """
        SELECT * FROM tool_prepare_job_events
        WHERE job_id = ?
        ORDER BY rowid ASC
        """,
        (row["job_id"],),
    ).fetchall()
    return job_row_to_dict(row, [event_row_to_dict(event_row) for event_row in event_rows])


def _reservation_payload(reservation: dict[str, str]) -> dict[str, str]:
    return {
        "key": reservation["key"],
        "packageSpec": reservation["packageSpec"],
        "validationTarget": reservation["validationTarget"],
    }


def require_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str) -> dict[str, Any]:
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    return job


def list_latest_tool_prepare_jobs_by_tool_id(cfg: RemoteRunnerConfig, tool_ids: list[str]) -> dict[str, dict[str, Any]]:
    normalized_ids = _normalized_tool_ids(tool_ids)
    if not normalized_ids:
        return {}
    placeholders = ", ".join("?" for _ in normalized_ids)
    with get_connection(cfg) as connection:
        rows = connection.execute(
            f"""
            SELECT rowid, *
            FROM tool_prepare_jobs
            WHERE tool_id IN ({placeholders})
            ORDER BY rowid DESC
            """,
            tuple(normalized_ids),
        ).fetchall()
    latest_jobs_by_tool_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        tool_id = str(row["tool_id"] or "").strip()
        if not tool_id or tool_id in latest_jobs_by_tool_id:
            continue
        latest_jobs_by_tool_id[tool_id] = _job_row_to_safe_summary(row)
    return latest_jobs_by_tool_id


def claim_next_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str = "tool-prepare-worker",
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    claimed_at = str(now or now_iso())
    normalized_worker_id = str(worker_id or "tool-prepare-worker").strip() or "tool-prepare-worker"
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT *
            FROM tool_prepare_jobs
            WHERE (
                status = 'queued'
                AND COALESCE(next_attempt_at, created_at) <= ?
            ) OR (
                status = 'running'
                AND (claimed_until IS NULL OR claimed_until < ?)
            )
            ORDER BY created_at ASC, job_id ASC
            LIMIT 1
            """,
            (claimed_at, claimed_at),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        reclaimed = str(row["status"] or "") == "running"
        next_attempts = int(row["attempts"] or 0) + 1
        claimed_until = _add_seconds(claimed_at, int(lease_seconds))
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET status = 'running',
                stage = 'claimed',
                message = 'Prepare job claimed by worker.',
                claimed_by = ?,
                claimed_until = ?,
                heartbeat_at = ?,
                attempts = ?,
                next_attempt_at = NULL,
                exhausted_at = NULL,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                normalized_worker_id,
                claimed_until,
                claimed_at,
                next_attempts,
                claimed_at,
                claimed_at,
                row["job_id"],
            ),
        )
        _insert_prepare_job_event(
            connection,
            job_id=str(row["job_id"]),
            stage="reclaimed" if reclaimed else "claimed",
            level="info",
            message="Prepare job reclaimed after an expired lease." if reclaimed else "Prepare job claimed by worker.",
            details={"workerId": normalized_worker_id, "attempts": next_attempts, "claimedUntil": claimed_until},
        )
        connection.commit()
    return fetch_tool_prepare_job(cfg, str(row["job_id"]))


def heartbeat_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    job_id: str,
    *,
    worker_id: str,
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    heartbeat_at = str(now or now_iso())
    normalized_job_id = str(job_id or "").strip()
    normalized_worker_id = str(worker_id or "").strip()
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM tool_prepare_jobs WHERE job_id = ?", (normalized_job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if str(row["status"] or "") != "running" or str(row["claimed_by"] or "") != normalized_worker_id:
            return {"accepted": False, "reason": "not_current_worker"}
        claimed_until = _add_seconds(heartbeat_at, int(lease_seconds))
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET heartbeat_at = ?, claimed_until = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND claimed_by = ?
            """,
            (heartbeat_at, claimed_until, heartbeat_at, normalized_job_id, normalized_worker_id),
        )
        connection.commit()
    return {"accepted": True, "claimedUntil": claimed_until}


def mark_tool_prepare_job_worker_failure(
    cfg: RemoteRunnerConfig,
    job_id: str,
    *,
    code: str,
    message: str,
    now: str | None = None,
    retry_delay_seconds: int = 30,
) -> dict[str, Any]:
    failed_at = str(now or now_iso())
    normalized_code = str(code or "TOOL_PREPARE_WORKER_FAILED").strip() or "TOOL_PREPARE_WORKER_FAILED"
    normalized_message = str(message or normalized_code).strip() or normalized_code
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM tool_prepare_jobs WHERE job_id = ?", (str(job_id or "").strip(),)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if str(row["status"] or "") in TERMINAL_PREPARE_JOB_STATUSES:
            return _job_with_events(connection, row)
        attempts = int(row["attempts"] or 0)
        max_attempts = max(1, int(row["max_attempts"] or 1))
        worker_error = {
            "code": normalized_code,
            "message": normalized_message,
            "at": failed_at,
            "attempts": attempts,
            "maxAttempts": max_attempts,
        }
        if attempts >= max_attempts:
            connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'exhausted',
                    stage = 'exhausted',
                    message = ?,
                    error_code = ?,
                    claimed_by = '',
                    claimed_until = NULL,
                    next_attempt_at = NULL,
                    exhausted_at = ?,
                    last_worker_error_json = ?,
                    updated_at = ?,
                    finished_at = COALESCE(finished_at, ?)
                WHERE job_id = ? AND status NOT IN ('succeeded', 'failed', 'cancelled', 'waiting_resource', 'exhausted')
                """,
                (
                    normalized_message,
                    normalized_code,
                    failed_at,
                    json.dumps(worker_error, ensure_ascii=False, sort_keys=True),
                    failed_at,
                    failed_at,
                    job_id,
                ),
            )
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="exhausted",
                level="error",
                message=normalized_message,
                details=worker_error,
            )
            record_prepare_job_validation_result(
                connection,
                job_id=job_id,
                stage="exhausted",
                status="exhausted",
                failure_code=normalized_code,
                created_at=failed_at,
            )
        else:
            next_attempt_at = _add_seconds(failed_at, int(retry_delay_seconds))
            connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'queued',
                    stage = 'retry_wait',
                    message = ?,
                    error_code = ?,
                    claimed_by = '',
                    claimed_until = NULL,
                    next_attempt_at = ?,
                    last_worker_error_json = ?,
                    updated_at = ?
                WHERE job_id = ? AND status NOT IN ('succeeded', 'failed', 'cancelled', 'waiting_resource', 'exhausted')
                """,
                (
                    normalized_message,
                    normalized_code,
                    next_attempt_at,
                    json.dumps(worker_error, ensure_ascii=False, sort_keys=True),
                    failed_at,
                    job_id,
                ),
            )
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="retry_wait",
                level="warning",
                message=normalized_message,
                details={**worker_error, "nextAttemptAt": next_attempt_at},
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def _normalized_tool_ids(tool_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in tool_ids:
        tool_id = str(value or "").strip()
        if not tool_id or tool_id in seen:
            continue
        seen.add(tool_id)
        normalized.append(tool_id)
    return normalized


def _job_row_to_safe_summary(row: Any) -> dict[str, Any]:
    result = json.loads(row["result_json"] or "{}") if row["result_json"] else {}
    contract = result.get("toolContract") if isinstance(result, dict) and isinstance(result.get("toolContract"), dict) else {}
    state = str(contract.get("state") or "").strip()
    succeeded = str(row["status"] or "") == "succeeded"
    workflow_ready = succeeded and (bool(contract.get("workflowReady")) or state in {"WorkflowReady", "ProductionEnabled"})
    production_enabled = succeeded and (
        bool(contract.get("productionEnabled"))
        or str(contract.get("state") or "") == "ProductionEnabled"
    )
    return {
        "jobId": row["job_id"],
        "toolId": row["tool_id"],
        "status": row["status"],
        "stage": row["stage"],
        "message": row["message"],
        "errorCode": row["error_code"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "cancelledAt": row["cancelled_at"],
        "resultState": state if succeeded else "",
        "workflowReady": workflow_ready,
        "productionEnabled": production_enabled,
    }


def record_tool_prepare_job_event(
    cfg: RemoteRunnerConfig,
    job_id: str,
    *,
    stage: str,
    message: str,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now_iso()
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    normalized_stage = str(stage or "running").strip() or "running"
    normalized_message = str(message or "").strip() or "Prepare job updated."
    normalized_level = str(level or "info").strip() or "info"
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT status FROM tool_prepare_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if row["status"] not in TERMINAL_PREPARE_JOB_STATUSES:
            connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'running', stage = ?, message = ?, updated_at = ?, started_at = COALESCE(started_at, ?)
                WHERE job_id = ? AND status IN ('queued', 'running')
                """,
                (normalized_stage, normalized_message, now, now, job_id),
            )
            connection.execute(
                """
                INSERT INTO tool_prepare_job_events (event_id, job_id, stage, level, message, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    job_id,
                    normalized_stage,
                    normalized_level,
                    normalized_message,
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def _insert_prepare_job_event(
    connection: Any,
    *,
    job_id: str,
    stage: str,
    level: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tool_prepare_job_events (event_id, job_id, stage, level, message, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            job_id,
            stage,
            level,
            message,
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            now_iso(),
        ),
    )


def complete_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    now = now_iso()
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            f"""
            UPDATE tool_prepare_jobs
            SET status = 'succeeded', stage = 'published', message = ?, result_json = ?, updated_at = ?, finished_at = ?
            WHERE job_id = ? AND status NOT IN {TERMINAL_PREPARE_JOB_STATUS_SQL}
            """,
            (
                str(result.get("message") or "Tool revision published."),
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                now,
                now,
                job_id,
            ),
        )
        if cursor.rowcount:
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="published",
                level="success",
                message=str(result.get("message") or "Tool revision published."),
                details={"toolRevisionId": str(result.get("toolRevisionId") or "")},
            )
            record_prepare_job_validation_result(
                connection,
                job_id=job_id,
                stage="published",
                status="succeeded",
                result=result,
                created_at=now,
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def fail_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str, *, code: str, message: str) -> dict[str, Any]:
    now = now_iso()
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            f"""
            UPDATE tool_prepare_jobs
            SET status = 'failed', stage = 'failed', message = ?, error_code = ?, updated_at = ?, finished_at = ?
            WHERE job_id = ? AND status NOT IN {TERMINAL_PREPARE_JOB_STATUS_SQL}
            """,
            (message, code, now, now, job_id),
        )
        if cursor.rowcount:
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="failed",
                level="error",
                message=message,
                details={"code": code},
            )
            record_prepare_job_validation_result(
                connection,
                job_id=job_id,
                stage="failed",
                status="failed",
                failure_code=code,
                created_at=now,
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def mark_tool_prepare_job_waiting_resource(
    cfg: RemoteRunnerConfig,
    job_id: str,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now_iso()
    normalized_code = str(code or "WORKFLOW_RESOURCE_BINDING_REQUIRED").strip() or "WORKFLOW_RESOURCE_BINDING_REQUIRED"
    normalized_message = str(message or normalized_code).strip() or normalized_code
    event_details = {"code": normalized_code, **(details or {})}
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            f"""
            UPDATE tool_prepare_jobs
            SET status = 'waiting_resource', stage = 'waiting_resource', message = ?, error_code = ?,
                updated_at = ?, finished_at = ?
            WHERE job_id = ? AND status NOT IN {TERMINAL_PREPARE_JOB_STATUS_SQL}
            """,
            (normalized_message, normalized_code, now, now, job_id),
        )
        if cursor.rowcount:
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="waiting_resource",
                level="warning",
                message=normalized_message,
                details=event_details,
            )
            record_prepare_job_validation_result(
                connection,
                job_id=job_id,
                stage="waiting_resource",
                status="waiting_resource",
                failure_code=normalized_code,
                created_at=now,
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def cancel_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str) -> dict[str, Any]:
    now = now_iso()
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            f"""
            UPDATE tool_prepare_jobs
            SET status = 'cancelled', stage = 'cancelled', message = 'Prepare job cancelled.',
                updated_at = ?, finished_at = COALESCE(finished_at, ?), cancelled_at = ?
            WHERE job_id = ? AND status NOT IN {TERMINAL_PREPARE_JOB_STATUS_SQL}
            """,
            (now, now, now, job_id),
        )
        if cursor.rowcount:
            _insert_prepare_job_event(
                connection,
                job_id=job_id,
                stage="cancelled",
                level="warning",
                message="Prepare job cancelled.",
            )
            record_prepare_job_validation_result(
                connection,
                job_id=job_id,
                stage="cancelled",
                status="cancelled",
                created_at=now,
            )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    if cursor.rowcount == 0 and job["status"] not in TERMINAL_PREPARE_JOB_STATUSES:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    return job


def tool_prepare_job_cancelled(cfg: RemoteRunnerConfig, job_id: str) -> bool:
    job = fetch_tool_prepare_job(cfg, job_id)
    return job is not None and job["status"] == "cancelled"


def tool_prepare_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("request")
    return payload if isinstance(payload, dict) else {}


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
