from __future__ import annotations

from typing import Any

from .api_models import (
    RunResumeRequest,
    RunRuleCacheRestorePinApplyRequest,
    RunRuleCacheRestorePinPrepareRequest,
    RunRuleCacheRestoreStagedFileApplyRequest,
    RunRuleCacheRestoreStagedFilePrepareRequest,
    RunRuleOutputInvalidationApplyRequest,
    RunRuleRetryRequest,
)
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerOperationBlockedError
from .execution_rule_retry_projection import rule_retry_blocked
from .execution_resume_projection import resume_blocked
from .execution_retry_storage import request_rule_retry, request_run_resume
from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, data_response, remote_runner_principal, run_sync
from .run_execution_context_storage import fetch_run_execution_context
from .rule_output_invalidation_storage import apply_rule_output_invalidation_plan
from .rule_restore_pin_storage import apply_rule_cache_restore_pins, prepare_rule_cache_restore_pins
from .rule_staged_restore_storage import (
    apply_rule_cache_restore_staged_files,
    prepare_rule_cache_restore_staged_files,
)
from .workflow_run_storage import StaleRunAttemptError


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
        raise rule_retry_blocked(plan, mismatch)
    if plan.get("executionEnabled") is not True:
        reason_code = str(plan.get("executionReasonCode") or "RULE_RETRY_EXECUTION_DISABLED")
        await _record_rule_retry_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
        raise rule_retry_blocked(plan, reason_code)
    try:
        result = await run_sync(
            request_rule_retry,
            cfg,
            run_id,
            actor=request.actor,
            reason=request.reason,
            execution_plan=plan,
        )
    except ValueError as exc:
        reason_code = _exception_reason_code(exc, fallback="RULE_RETRY_EXECUTION_REQUEST_BLOCKED")
        await _record_rule_retry_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
        raise rule_retry_blocked(plan, reason_code) from exc
    await _record_rule_retry_audit(
        cfg,
        run_id,
        plan,
        decision="allow",
        reason_code="RULE_RETRY_REQUESTED",
        result=result,
    )
    return data_response(_public_rule_retry_result(result, plan))


async def apply_rule_output_invalidation_from_request(
    run_id: str,
    request: RunRuleOutputInvalidationApplyRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="run.rule_output_invalidation.apply")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleOutputInvalidationPlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash, code="RULE_OUTPUT_INVALIDATION_PLAN_HASH_MISMATCH")
    if mismatch:
        await _record_output_invalidation_audit(
            cfg,
            run_id,
            plan,
            decision="deny",
            reason_code=mismatch,
            request_reason_provided=bool(str(request.reason or "").strip()),
        )
        raise _output_invalidation_blocked(plan, mismatch)
    try:
        result = await run_sync(
            apply_rule_output_invalidation_plan,
            cfg,
            plan,
            plan_hash=request.planHash,
            actor=request.actor,
        )
    except ValueError as exc:
        reason_code = str(exc) or "RULE_OUTPUT_INVALIDATION_APPLY_BLOCKED"
        await _record_output_invalidation_audit(
            cfg,
            run_id,
            plan,
            decision="deny",
            reason_code=reason_code,
            request_reason_provided=bool(str(request.reason or "").strip()),
        )
        raise _output_invalidation_blocked(plan, reason_code) from exc
    await _record_output_invalidation_audit(
        cfg,
        run_id,
        plan,
        decision="allow",
        reason_code="RULE_OUTPUT_INVALIDATION_APPLIED",
        request_reason_provided=bool(str(request.reason or "").strip()),
        result=result,
    )
    return data_response(result)


