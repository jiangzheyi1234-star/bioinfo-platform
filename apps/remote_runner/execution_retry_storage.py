from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2, record_run_command
from .execution_policy import retry_backoff_seconds_for_job
from .run_execution_storage import (
    RELEASED_LEASE_STATES,
    _add_seconds,
    _fetch_run_row,
    _optional_text,
    _required_text,
    _stable_json,
)
from .rule_partial_rerun_claim_preflight import (
    rule_partial_rerun_execution_options_requested,
    validate_rule_partial_rerun_claim_preflight,
)
from .rule_retry_execution_plan import rule_retry_execution_options
from .storage_core import get_connection, now_iso


RETRYABLE_RUN_STATUSES = {"failed", "canceled", "cancelled"}


def request_run_retry(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
    command_id: str | None = None,
    execution_options: dict[str, Any] | None = None,
    scope: str = "run",
    now: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    requested_at = _optional_text(now) or now_iso()
    normalized_actor = _optional_text(actor) or "remote-runner-api"
    normalized_reason = _optional_text(reason) or "operator_requested"
    normalized_scope = _retry_scope(scope)
    normalized_execution_options = execution_options or {}
    if rule_partial_rerun_execution_options_requested(normalized_execution_options):
        if normalized_scope != "rule":
            raise ValueError("RULE_RETRY_SCOPE_REQUIRED_FOR_RULE_EXECUTION_OPTIONS")
        validate_rule_partial_rerun_claim_preflight(
            normalized_execution_options,
            run_id=normalized_run_id,
            attempt_id="pending-worker-claim",
            lease_generation=1,
        )
        canonical_options = rule_retry_execution_options(
            _current_rule_retry_execution_plan(cfg, normalized_run_id)
        )
        if canonical_options != normalized_execution_options:
            raise ValueError("RULE_PARTIAL_RERUN_EXECUTION_OPTIONS_NOT_CURRENT")
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = _fetch_run_row(connection, normalized_run_id)
        run_status = str(run["status"] or "").lower()
        if run_status not in RETRYABLE_RUN_STATUSES:
            raise ValueError(f"RUN_RETRY_STATUS_NOT_RETRYABLE: {run_status}")
        job = connection.execute(
            "SELECT * FROM run_jobs WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        if job is None:
            raise ValueError("RUN_RETRY_JOB_NOT_FOUND")
        lease = connection.execute(
            "SELECT * FROM run_leases WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        if lease is not None and str(lease["state"]) == "active":
            raise ValueError("RUN_RETRY_ACTIVE_LEASE")
        if lease is not None and str(lease["state"]) not in RELEASED_LEASE_STATES:
            raise ValueError(f"RUN_RETRY_LEASE_NOT_RELEASED: {lease['state']}")
        attempt_count = int(job["attempt_count"])
        max_attempts = int(job["max_attempts"])
        remaining_attempts = max(0, max_attempts - attempt_count)
        if job["dead_lettered_at"] or remaining_attempts <= 0:
            raise ValueError("RUN_RETRY_MAX_ATTEMPTS_EXHAUSTED")
        job_state = str(job["state"])
        if job_state == "queued":
            raise ValueError("RUN_RETRY_ALREADY_QUEUED")
        if job_state == "claimed":
            raise ValueError("RUN_RETRY_JOB_CLAIMED")
        backoff_seconds = retry_backoff_seconds_for_job(job, fallback_seconds=0)
        available_at = _add_seconds(requested_at, backoff_seconds)
        if rule_partial_rerun_execution_options_requested(normalized_execution_options):
            validate_rule_partial_rerun_claim_preflight(
                normalized_execution_options,
                run_id=normalized_run_id,
                attempt_id="pending-worker-claim",
                lease_generation=attempt_count + 1,
            )
        command_payload = {
            "runId": normalized_run_id,
            "scope": normalized_scope,
            "reason": normalized_reason,
        }
        if normalized_execution_options:
            command_payload["executionOptions"] = normalized_execution_options
        command = record_run_command(
            connection,
            run_id=normalized_run_id,
            command_type="retry_run",
            command_id=command_id,
            payload=command_payload,
            actor=normalized_actor,
            requested_at=requested_at,
        )
        next_state_version = int(run["state_version"]) + 1
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?,
                started_at = NULL, finished_at = NULL, last_error_json = NULL,
                last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                "queued",
                "retry",
                next_state_version,
                "Run retry requested.",
                requested_at,
                normalized_run_id,
            ),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET state = ?, available_at = ?, wait_reason_json = '{}',
                execution_options_json = ?, dead_lettered_at = NULL, updated_at = ?
            WHERE job_id = ?
            """,
            ("queued", available_at, _stable_json(normalized_execution_options), requested_at, job["job_id"]),
        )
        event_payload = {
            "runId": normalized_run_id,
            "jobId": job["job_id"],
            "scope": normalized_scope,
            "reason": normalized_reason,
            "attemptCount": attempt_count,
            "maxAttempts": max_attempts,
            "remainingAttempts": remaining_attempts,
            "backoffSeconds": backoff_seconds,
            "availableAt": available_at,
        }
        if normalized_execution_options:
            event_payload["executionOptions"] = normalized_execution_options
        append_run_event_v2(
            connection,
            run_id=normalized_run_id,
            event_type="run_retry_requested",
            from_status=run["status"],
            to_status="queued",
            stage="retry",
            state_version=next_state_version,
            message="Run retry requested.",
            request_id=str(run["request_id"]),
            command_id=command["commandId"],
            actor=normalized_actor,
            payload=event_payload,
            occurred_at=requested_at,
            command_derived=True,
        )
        connection.commit()
        result = {
            "runId": normalized_run_id,
            "status": "queued",
            "stage": "retry",
            "commandId": command["commandId"],
            "jobId": job["job_id"],
            "attemptCount": attempt_count,
            "maxAttempts": max_attempts,
            "remainingAttempts": remaining_attempts,
            "availableAt": available_at,
            "retryRequestedAt": requested_at,
        }
        if normalized_execution_options:
            result["executionOptions"] = normalized_execution_options
        return result


def request_rule_retry(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
    command_id: str | None = None,
    execution_plan: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    current_plan = _current_rule_retry_execution_plan(cfg, normalized_run_id)
    plan = execution_plan or current_plan
    if not isinstance(plan, dict):
        raise ValueError("RULE_RETRY_EXECUTION_PLAN_MISSING")
    if str(plan.get("runId") or "").strip() != normalized_run_id:
        raise ValueError("RULE_RETRY_RUN_ID_MISMATCH")
    if str(plan.get("planHash") or "").strip() != str(current_plan.get("planHash") or "").strip():
        raise ValueError("RULE_RETRY_EXECUTION_PLAN_HASH_MISMATCH")
    execution_options = rule_retry_execution_options(plan)
    result = request_run_retry(
        cfg,
        normalized_run_id,
        actor=actor,
        reason=reason or "operator_rule_retry",
        command_id=command_id,
        execution_options=execution_options,
        scope="rule",
        now=now,
    )
    return {
        **result,
        "scope": "rule",
        "selectedRules": list(plan.get("selectedRules") or []),
        "rerunScope": dict(plan.get("rerunScope") or {}),
    }


def _current_rule_retry_execution_plan(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    from .run_execution_context_storage import fetch_run_execution_context

    context = fetch_run_execution_context(cfg, run_id)
    plan = context.get("ruleRetryExecutionPlan")
    if not isinstance(plan, dict):
        raise ValueError("RULE_RETRY_EXECUTION_PLAN_MISSING")
    return plan


def _retry_scope(scope: str) -> str:
    normalized = str(scope or "").strip()
    if normalized not in {"run", "rule"}:
        raise ValueError(f"RUN_RETRY_SCOPE_UNSUPPORTED: {normalized}")
    return normalized
