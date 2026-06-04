from __future__ import annotations

import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage_core import get_connection, now_iso
from .tool_prepare_job_records import (
    event_row_to_dict,
    job_row_to_dict,
)


TERMINAL_PREPARE_JOB_STATUSES = {"succeeded", "failed", "cancelled", "waiting_resource"}
TERMINAL_PREPARE_JOB_STATUS_SQL = "(" + ", ".join(f"'{status}'" for status in sorted(TERMINAL_PREPARE_JOB_STATUSES)) + ")"


def create_tool_prepare_job(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    now = now_iso()
    job_id = f"toolprep_{uuid.uuid4().hex[:12]}"
    tool_id = str(payload.get("id") or "").strip()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO tool_prepare_jobs (
                job_id, status, stage, message, tool_id, request_json,
                result_json, error_code, created_at, updated_at, started_at, finished_at, cancelled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "queued",
                "queued",
                "Prepare job queued.",
                tool_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                None,
                None,
                now,
                now,
                None,
                None,
                None,
            ),
        )
        _insert_prepare_job_event(
            connection,
            job_id=job_id,
            stage="queued",
            level="info",
            message="Prepare job queued.",
            details={"toolId": tool_id},
        )
        connection.commit()
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise KeyError(job_id)
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


def require_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str) -> dict[str, Any]:
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise RemoteRunnerNotFoundError("TOOL_PREPARE_JOB_NOT_FOUND")
    return job


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
