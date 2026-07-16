from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError, RemoteRunnerOperationBlockedError
from .execution_lifecycle_guard import ensure_execution_lifecycle_admission_open_for_connection
from .storage_core import get_connection, now_iso
from .tool_platform_storage import record_prepare_job_validation_result
from .tool_prepare_attempt_mutations import (
    fail_tool_prepare_job,
    mark_tool_prepare_job_waiting_resource,
    mark_tool_prepare_job_worker_failure,
    record_tool_prepare_job_event,
)
from .tool_prepare_claims import claim_next_tool_prepare_job, heartbeat_tool_prepare_job
from .tool_prepare_job_records import event_row_to_dict, job_row_to_dict
from .tool_prepare_reservations import tool_prepare_job_reservation


TERMINAL_PREPARE_JOB_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "waiting_resource",
    "exhausted",
}
TERMINAL_PREPARE_JOB_STATUS_SQL = (
    "(" + ", ".join(f"'{status}'" for status in sorted(TERMINAL_PREPARE_JOB_STATUSES)) + ")"
)


def create_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = now_iso()
    job_id = f"toolprep_{uuid.uuid4().hex[:12]}"
    tool_id = str(payload.get("id") or "").strip()
    reservation = tool_prepare_job_reservation(payload, tool_id)
    max_attempts = _positive_int(payload.get("maxAttempts"), default=3)
    backoff_seconds = _positive_int(payload.get("backoffSeconds"), default=30)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_row = _fetch_active_prepare_job_by_reservation(
            connection,
            reservation["key"],
        )
        if existing_row is not None:
            connection.commit()
            job = _job_with_events(connection, existing_row)
            job["reusedExisting"] = True
            return job
        ensure_execution_lifecycle_admission_open_for_connection(connection, now=now)
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
            existing_row = _fetch_active_prepare_job_by_reservation(
                connection,
                reservation["key"],
            )
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
            details={
                "toolId": tool_id,
                "reservation": _reservation_payload(reservation),
            },
            created_at=now,
        )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
    job["reusedExisting"] = False
    return job


def fetch_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    job_id: str,
) -> dict[str, Any] | None:
    normalized = str(job_id or "").strip()
    if not normalized:
        return None
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM tool_prepare_jobs WHERE job_id = ?",
            (normalized,),
        ).fetchone()
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
    return (
        job_row_to_dict(
            row,
            [event_row_to_dict(event_row) for event_row in event_rows],
        )
        if row is not None
        else None
    )


def _fetch_active_prepare_job_by_reservation(
    connection: sqlite3.Connection,
    reservation_key: str,
) -> sqlite3.Row | None:
    normalized_key = str(reservation_key or "")
    if not normalized_key:
        return None
    return connection.execute(
        """
        SELECT jobs.*
        FROM tool_prepare_jobs AS jobs
        WHERE jobs.reservation_key = ?
          AND (
              jobs.status IN ('queued', 'running')
              OR EXISTS (
                  SELECT 1
                  FROM tool_prepare_attempts AS attempts
                  WHERE attempts.job_id = jobs.job_id
                    AND attempts.state IN ('active', 'recovery_required')
              )
          )
        ORDER BY
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM tool_prepare_attempts AS attempts
                    WHERE attempts.job_id = jobs.job_id
                      AND attempts.state IN ('active', 'recovery_required')
                ) THEN 0
                ELSE 1
            END,
            jobs.rowid DESC
        LIMIT 1
        """,
        (normalized_key,),
    ).fetchone()


def _job_with_events(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    event_rows = connection.execute(
        """
        SELECT * FROM tool_prepare_job_events
        WHERE job_id = ?
        ORDER BY rowid ASC
        """,
        (row["job_id"],),
    ).fetchall()
    return job_row_to_dict(
        row,
        [event_row_to_dict(event_row) for event_row in event_rows],
    )


def _reservation_payload(reservation: dict[str, str]) -> dict[str, str]:
    return {
        "key": reservation["key"],
        "packageSpec": reservation["packageSpec"],
        "validationTarget": reservation["validationTarget"],
    }


def require_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    job_id: str,
) -> dict[str, Any]:
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    return job


