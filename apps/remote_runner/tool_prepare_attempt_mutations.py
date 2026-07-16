from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any
import uuid

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso
from .tool_platform_storage import record_prepare_job_validation_result
from .tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareClaimLostError,
    record_tool_prepare_attempt_outcome_for_connection,
    require_active_tool_prepare_claim_for_connection,
)


def record_tool_prepare_job_event(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    *,
    stage: str,
    message: str,
    level: str = "info",
    details: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    normalized_stage = _text_or_default(stage, "running")
    normalized_message = _text_or_default(message, "Prepare job updated.")
    normalized_level = _text_or_default(level, "info")
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            require_active_tool_prepare_claim_for_connection(connection, proof)
            updated = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET stage = ?, message = ?, updated_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND claimed_by = ?
                  AND attempts = ?
                """,
                (
                    normalized_stage,
                    normalized_message,
                    timestamp,
                    proof.job_id,
                    proof.claim_owner,
                    proof.generation,
                ),
            )
            _require_job_update(updated.rowcount, "event")
            _insert_event(
                connection,
                proof=proof,
                stage=normalized_stage,
                level=normalized_level,
                message=normalized_message,
                details=details,
                created_at=timestamp,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _mutation_result(proof, status="running", stage=normalized_stage)


def fail_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    *,
    code: str,
    message: str,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    normalized_code = _text_or_default(code, "TOOL_PREPARE_FAILED")
    normalized_message = _text_or_default(message, normalized_code)
    error = {
        "at": timestamp,
        "code": normalized_code,
        "message": normalized_message,
    }
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            record_tool_prepare_attempt_outcome_for_connection(
                connection,
                proof,
                outcome_status="failed",
                updated_at=timestamp,
                last_error=error,
            )
            updated = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'failed',
                    stage = 'failed',
                    message = ?,
                    error_code = ?,
                    updated_at = ?,
                    finished_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND claimed_by = ?
                  AND attempts = ?
                """,
                (
                    normalized_message,
                    normalized_code,
                    timestamp,
                    timestamp,
                    proof.job_id,
                    proof.claim_owner,
                    proof.generation,
                ),
            )
            _require_job_update(updated.rowcount, "failure")
            _insert_event(
                connection,
                proof=proof,
                stage="failed",
                level="error",
                message=normalized_message,
                details={"code": normalized_code},
                created_at=timestamp,
            )
            record_prepare_job_validation_result(
                connection,
                job_id=proof.job_id,
                stage="failed",
                status="failed",
                failure_code=normalized_code,
                created_at=timestamp,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _mutation_result(proof, status="failed", stage="failed")


def mark_tool_prepare_job_waiting_resource(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    normalized_code = _text_or_default(code, "WORKFLOW_RESOURCE_BINDING_REQUIRED")
    normalized_message = _text_or_default(message, normalized_code)
    event_details = {"code": normalized_code, **(details or {})}
    error = {
        "at": timestamp,
        "code": normalized_code,
        "details": details or {},
        "message": normalized_message,
    }
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            record_tool_prepare_attempt_outcome_for_connection(
                connection,
                proof,
                outcome_status="waiting_resource",
                updated_at=timestamp,
                last_error=error,
            )
            updated = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'waiting_resource',
                    stage = 'waiting_resource',
                    message = ?,
                    error_code = ?,
                    updated_at = ?,
                    finished_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND claimed_by = ?
                  AND attempts = ?
                """,
                (
                    normalized_message,
                    normalized_code,
                    timestamp,
                    timestamp,
                    proof.job_id,
                    proof.claim_owner,
                    proof.generation,
                ),
            )
            _require_job_update(updated.rowcount, "waiting-resource")
            _insert_event(
                connection,
                proof=proof,
                stage="waiting_resource",
                level="warning",
                message=normalized_message,
                details=event_details,
                created_at=timestamp,
            )
            record_prepare_job_validation_result(
                connection,
                job_id=proof.job_id,
                stage="waiting_resource",
                status="waiting_resource",
                failure_code=normalized_code,
                created_at=timestamp,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _mutation_result(proof, status="waiting_resource", stage="waiting_resource")


def mark_tool_prepare_job_worker_failure(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    *,
    code: str,
    message: str,
    now: str | None = None,
    retry_delay_seconds: int | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    normalized_code = _text_or_default(code, "TOOL_PREPARE_WORKER_FAILED")
    normalized_message = _text_or_default(message, normalized_code)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            require_active_tool_prepare_claim_for_connection(connection, proof)
            job = connection.execute(
                """
                SELECT attempts, max_attempts, backoff_seconds
                FROM tool_prepare_jobs
                WHERE job_id = ?
                  AND status = 'running'
                  AND claimed_by = ?
                  AND attempts = ?
                """,
                (proof.job_id, proof.claim_owner, proof.generation),
            ).fetchone()
            if job is None:
                raise ToolPrepareClaimLostError("worker failure job projection rejected")
            attempts = int(job["attempts"] or 0)
            max_attempts = int(job["max_attempts"] or 0)
            if max_attempts <= 0:
                raise ToolPrepareClaimLostError("prepare job max_attempts is invalid")
            worker_error = {
                "at": timestamp,
                "attempts": attempts,
                "code": normalized_code,
                "maxAttempts": max_attempts,
                "message": normalized_message,
            }
            exhausted = attempts >= max_attempts
            outcome_status = "exhausted" if exhausted else "retry_wait"
            record_tool_prepare_attempt_outcome_for_connection(
                connection,
                proof,
                outcome_status=outcome_status,
                updated_at=timestamp,
                last_error=worker_error,
            )
            if exhausted:
                next_attempt_at = None
                exhausted_at = timestamp
                updated = connection.execute(
                    """
                    UPDATE tool_prepare_jobs
                    SET status = 'exhausted',
                        stage = 'exhausted',
                        message = ?,
                        error_code = ?,
                        next_attempt_at = NULL,
                        exhausted_at = ?,
                        last_worker_error_json = ?,
                        updated_at = ?,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE job_id = ?
                      AND status = 'running'
                      AND claimed_by = ?
                      AND attempts = ?
                    """,
                    (
                        normalized_message,
                        normalized_code,
                        exhausted_at,
                        _json(worker_error),
                        timestamp,
                        timestamp,
                        proof.job_id,
                        proof.claim_owner,
                        proof.generation,
                    ),
                )
                _require_job_update(updated.rowcount, "worker exhaustion")
                _insert_event(
                    connection,
                    proof=proof,
                    stage="exhausted",
                    level="error",
                    message=normalized_message,
                    details=worker_error,
                    created_at=timestamp,
                )
                record_prepare_job_validation_result(
                    connection,
                    job_id=proof.job_id,
                    stage="exhausted",
                    status="exhausted",
                    failure_code=normalized_code,
                    created_at=timestamp,
                )
            else:
                delay_seconds = _retry_delay(
                    retry_delay_seconds,
                    default=int(job["backoff_seconds"] or 30),
                )
                next_attempt_at = _add_seconds(timestamp, delay_seconds)
                exhausted_at = None
                updated = connection.execute(
                    """
                    UPDATE tool_prepare_jobs
                    SET status = 'queued',
                        stage = 'retry_wait',
                        message = ?,
                        error_code = ?,
                        next_attempt_at = ?,
                        exhausted_at = NULL,
                        last_worker_error_json = ?,
                        updated_at = ?
                    WHERE job_id = ?
                      AND status = 'running'
                      AND claimed_by = ?
                      AND attempts = ?
                    """,
                    (
                        normalized_message,
                        normalized_code,
                        next_attempt_at,
                        _json(worker_error),
                        timestamp,
                        proof.job_id,
                        proof.claim_owner,
                        proof.generation,
                    ),
                )
                _require_job_update(updated.rowcount, "worker retry")
                _insert_event(
                    connection,
                    proof=proof,
                    stage="retry_wait",
                    level="warning",
                    message=normalized_message,
                    details={**worker_error, "nextAttemptAt": next_attempt_at},
                    created_at=timestamp,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        **_mutation_result(proof, status="exhausted" if exhausted else "queued", stage=outcome_status),
        "exhaustedAt": exhausted_at,
        "nextAttemptAt": next_attempt_at,
    }


def _insert_event(
    connection,
    *,
    proof: ToolPrepareAttemptProof,
    stage: str,
    level: str,
    message: str,
    details: dict[str, Any] | None,
    created_at: str,
) -> None:
    event_details = {
        **(details or {}),
        "attemptId": proof.attempt_id,
        "generation": proof.generation,
        "workerId": proof.worker_id,
    }
    connection.execute(
        """
        INSERT INTO tool_prepare_job_events (
            event_id, job_id, stage, level, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            proof.job_id,
            stage,
            level,
            message,
            _json(event_details),
            created_at,
        ),
    )


def _mutation_result(
    proof: ToolPrepareAttemptProof,
    *,
    status: str,
    stage: str,
) -> dict[str, Any]:
    return {
        "attemptId": proof.attempt_id,
        "generation": proof.generation,
        "jobId": proof.job_id,
        "stage": stage,
        "status": status,
    }


def _require_job_update(rowcount: int, operation: str) -> None:
    if rowcount != 1:
        raise ToolPrepareClaimLostError(f"{operation} compare-and-set failed")


def _timestamp(value: str | None) -> str:
    timestamp = str(value or now_iso()).strip()
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("TOOL_PREPARE_MUTATION_TIMESTAMP_INVALID") from exc
    return timestamp


def _retry_delay(value: int | None, *, default: int) -> int:
    try:
        delay = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("TOOL_PREPARE_RETRY_DELAY_INVALID") from exc
    if delay < 0:
        raise ValueError("TOOL_PREPARE_RETRY_DELAY_INVALID")
    return delay


def _add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text_or_default(value: str, default: str) -> str:
    return str(value or "").strip() or default


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "fail_tool_prepare_job",
    "mark_tool_prepare_job_waiting_resource",
    "mark_tool_prepare_job_worker_failure",
    "record_tool_prepare_job_event",
]