async def prepare_rule_cache_restore_pins_from_request(
    run_id: str,
    request: RunRuleCacheRestorePinPrepareRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.pins.prepare")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleCacheRestorePlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash, code="RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH")
    if mismatch:
        await _record_cache_restore_pin_audit(
            cfg,
            run_id,
            plan,
            action="run.rule_cache_restore.pins.prepare",
            decision="deny",
            reason_code=mismatch,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_pin_blocked(plan, mismatch)
    try:
        result = await run_sync(
            prepare_rule_cache_restore_pins,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = str(exc) or "RULE_CACHE_RESTORE_PIN_PREPARE_BLOCKED"
        await _record_cache_restore_pin_audit(
            cfg,
            run_id,
            plan,
            action="run.rule_cache_restore.pins.prepare",
            decision="deny",
            reason_code=reason_code,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_pin_blocked(plan, reason_code) from exc
    await _record_cache_restore_pin_audit(
        cfg,
        run_id,
        plan,
        action="run.rule_cache_restore.pins.prepare",
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_PINS_PREPARED",
        request_reason_provided=bool(str(request.reason or "").strip()),
        attempt_provided=bool(str(request.attemptId or "").strip()),
        lease_generation_provided=True,
        result=result,
    )
    return data_response(result)


async def apply_rule_cache_restore_pins_from_request(
    run_id: str,
    request: RunRuleCacheRestorePinApplyRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.pins.apply")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleCacheRestorePlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash, code="RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH")
    if mismatch:
        await _record_cache_restore_pin_audit(
            cfg,
            run_id,
            plan,
            action="run.rule_cache_restore.pins.apply",
            decision="deny",
            reason_code=mismatch,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_pin_blocked(plan, mismatch)
    try:
        result = await run_sync(
            apply_rule_cache_restore_pins,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
            actor=request.actor,
            reason=request.reason,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = str(exc) or "RULE_CACHE_RESTORE_PIN_APPLY_BLOCKED"
        await _record_cache_restore_pin_audit(
            cfg,
            run_id,
            plan,
            action="run.rule_cache_restore.pins.apply",
            decision="deny",
            reason_code=reason_code,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_pin_blocked(plan, reason_code) from exc
    await _record_cache_restore_pin_audit(
        cfg,
        run_id,
        plan,
        action="run.rule_cache_restore.pins.apply",
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_PINS_APPLIED",
        request_reason_provided=bool(str(request.reason or "").strip()),
        attempt_provided=bool(str(request.attemptId or "").strip()),
        lease_generation_provided=True,
        result=result,
    )
    return data_response(result)


async def prepare_rule_cache_restore_staged_files_from_request(
    run_id: str,
    request: RunRuleCacheRestoreStagedFilePrepareRequest,
    authorization: str | None,
) -> dict[str, Any]:
    action = "run.rule_cache_restore.staged_files.prepare"
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.staged_files.prepare")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleCacheRestorePlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash, code="RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH")
    if mismatch:
        await _record_cache_restore_staged_file_audit(
            cfg,
            run_id,
            plan,
            action=action,
            decision="deny",
            reason_code=mismatch,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_staged_file_blocked(plan, mismatch)
    try:
        result = await run_sync(
            prepare_rule_cache_restore_staged_files,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = str(exc) or "RULE_CACHE_RESTORE_STAGED_FILE_PREPARE_BLOCKED"
        await _record_cache_restore_staged_file_audit(
            cfg,
            run_id,
            plan,
            action=action,
            decision="deny",
            reason_code=reason_code,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_staged_file_blocked(plan, reason_code) from exc
    await _record_cache_restore_staged_file_audit(
        cfg,
        run_id,
        plan,
        action=action,
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_STAGED_FILES_PREPARED",
        request_reason_provided=bool(str(request.reason or "").strip()),
        attempt_provided=bool(str(request.attemptId or "").strip()),
        lease_generation_provided=True,
        result=result,
    )
    return data_response(result)


async def apply_rule_cache_restore_staged_files_from_request(
    run_id: str,
    request: RunRuleCacheRestoreStagedFileApplyRequest,
    authorization: str | None,
) -> dict[str, Any]:
    action = "run.rule_cache_restore.staged_files.apply"
    cfg = await _authorized_config_from_request(authorization, action="run.rule_cache_restore.staged_files.apply")
    context = await run_sync(fetch_run_execution_context, cfg, run_id)
    plan = _plan_object(context, "ruleCacheRestorePlan")
    mismatch = _plan_hash_mismatch(plan, request.planHash, code="RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH")
    if mismatch:
        await _record_cache_restore_staged_file_audit(
            cfg,
            run_id,
            plan,
            action=action,
            decision="deny",
            reason_code=mismatch,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_staged_file_blocked(plan, mismatch)
    try:
        result = await run_sync(
            apply_rule_cache_restore_staged_files,
            cfg,
            plan,
            plan_hash=request.planHash,
            attempt_id=request.attemptId,
            lease_generation=request.leaseGeneration,
            actor=request.actor,
            reason=request.reason,
        )
    except (ValueError, StaleRunAttemptError) as exc:
        reason_code = str(exc) or "RULE_CACHE_RESTORE_STAGED_FILE_APPLY_BLOCKED"
        await _record_cache_restore_staged_file_audit(
            cfg,
            run_id,
            plan,
            action=action,
            decision="deny",
            reason_code=reason_code,
            request_reason_provided=bool(str(request.reason or "").strip()),
            attempt_provided=bool(str(request.attemptId or "").strip()),
            lease_generation_provided=True,
        )
        raise _cache_restore_staged_file_blocked(plan, reason_code) from exc
    await _record_cache_restore_staged_file_audit(
        cfg,
        run_id,
        plan,
        action=action,
        decision="allow",
        reason_code="RULE_CACHE_RESTORE_STAGED_FILES_APPLIED",
        request_reason_provided=bool(str(request.reason or "").strip()),
        attempt_provided=bool(str(request.attemptId or "").strip()),
        lease_generation_provided=True,
        result=result,
    )
    return data_response(result)


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
        raise resume_blocked(plan, mismatch)
    reason_code = _resume_mutation_blocker(plan)
    if reason_code:
        await _record_resume_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
        raise resume_blocked(plan, reason_code)
    try:
        result = await run_sync(
            request_run_resume,
            cfg,
            run_id,
            actor=request.actor,
            reason=request.reason,
            resume_plan=plan,
        )
    except ValueError as exc:
        reason_code = _exception_reason_code(exc, fallback="RUN_RESUME_REQUEST_BLOCKED")
        await _record_resume_audit(cfg, run_id, plan, decision="deny", reason_code=reason_code)
        raise resume_blocked(plan, reason_code) from exc
    await _record_resume_audit(
        cfg,
        run_id,
        plan,
        decision="allow",
        reason_code="RUN_RESUME_REQUESTED",
        result=result,
    )
    return data_response(_public_resume_result(result, plan))


def _resume_mutation_blocker(plan: dict[str, Any]) -> str:
    if plan.get("executionEnabled") is not True:
        return str(plan.get("executionReasonCode") or "RUN_RESUME_EXECUTION_DISABLED")
    readiness = plan.get("activationReadiness") if isinstance(plan.get("activationReadiness"), dict) else {}
    if readiness.get("executionReady") is not True:
        return str(readiness.get("reasonCode") or "RUN_RESUME_ACTIVATION_NOT_READY")
    orchestration = plan.get("executorOrchestration") if isinstance(plan.get("executorOrchestration"), dict) else {}
    if orchestration.get("executorReady") is not True:
        return str(orchestration.get("reasonCode") or "RUN_RESUME_EXECUTOR_NOT_READY")
    if orchestration.get("queueMutationAllowed") is not True:
        return "RUN_RESUME_QUEUE_MUTATION_BLOCKED"
    if orchestration.get("runStateMutationAllowed") is not True:
        return "RUN_RESUME_RUN_STATE_MUTATION_BLOCKED"
    return ""


def _plan_object(context: dict[str, Any], key: str) -> dict[str, Any]:
    plan = context.get(key) if isinstance(context, dict) else None
    if not isinstance(plan, dict):
        raise RemoteRunnerOperationBlockedError(
            f"{key.upper()}_MISSING",
            {"code": f"{key.upper()}_MISSING", "message": f"{key} is unavailable."},
        )
    return plan


def _plan_hash_mismatch(
    plan: dict[str, Any],
    expected: str,
    *,
    code: str = "RUN_REEXECUTION_PLAN_HASH_MISMATCH",
) -> str:
    current = str(plan.get("planHash") or "").strip()
    provided = str(expected or "").strip()
    if not current or current != provided:
        return code
    return ""


def _public_rule_retry_result(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    rerun_scope = plan.get("rerunScope") if isinstance(plan.get("rerunScope"), dict) else {}
    return {
        "schemaVersion": "run-rule-retry-result.v1",
        "runId": str(result.get("runId") or ""),
        "accepted": True,
        "blocked": False,
        "status": str(result.get("status") or ""),
        "stage": str(result.get("stage") or ""),
        "scope": "rule",
        "commandId": str(result.get("commandId") or ""),
        "jobId": str(result.get("jobId") or ""),
        "selectedRuleCount": _collection_size(plan.get("selectedRules")),
        "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
        "remainingAttempts": _safe_int(result.get("remainingAttempts")),
        "availableAt": str(result.get("availableAt") or ""),
        "retryRequestedAt": str(result.get("retryRequestedAt") or ""),
        "planHash": str(plan.get("planHash") or ""),
    }


def _public_resume_result(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    output_audit = plan.get("incompleteOutputAudit") if isinstance(plan.get("incompleteOutputAudit"), dict) else {}
    adoption = plan.get("artifactAdoptionBoundary") if isinstance(plan.get("artifactAdoptionBoundary"), dict) else {}
    return {
        "schemaVersion": "run-resume-result.v1",
        "runId": str(result.get("runId") or ""),
        "accepted": True,
        "blocked": False,
        "status": str(result.get("status") or ""),
        "stage": str(result.get("stage") or ""),
        "scope": "resume",
        "commandId": str(result.get("commandId") or ""),
        "jobId": str(result.get("jobId") or ""),
        "remainingAttempts": _safe_int(result.get("remainingAttempts")),
        "availableAt": str(result.get("availableAt") or ""),
        "resumeRequestedAt": str(result.get("retryRequestedAt") or ""),
        "planHash": str(plan.get("planHash") or ""),
        "resumeStrategy": str(plan.get("strategy") or ""),
        "retainedOutputCount": _safe_int(adoption.get("retainedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
    }


def _output_invalidation_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(
        code,
        {
            "code": code,
            "message": str(plan.get("message") or "ruleOutputInvalidationPlan is blocked."),
            "ruleOutputInvalidationPlan": _public_output_invalidation_plan(plan),
        },
    )


def _public_output_invalidation_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("outputEdgeSummary") if isinstance(plan.get("outputEdgeSummary"), dict) else {}
    state = plan.get("outputInvalidationState") if isinstance(plan.get("outputInvalidationState"), dict) else {}
    return {
        "schemaVersion": "rule-output-invalidation-public-plan.v1",
        "planHash": str(plan.get("planHash") or ""),
        "runId": str(plan.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(plan.get("workflowRevisionId") or "").strip()),
        "previewAvailable": bool(plan.get("previewAvailable")),
        "supported": bool(plan.get("supported")),
        "eligible": bool(plan.get("eligible")),
        "eligibleNow": bool(plan.get("eligibleNow")),
        "invalidationEnabled": bool(plan.get("invalidationEnabled")),
        "pathExposed": bool(plan.get("pathExposed")),
        "storageReferenceExposed": bool(plan.get("storageReferenceExposed")),
        "reasonCode": str(plan.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
        "outputEdgeSummary": {
            "outputEdgeCount": _safe_int(summary.get("outputEdgeCount")),
            "invalidatedOutputEdgeCount": _safe_int(summary.get("invalidatedOutputEdgeCount")),
            "selectedOutputEdgeCount": _safe_int(summary.get("selectedOutputEdgeCount")),
            "downstreamOutputEdgeCount": _safe_int(summary.get("downstreamOutputEdgeCount")),
            "preservedOutputEdgeCount": _safe_int(summary.get("preservedOutputEdgeCount")),
            "unmatchedOutputEdgeCount": _safe_int(summary.get("unmatchedOutputEdgeCount")),
            "invalidatedLineageEdgeCount": _safe_int(summary.get("invalidatedLineageEdgeCount")),
            "preservedLineageEdgeCount": _safe_int(summary.get("preservedLineageEdgeCount")),
            "alreadyInvalidatedOutputEdgeCount": _safe_int(summary.get("alreadyInvalidatedOutputEdgeCount")),
            "alreadyInvalidatedLineageEdgeCount": _safe_int(summary.get("alreadyInvalidatedLineageEdgeCount")),
            "payloadDeletionAllowed": bool(summary.get("payloadDeletionAllowed")),
            "lineageMutationAllowed": bool(summary.get("lineageMutationAllowed")),
        },
        "outputInvalidationState": {
            "state": str(state.get("state") or "unknown"),
            "appliedOutputEdgeCount": _safe_int(state.get("appliedOutputEdgeCount")),
            "appliedLineageEdgeCount": _safe_int(state.get("appliedLineageEdgeCount")),
            "evidenceEventCount": _safe_int(state.get("evidenceEventCount")),
            "latestAppliedAtPresent": bool(str(state.get("latestAppliedAt") or "").strip()),
        },
    }


def _cache_restore_pin_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(
        code,
        {
            "code": code,
            "message": str(plan.get("message") or "ruleCacheRestorePlan is blocked."),
            "ruleCacheRestorePlan": _public_cache_restore_pin_plan(plan),
        },
    )


def _public_cache_restore_pin_plan(plan: dict[str, Any]) -> dict[str, Any]:
    policy = plan.get("restorePinPolicy") if isinstance(plan.get("restorePinPolicy"), dict) else {}
    eligibility = plan.get("cacheEligibility") if isinstance(plan.get("cacheEligibility"), dict) else {}
    return {
        "schemaVersion": "rule-cache-restore-pin-public-plan.v1",
        "planHash": str(plan.get("planHash") or ""),
        "runId": str(plan.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(plan.get("workflowRevisionId") or "").strip()),
        "previewAvailable": bool(policy.get("previewAvailable")),
        "creationEnabled": bool(policy.get("creationEnabled")),
        "pinCreationAllowed": bool(policy.get("pinCreationAllowed")),
        "reasonCode": str(policy.get("reasonCode") or plan.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(policy.get("blockedReasonCodes") or plan.get("blockedReasonCodes")),
        "outputInvalidationApplied": bool(eligibility.get("outputInvalidationApplied")),
        "cacheHitCount": _safe_int(plan.get("cacheHitCount")),
        "cacheMissCount": _safe_int(plan.get("cacheMissCount")),
        "candidatePinCount": _safe_int(policy.get("candidatePinCount")),
        "requiredPinCount": _safe_int(policy.get("requiredPinCount")),
        "eligiblePinCount": _safe_int(policy.get("eligiblePinCount")),
        "blockedPinCount": _safe_int(policy.get("blockedPinCount")),
        "ttlSeconds": _safe_int(policy.get("ttlSeconds")),
        "attemptScoped": bool(policy.get("attemptScoped")),
        "ownerIdExposed": bool(policy.get("ownerIdExposed")),
        "cacheKeyExposed": bool(policy.get("cacheKeyExposed")),
        "storageUriExposed": bool(policy.get("storageUriExposed")),
        "pathExposed": bool(policy.get("pathExposed")),
    }


def _cache_restore_staged_file_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(
        code,
        {
            "code": code,
            "message": str(plan.get("message") or "ruleCacheRestorePlan staged-file restore is blocked."),
            "ruleCacheRestorePlan": _public_cache_restore_staged_file_plan(plan),
        },
    )


def _public_cache_restore_staged_file_plan(plan: dict[str, Any]) -> dict[str, Any]:
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    eligibility = plan.get("cacheEligibility") if isinstance(plan.get("cacheEligibility"), dict) else {}
    return {
        "schemaVersion": "rule-cache-restore-staged-file-public-plan.v1",
        "planHash": str(plan.get("planHash") or ""),
        "runId": str(plan.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(plan.get("workflowRevisionId") or "").strip()),
        "previewAvailable": bool(policy.get("previewAvailable")),
        "enabled": bool(policy.get("enabled")),
        "materializationEnabled": bool(policy.get("materializationEnabled")),
        "attemptStagingAllowed": bool(policy.get("attemptStagingAllowed")),
        "overwriteAllowed": bool(policy.get("overwriteAllowed")),
        "deleteUnknownOutputs": bool(policy.get("deleteUnknownOutputs")),
        "unknownOutputHandling": str(policy.get("unknownOutputHandling") or ""),
        "reasonCode": str(policy.get("reasonCode") or plan.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(policy.get("blockedReasonCodes") or plan.get("blockedReasonCodes")),
        "outputInvalidationApplied": bool(eligibility.get("outputInvalidationApplied")),
        "targetCount": _safe_int(policy.get("targetCount")),
        "managedTargetCount": _safe_int(policy.get("managedTargetCount")),
        "cacheHitTargetCount": _safe_int(policy.get("cacheHitTargetCount")),
        "cacheMissTargetCount": _safe_int(policy.get("cacheMissTargetCount")),
        "unmappedTargetCount": _safe_int(policy.get("unmappedTargetCount")),
        "unknownOutputCount": _safe_int(policy.get("unknownOutputCount")),
        "restorePinnedCount": _safe_int(policy.get("restorePinnedCount")),
        "stagingDirectoryManaged": bool(policy.get("stagingDirectoryManaged")),
        "stagingDirectoryExposed": bool(policy.get("stagingDirectoryExposed")),
        "pathExposed": bool(policy.get("pathExposed")),
        "storageUriExposed": bool(policy.get("storageUriExposed")),
        "cacheKeyExposed": bool(policy.get("cacheKeyExposed")),
    }


async def _record_rule_retry_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    decision: str,
    reason_code: str,
    result: dict[str, Any] | None = None,
) -> None:
    rerun_scope = plan.get("rerunScope") if isinstance(plan.get("rerunScope"), dict) else {}
    output_audit = plan.get("incompleteOutputAudit") if isinstance(plan.get("incompleteOutputAudit"), dict) else {}
    details = {
        "planHash": str(plan.get("planHash") or ""),
        "executionEnabled": bool(plan.get("executionEnabled")),
        "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
        "selectedRuleCount": _collection_size(plan.get("selectedRules")),
        "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
        "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
        "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
        "unverifiedOutputCount": _safe_int(output_audit.get("unverifiedOutputCount")),
        "pathExposed": bool(output_audit.get("pathExposed")),
        "storageUriExposed": bool(output_audit.get("storageUriExposed")),
        "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
    }
    if result is not None:
        details.update(
            {
                "status": str(result.get("status") or ""),
                "stage": str(result.get("stage") or ""),
                "scope": str(result.get("scope") or ""),
                "remainingAttempts": _safe_int(result.get("remainingAttempts")),
                "scopedRetryOptionsStored": isinstance(result.get("executionOptions"), dict),
            }
        )
    await _record_reexecution_audit(
        cfg,
        action="run.rule_retry",
        subject_kind="run_rule_retry",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details=details,
    )


async def _record_resume_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    decision: str,
    reason_code: str,
    result: dict[str, Any] | None = None,
) -> None:
    latest_attempt = plan.get("latestAttempt") if isinstance(plan.get("latestAttempt"), dict) else {}
    output_audit = (
        plan.get("incompleteOutputAudit") if isinstance(plan.get("incompleteOutputAudit"), dict) else {}
    )
    details = {
        "planHash": str(plan.get("planHash") or ""),
        "executionEnabled": bool(plan.get("executionEnabled")),
        "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
        "latestAttemptState": str(latest_attempt.get("state") or ""),
        "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
        "missingOutputCount": _safe_int(output_audit.get("missingOutputCount")),
        "unsafeOutputCount": _safe_int(output_audit.get("unsafeOutputCount")),
        "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
    }
    if result is not None:
        details.update(
            {
                "status": str(result.get("status") or ""),
                "stage": str(result.get("stage") or ""),
                "scope": str(result.get("scope") or ""),
                "remainingAttempts": _safe_int(result.get("remainingAttempts")),
                "resumeOptionsStored": isinstance(result.get("executionOptions"), dict),
            }
        )
    await _record_reexecution_audit(
        cfg,
        action="run.resume",
        subject_kind="run_resume",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details=details,
    )


async def _record_cache_restore_staged_file_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    action: str,
    decision: str,
    reason_code: str,
    request_reason_provided: bool,
    attempt_provided: bool,
    lease_generation_provided: bool,
    result: dict[str, Any] | None = None,
) -> None:
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    details = {
        "planHash": str(plan.get("planHash") or ""),
        "previewAvailable": bool(policy.get("previewAvailable")),
        "enabled": bool(policy.get("enabled")),
        "materializationEnabled": bool(policy.get("materializationEnabled")),
        "attemptStagingAllowed": bool(policy.get("attemptStagingAllowed")),
        "overwriteAllowed": bool(policy.get("overwriteAllowed")),
        "deleteUnknownOutputs": bool(policy.get("deleteUnknownOutputs")),
        "requestReasonProvided": request_reason_provided,
        "attemptProvided": attempt_provided,
        "leaseGenerationProvided": lease_generation_provided,
        "targetCount": _safe_int(policy.get("targetCount")),
        "managedTargetCount": _safe_int(policy.get("managedTargetCount")),
        "cacheHitTargetCount": _safe_int(policy.get("cacheHitTargetCount")),
        "cacheMissTargetCount": _safe_int(policy.get("cacheMissTargetCount")),
        "unmappedTargetCount": _safe_int(policy.get("unmappedTargetCount")),
        "unknownOutputCount": _safe_int(policy.get("unknownOutputCount")),
        "restorePinnedCount": _safe_int(policy.get("restorePinnedCount")),
        "blockedReasonCodes": _string_list(policy.get("blockedReasonCodes") or plan.get("blockedReasonCodes")),
    }
    if result is not None:
        for key in (
            "stagedFileCount",
            "preparedStagedFileCount",
            "createdStagedFileCount",
            "reusedStagedFileCount",
            "restorePinCount",
        ):
            if key in result:
                details[key] = _safe_int(result.get(key))
    await _record_reexecution_audit(
        cfg,
        action=action,
        subject_kind="run_rule_cache_restore_staged_files",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details=details,
    )


async def _record_cache_restore_pin_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    action: str,
    decision: str,
    reason_code: str,
    request_reason_provided: bool,
    attempt_provided: bool,
    lease_generation_provided: bool,
    result: dict[str, Any] | None = None,
) -> None:
    policy = plan.get("restorePinPolicy") if isinstance(plan.get("restorePinPolicy"), dict) else {}
    details = {
        "planHash": str(plan.get("planHash") or ""),
        "previewAvailable": bool(policy.get("previewAvailable")),
        "creationEnabled": bool(policy.get("creationEnabled")),
        "pinCreationAllowed": bool(policy.get("pinCreationAllowed")),
        "requestReasonProvided": request_reason_provided,
        "attemptProvided": attempt_provided,
        "leaseGenerationProvided": lease_generation_provided,
        "candidatePinCount": _safe_int(policy.get("candidatePinCount")),
        "requiredPinCount": _safe_int(policy.get("requiredPinCount")),
        "eligiblePinCount": _safe_int((result or {}).get("eligiblePinCount") or policy.get("eligiblePinCount")),
        "blockedPinCount": _safe_int(policy.get("blockedPinCount")),
        "blockedReasonCodes": _string_list(policy.get("blockedReasonCodes") or plan.get("blockedReasonCodes")),
    }
    if result is not None:
        for key in (
            "preparedPinCount",
            "appliedPinCount",
            "createdPinCount",
            "reusedPinCount",
            "cacheEntryCount",
        ):
            if key in result:
                details[key] = _safe_int(result.get(key))
    await _record_reexecution_audit(
        cfg,
        action=action,
        subject_kind="run_rule_cache_restore_pins",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details=details,
    )


async def _record_output_invalidation_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    plan: dict[str, Any],
    *,
    decision: str,
    reason_code: str,
    request_reason_provided: bool,
    result: dict[str, Any] | None = None,
) -> None:
    summary = plan.get("outputEdgeSummary") if isinstance(plan.get("outputEdgeSummary"), dict) else {}
    await _record_reexecution_audit(
        cfg,
        action="run.rule_output_invalidation.apply",
        subject_kind="run_rule_output_invalidation",
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        details={
            "planHash": str(plan.get("planHash") or ""),
            "previewAvailable": bool(plan.get("previewAvailable")),
            "invalidationEnabled": bool(plan.get("invalidationEnabled")),
            "requestReasonProvided": request_reason_provided,
            "invalidatedOutputEdgeCount": _safe_int(
                (result or {}).get("invalidatedOutputEdgeCount")
                if result
                else summary.get("invalidatedOutputEdgeCount")
            ),
            "invalidatedLineageEdgeCount": _safe_int(
                (result or {}).get("invalidatedLineageEdgeCount")
                if result
                else summary.get("invalidatedLineageEdgeCount")
            ),
            "payloadDeleted": bool((result or {}).get("payloadDeleted")),
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


def _exception_reason_code(exc: BaseException, *, fallback: str) -> str:
    reason = str(exc or "").strip()
    if not reason:
        return fallback
    return reason.split(":", 1)[0].strip() or fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
