from __future__ import annotations

import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso
from .tool_platform_storage import record_prepare_job_validation_result
from .tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareClaimLostError,
    record_tool_prepare_attempt_outcome_for_connection,
    require_active_tool_prepare_claim_for_connection,
)
from .tool_revisions import publish_tool_revision_record
from .tool_prepare_reservations import tool_prepare_job_reservation
from .tool_storage import upsert_tool_record


def publish_validated_tool_for_attempt(
    cfg: RemoteRunnerConfig,
    *,
    proof: ToolPrepareAttemptProof,
    validated_tool: dict[str, Any],
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Atomically publish a validated tool and complete its fenced prepare job."""

    occurred_at = str(completed_at or now_iso())
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            status_row = connection.execute(
                "SELECT status FROM tool_prepare_jobs WHERE job_id = ?",
                (proof.job_id,),
            ).fetchone()
            if status_row is not None and str(status_row["status"] or "") == "succeeded":
                replayed = _replay_succeeded_publication(connection, proof)
                connection.commit()
                return replayed

            require_active_tool_prepare_claim_for_connection(connection, proof)
            _require_validated_tool_binding(connection, proof, validated_tool)
            revision = publish_tool_revision_record(
                connection,
                validated_tool,
                published_at=occurred_at,
            )
            published = {
                **revision,
                "status": "published",
                "message": str(validated_tool.get("message") or "Tool revision published."),
            }
            saved = upsert_tool_record(connection, published, updated_at=occurred_at)
            validation = record_prepare_job_validation_result(
                connection,
                job_id=proof.job_id,
                stage="published",
                status="succeeded",
                result=saved,
                created_at=occurred_at,
            )
            validation_summary = _validation_summary(validation, job_id=proof.job_id)
            result = {
                **saved,
                "validationSummary": validation_summary,
                "validationResultId": validation["validationResultId"],
                "evidenceId": validation["evidenceId"],
            }
            record_tool_prepare_attempt_outcome_for_connection(
                connection,
                proof,
                outcome_status="succeeded",
                updated_at=occurred_at,
            )
            completed = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'succeeded',
                    stage = 'published',
                    message = ?,
                    result_json = ?,
                    error_code = NULL,
                    updated_at = ?,
                    finished_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND claimed_by = ?
                  AND attempts = ?
                """,
                (
                    str(result.get("message") or "Tool revision published."),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    occurred_at,
                    occurred_at,
                    proof.job_id,
                    proof.claim_owner,
                    proof.generation,
                ),
            )
            if completed.rowcount != 1:
                raise ToolPrepareClaimLostError("publication compare-and-set failed")
            _insert_published_event(
                connection,
                proof=proof,
                result=result,
                created_at=occurred_at,
            )
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise


def _replay_succeeded_publication(
    connection: Any,
    proof: ToolPrepareAttemptProof,
) -> dict[str, Any]:
    context = require_active_tool_prepare_claim_for_connection(
        connection,
        proof,
        required_status="succeeded",
    )
    if str(context["attempt"]["outcome_status"] or "") != "succeeded":
        raise ToolPrepareClaimLostError("succeeded job has no matching attempt outcome")
    result_row = connection.execute(
        "SELECT result_json FROM tool_prepare_jobs WHERE job_id = ?",
        (proof.job_id,),
    ).fetchone()
    if result_row is None:
        raise ToolPrepareClaimLostError("succeeded prepare job is missing")
    raw_result = result_row["result_json"]
    try:
        result = json.loads(raw_result or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ToolPrepareClaimLostError("succeeded job result is invalid") from exc
    if not isinstance(result, dict) or not result:
        raise ToolPrepareClaimLostError("succeeded job result is invalid")
    return result


def _require_validated_tool_binding(
    connection: Any,
    proof: ToolPrepareAttemptProof,
    validated_tool: dict[str, Any],
) -> None:
    row = connection.execute(
        """
        SELECT tool_id, reservation_package_spec, reservation_validation_target
        FROM tool_prepare_jobs
        WHERE job_id = ?
        """,
        (proof.job_id,),
    ).fetchone()
    if row is None:
        raise ToolPrepareClaimLostError("prepare job is missing")
    tool_id = str(validated_tool.get("id") or validated_tool.get("toolId") or "").strip()
    if not tool_id or tool_id != str(row["tool_id"] or "").strip():
        raise ToolPrepareClaimLostError("validated tool does not match prepare job")
    reservation = tool_prepare_job_reservation(validated_tool, tool_id)
    target_mismatch = (
        "validationTarget" in validated_tool
        and reservation["validationTarget"] != str(row["reservation_validation_target"] or "")
    )
    if reservation["packageSpec"] != str(row["reservation_package_spec"] or "") or target_mismatch:
        raise ToolPrepareClaimLostError("validated tool does not match prepare job reservation")


def _validation_summary(validation: dict[str, Any], *, job_id: str) -> dict[str, Any]:
    return {
        "latestResultId": str(validation.get("validationResultId") or ""),
        "evidenceId": str(validation.get("evidenceId") or ""),
        "latestJobId": job_id,
        "latestStage": str(validation.get("stage") or "published"),
        "latestStatus": str(validation.get("status") or "succeeded"),
        "failureCode": str(validation.get("failureCode") or ""),
        "updatedAt": str(validation.get("createdAt") or ""),
    }


def _insert_published_event(
    connection: Any,
    *,
    proof: ToolPrepareAttemptProof,
    result: dict[str, Any],
    created_at: str,
) -> None:
    details = {
        "attemptId": proof.attempt_id,
        "evidenceId": str(result.get("evidenceId") or ""),
        "generation": proof.generation,
        "toolRevisionId": str(result.get("toolRevisionId") or ""),
        "validationResultId": str(result.get("validationResultId") or ""),
    }
    connection.execute(
        """
        INSERT INTO tool_prepare_job_events (
            event_id, job_id, stage, level, message, details_json, created_at
        ) VALUES (?, ?, 'published', 'success', ?, ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            proof.job_id,
            str(result.get("message") or "Tool revision published."),
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            created_at,
        ),
    )


__all__ = ["publish_validated_tool_for_attempt"]
