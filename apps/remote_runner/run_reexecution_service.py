from __future__ import annotations

from typing import Any

from .api_models import RunResumeRequest, RunRuleRetryRequest
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerOperationBlockedError
from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, remote_runner_principal, run_sync
from .run_execution_context_storage import fetch_run_execution_context


async def _authorized_config_from_request(
    authorization: str | None,
    *,
    action: str,
) -> RemoteRunnerConfig:
    return await run_sync(authorized_config, authorization, action=action)


async def retry_run_rules_from_request(
    run_id: str,
    request: RunRuleRetryRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="run.rule_retry")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleRetryExecutionPlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash)
    if mismatch:
        await _record_rule_retry_audit(cfg, run_id, plan, decision="deny", reason_code=mismatch)
        raise _blocked("ruleRetryExecutionPlan", plan, mismatch)
    reason_code = str(plan.get("executionReasonCode") or "RULE_RETRY_EXECUTION_DISABLED")
    await _record_rule_retry_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
    raise _blocked("ruleRetryExecutionPlan", plan, reason_code)


async def resume_run_from_request(
    run_id: str,
    request: RunResumeRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="run.resume")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "resumePlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash)
    if mismatch:
        await _record_resume_audit(cfg, run_id, plan, decision="deny", reason_code=mismatch)
        raise _blocked("resumePlan", plan, mismatch)
    reason_code = str(plan.get("executionReasonCode") or "RUN_RESUME_EXECUTION_DISABLED")
    await _record_resume_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
    raise _blocked("resumePlan", plan, reason_code)


def _plan_object(context: dict[str, Any], key: str) -> dict[str, Any]:
    plan = context.get(key) if isinstance(context, dict) else None
    if not isinstance(plan, dict):
        raise RemoteRunnerOperationBlockedError(
            f"{key.upper()}_MISSING",
            {"code": f"{key.upper()}_MISSING", "message": f"{key} is unavailable."},
        )
    return plan


def _plan_hash_mismatch(plan: dict[str, Any], expected: str) -> str:
    current = str(plan.get("planHash") or "").strip()
    provided = str(expected or "").strip()
    if not current or current != provided:
        return "RUN_REEXECUTION_PLAN_HASH_MISMATCH"
    return ""


def _blocked(plan_key: str, plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(
        code,
        {
            "code": code,
            "message": str(plan.get("message") or f"{plan_key} is blocked."),
            plan_key: plan,
        },
    )


async def _record_rule_retry_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    decision: str,
    reason_code: str,
) -> None:
    rerun_scope = plan.get("rerunScope") if isinstance(plan.get("rerunScope"), dict) else {}
    await _record_reexecution_audit(
        cfg,
        action="run.rule_retry",
        subject_kind="run_rule_retry",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details={
            "planHash": str(plan.get("planHash") or ""),
            "executionEnabled": bool(plan.get("executionEnabled")),
            "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
            "selectedRuleCount": _collection_size(plan.get("selectedRules")),
            "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
            "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
        },
    )


async def _record_resume_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    decision: str,
    reason_code: str,
) -> None:
    latest_attempt = plan.get("latestAttempt") if isinstance(plan.get("latestAttempt"), dict) else {}
    output_audit = (
        plan.get("incompleteOutputAudit") if isinstance(plan.get("incompleteOutputAudit"), dict) else {}
    )
    await _record_reexecution_audit(
        cfg,
        action="run.resume",
        subject_kind="run_resume",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details={
            "planHash": str(plan.get("planHash") or ""),
            "executionEnabled": bool(plan.get("executionEnabled")),
            "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
            "latestAttemptState": str(latest_attempt.get("state") or ""),
            "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
            "missingOutputCount": _safe_int(output_audit.get("missingOutputCount")),
            "unsafeOutputCount": _safe_int(output_audit.get("unsafeOutputCount")),
            "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
        },
    )


async def _record_reexecution_audit(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    subject_kind: str,
    run_id: str,
    decision: str,
    reason_code: str,
    details: dict[str, Any],
) -> None:
    principal = remote_runner_principal(cfg)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action=action,
        actor=principal.actor,
        subject_kind=subject_kind,
        subject_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details=details,
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _collection_size(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
