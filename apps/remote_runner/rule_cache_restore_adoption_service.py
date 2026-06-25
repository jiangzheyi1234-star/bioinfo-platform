from __future__ import annotations

from typing import Any

from .api_models import (
    RunRuleCacheRestoreAdoptionApplyRequest,
    RunRuleCacheRestoreAdoptionPrepareRequest,
)
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerOperationBlockedError
from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, data_response, remote_runner_principal, run_sync
from .run_execution_context_storage import fetch_run_execution_context
from .rule_cache_restore_adoption_storage import (
    apply_rule_cache_restore_adoption,
    prepare_rule_cache_restore_adoption,
)
from .workflow_run_storage import StaleRunAttemptError


async def prepare_rule_cache_restore_adoption_from_request(
    run_id: str,
    request: RunRuleCacheRestoreAdoptionPrepareRequest,
    authorization: str | None,
) -> dict[str, Any]:
    action = "run.rule_cache_restore.adoption.prepare"
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.adoption.prepare")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context)
    mismatch = _plan_hash_mismatch(plan, request.planHash)
    if mismatch:
        await _record_adoption_audit(
            cfg,
            action=action,
            run_id=run_id,
            plan=plan,
            request=request,
            decision="deny",
            reason_code=mismatch,
        )
        raise _adoption_blocked(plan, mismatch)
    try:
        result = await run_sync(
            prepare_rule_cache_restore_adoption,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = _reason_code(exc)
        await _record_adoption_audit(
            cfg,
            action=action,
            run_id=run_id,
            plan=plan,
            request=request,
            decision="deny",
            reason_code=reason_code,
        )
        raise _adoption_blocked(plan, reason_code) from exc
    await _record_adoption_audit(
        cfg,
        action=action,
        run_id=run_id,
        plan=plan,
        request=request,
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_ADOPTION_PREPARED",
        result=result,
    )
    return data_response(result)


async def apply_rule_cache_restore_adoption_from_request(
    run_id: str,
    request: RunRuleCacheRestoreAdoptionApplyRequest,
    authorization: str | None,
) -> dict[str, Any]:
    action = "run.rule_cache_restore.adoption.apply"
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.adoption.apply")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context)
    mismatch = _plan_hash_mismatch(plan, request.planHash)
    if mismatch:
        await _record_adoption_audit(
            cfg,
            action=action,
            run_id=run_id,
            plan=plan,
            request=request,
            decision="deny",
            reason_code=mismatch,
        )
        raise _adoption_blocked(plan, mismatch)
    try:
        result = await run_sync(
            apply_rule_cache_restore_adoption,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
            actor=request.actor,
            reason=request.reason,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = _reason_code(exc)
        await _record_adoption_audit(
            cfg,
            action=action,
            run_id=run_id,
            plan=plan,
            request=request,
            decision="deny",
            reason_code=reason_code,
        )
        raise _adoption_blocked(plan, reason_code) from exc
    await _record_adoption_audit(
        cfg,
        action=action,
        run_id=run_id,
        plan=plan,
        request=request,
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_ADOPTION_APPLIED",
        result=result,
    )
    return data_response(result)


async def _authorized_config_from_request(
    authorization: str | None,
    *,
    action: str,
) -> RemoteRunnerConfig:
    return await run_sync(authorized_config, authorization, action=action)


def _plan_object(context: dict[str, Any]) -> dict[str, Any]:
    plan = context.get("ruleCacheRestorePlan")
    if not isinstance(plan, dict):
        raise RemoteRunnerOperationBlockedError("RULE_CACHE_RESTORE_PLAN_MISSING")
    return plan


def _plan_hash_mismatch(plan: dict[str, Any], requested_hash: str) -> str:
    actual = str(plan.get("planHash") or "").strip()
    requested = str(requested_hash or "").strip()
    if not actual or requested != actual:
        return "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"
    return ""


def _adoption_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(
        code,
        {
            "code": code,
            "ruleCacheRestorePlan": _public_adoption_plan(plan),
        },
    )


def _public_adoption_plan(plan: dict[str, Any]) -> dict[str, Any]:
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    promotion = plan.get("finalOutputPromotionState")
    if not isinstance(promotion, dict):
        promotion = {}
    return {
        "schemaVersion": "rule-cache-restore-adoption-public-plan.v1",
        "runId": plan.get("runId"),
        "planHash": plan.get("planHash"),
        "reasonCode": plan.get("reasonCode"),
        "outputCount": _safe_int(plan.get("outputCount")),
        "cacheHitCount": _safe_int(plan.get("cacheHitCount")),
        "cacheMissCount": _safe_int(plan.get("cacheMissCount")),
        "materializationEnabled": bool(policy.get("materializationEnabled")),
        "attemptFinalOutputPromotionAllowed": bool(policy.get("attemptFinalOutputPromotionAllowed")),
        "finalOutputMutationAllowed": bool(policy.get("finalOutputMutationAllowed")),
        "finalOutputOverwriteAllowed": bool(policy.get("finalOutputOverwriteAllowed")),
        "promotionState": str(promotion.get("state") or ""),
        "targetCount": _safe_int(promotion.get("targetCount")),
        "candidateOutputCount": _safe_int(promotion.get("candidateOutputCount")),
        "promotedFinalOutputCount": _safe_int(promotion.get("promotedFinalOutputCount")),
        "adoptedCandidateOutputCount": _safe_int(promotion.get("adoptedCandidateOutputCount")),
        "pendingFinalOutputCount": _safe_int(promotion.get("pendingFinalOutputCount")),
        "pathExposed": False,
        "storageUriExposed": False,
        "cacheIdentifierExposed": False,
        "ownerIdExposed": False,
    }


async def _record_adoption_audit(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    run_id: str,
    plan: dict[str, Any],
    request: RunRuleCacheRestoreAdoptionPrepareRequest | RunRuleCacheRestoreAdoptionApplyRequest,
    decision: str,
    reason_code: str,
    result: dict[str, Any] | None = None,
) -> None:
    promotion = plan.get("finalOutputPromotionState")
    if not isinstance(promotion, dict):
        promotion = {}
    principal = remote_runner_principal(cfg)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action=action,
        actor=principal.actor,
        subject_kind="run_rule_cache_restore_adoption",
        subject_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details={
            "planHash": str(plan.get("planHash") or ""),
            "requestReasonProvided": bool(str(getattr(request, "reason", "") or "").strip()),
            "attemptProvided": bool(str(getattr(request, "attemptId", "") or "").strip()),
            "leaseGenerationProvided": bool(getattr(request, "leaseGeneration", None)),
            "promotionState": str(promotion.get("state") or ""),
            "targetCount": _safe_int(promotion.get("targetCount")),
            "candidateOutputCount": _safe_int(promotion.get("candidateOutputCount")),
            "promotedFinalOutputCount": _safe_int(promotion.get("promotedFinalOutputCount")),
            "adoptedCandidateOutputCount": _safe_int(promotion.get("adoptedCandidateOutputCount")),
            "pendingFinalOutputCount": _safe_int(promotion.get("pendingFinalOutputCount")),
            "resultTargetCount": _safe_int((result or {}).get("targetCount")),
            "resultAdoptedArtifactCount": _safe_int((result or {}).get("adoptedArtifactCount")),
            "resultVerifiedCandidateOutputCount": _safe_int((result or {}).get("verifiedCandidateOutputCount")),
            "resultReleasedPinCount": _safe_int((result or {}).get("releasedPinCount")),
            "runStateMutated": bool((result or {}).get("runStateMutated")),
            "retryEnqueued": bool((result or {}).get("retryEnqueued")),
            "pathExposed": False,
            "storageUriExposed": False,
            "cacheIdentifierExposed": False,
            "ownerIdExposed": False,
        },
    )


def _reason_code(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__.upper()
    return text.split(":", 1)[0]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