def list_tool_prepare_jobs(
    cfg: RemoteRunnerConfig,
    *,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_status = str(status or "").strip()
    bounded_limit = min(100, max(1, int(limit)))
    bounded_offset = max(0, int(offset))
    where_sql = "WHERE status = ?" if normalized_status else ""
    params: tuple[Any, ...] = (normalized_status,) if normalized_status else ()
    with get_connection(cfg) as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM tool_prepare_jobs {where_sql}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT *
            FROM tool_prepare_jobs
            {where_sql}
            ORDER BY created_at DESC, job_id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, bounded_limit, bounded_offset),
        ).fetchall()
        count_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM tool_prepare_jobs
            GROUP BY status
            """
        ).fetchall()
        event_rows_by_job_id = _events_by_job_id(
            connection,
            [str(row["job_id"]) for row in rows],
        )
    return {
        "items": [
            job_row_to_dict(
                row,
                [
                    event_row_to_dict(event)
                    for event in event_rows_by_job_id.get(str(row["job_id"]), [])
                ],
            )
            for row in rows
        ],
        "total": int(total or 0),
        "limit": bounded_limit,
        "offset": bounded_offset,
        "statusCounts": _prepare_job_status_counts(count_rows),
    }


def _events_by_job_id(
    connection: sqlite3.Connection,
    job_ids: list[str],
) -> dict[str, list[sqlite3.Row]]:
    if not job_ids:
        return {}
    placeholders = ", ".join("?" for _ in job_ids)
    rows = connection.execute(
        f"""
        SELECT *
        FROM tool_prepare_job_events
        WHERE job_id IN ({placeholders})
        ORDER BY rowid ASC
        """,
        tuple(job_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {job_id: [] for job_id in job_ids}
    for row in rows:
        grouped.setdefault(str(row["job_id"]), []).append(row)
    return grouped


def _prepare_job_status_counts(rows: list[Any]) -> dict[str, int]:
    counts = {
        status: 0
        for status in sorted(TERMINAL_PREPARE_JOB_STATUSES | {"queued", "running"})
    }
    for row in rows:
        counts[str(row["status"])] = int(row["count"] or 0)
    return counts


def list_latest_tool_prepare_jobs_by_tool_id(
    cfg: RemoteRunnerConfig,
    tool_ids: list[str],
) -> dict[str, dict[str, Any]]:
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
    contract = (
        result.get("toolContract")
        if isinstance(result, dict) and isinstance(result.get("toolContract"), dict)
        else {}
    )
    state = str(contract.get("state") or "").strip()
    succeeded = str(row["status"] or "") == "succeeded"
    workflow_ready = succeeded and (
        bool(contract.get("workflowReady"))
        or state in {"WorkflowReady", "ProductionEnabled"}
    )
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
        "validationResultId": (
            str(result.get("validationResultId") or "") if succeeded else ""
        ),
        "evidenceId": str(result.get("evidenceId") or "") if succeeded else "",
    }


def _insert_prepare_job_event(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    stage: str,
    level: str,
    message: str,
    details: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tool_prepare_job_events (
            event_id, job_id, stage, level, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            job_id,
            stage,
            level,
            message,
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            created_at or now_iso(),
        ),
    )


def cancel_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    job_id: str,
) -> dict[str, Any]:
    cancelled_at = now_iso()
    normalized_job_id = str(job_id or "").strip()
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM tool_prepare_jobs WHERE job_id = ?",
                (normalized_job_id,),
            ).fetchone()
            if row is None:
                raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
            if str(row["status"] or "") not in TERMINAL_PREPARE_JOB_STATUSES:
                claim_owner = str(row["claimed_by"] or "")
                generation = int(row["attempts"] or 0)
                updated = connection.execute(
                    f"""
                    UPDATE tool_prepare_jobs
                    SET status = 'cancelled',
                        stage = 'cancelled',
                        message = 'Prepare job cancelled.',
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?),
                        cancelled_at = ?
                    WHERE job_id = ?
                      AND status NOT IN {TERMINAL_PREPARE_JOB_STATUS_SQL}
                      AND COALESCE(claimed_by, '') = ?
                      AND attempts = ?
                    """,
                    (
                        cancelled_at,
                        cancelled_at,
                        cancelled_at,
                        normalized_job_id,
                        claim_owner,
                        generation,
                    ),
                )
                if updated.rowcount != 1:
                    raise RemoteRunnerOperationBlockedError(
                        "TOOL_PREPARE_CANCEL_JOB_PROJECTION_INVALID"
                    )
                open_attempt_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM tool_prepare_attempts
                        WHERE job_id = ?
                          AND state IN ('active', 'recovery_required')
                        """,
                        (normalized_job_id,),
                    ).fetchone()["count"]
                )
                attempt_update = connection.execute(
                    """
                    UPDATE tool_prepare_attempts
                    SET outcome_status = 'cancelled', updated_at = ?
                    WHERE job_id = ?
                      AND generation = ?
                      AND claim_owner = ?
                      AND state IN ('active', 'recovery_required')
                    """,
                    (
                        cancelled_at,
                        normalized_job_id,
                        generation,
                        claim_owner,
                    ),
                )
                claim_projection_matches = bool(claim_owner) == bool(
                    open_attempt_count
                )
                if (
                    open_attempt_count > 1
                    or attempt_update.rowcount != open_attempt_count
                    or not claim_projection_matches
                ):
                    raise RemoteRunnerOperationBlockedError(
                        "TOOL_PREPARE_CANCEL_CLAIM_PROJECTION_INVALID"
                    )
                _insert_prepare_job_event(
                    connection,
                    job_id=normalized_job_id,
                    stage="cancelled",
                    level="warning",
                    message="Prepare job cancelled.",
                    created_at=cancelled_at,
                )
                record_prepare_job_validation_result(
                    connection,
                    job_id=normalized_job_id,
                    stage="cancelled",
                    status="cancelled",
                    created_at=cancelled_at,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    job = fetch_tool_prepare_job(cfg, normalized_job_id)
    if job is None:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    return job


def tool_prepare_job_cancelled(
    cfg: RemoteRunnerConfig,
    job_id: str,
) -> bool:
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


__all__ = [
    "TERMINAL_PREPARE_JOB_STATUSES",
    "cancel_tool_prepare_job",
    "claim_next_tool_prepare_job",
    "create_tool_prepare_job",
    "fail_tool_prepare_job",
    "fetch_tool_prepare_job",
    "heartbeat_tool_prepare_job",
    "list_latest_tool_prepare_jobs_by_tool_id",
    "list_tool_prepare_jobs",
    "mark_tool_prepare_job_waiting_resource",
    "mark_tool_prepare_job_worker_failure",
    "record_tool_prepare_job_event",
    "require_tool_prepare_job",
    "tool_prepare_job_cancelled",
    "tool_prepare_job_payload",
]
