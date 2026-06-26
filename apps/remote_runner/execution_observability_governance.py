from __future__ import annotations

from collections import Counter
from typing import Any

from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event


def record_run_events_read_audit(cfg: RemoteRunnerConfig, run_id: str, events: list[dict[str, Any]]) -> None:
    event_types = Counter(str(item.get("eventType") or "unknown") for item in events if isinstance(item, dict))
    record_governance_audit_event(
        cfg,
        action="run.events.read",
        actor=_actor(cfg),
        subject_kind="run_events",
        subject_id=run_id,
        details={
            "returnedCount": len(events),
            "eventTypes": dict(sorted(event_types.items())),
        },
    )


def record_run_execution_context_read_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    context: dict[str, Any],
) -> None:
    attempts = _list_value(context.get("attempts"))
    rule_retry_plan = _dict_value(context.get("ruleRetryPlan"))
    rule_retry_execution_plan = _dict_value(context.get("ruleRetryExecutionPlan"))
    rule_retry_readiness = _dict_value(context.get("ruleRetryActivationReadiness")) or _dict_value(
        rule_retry_execution_plan.get("activationReadiness")
    )
    resume_readiness = _dict_value(context.get("resumeActivationReadiness")) or _dict_value(
        _dict_value(context.get("resumePlan")).get("activationReadiness")
    )
    workdir_reuse_policy = _dict_value(context.get("workdirReusePolicy")) or _dict_value(
        _dict_value(context.get("resumePlan")).get("workdirEvidence")
    )
    rule_cache_restore_plan = _dict_value(context.get("ruleCacheRestorePlan")) or _dict_value(
        rule_retry_execution_plan.get("cacheRestorePlan")
    )
    rule_cache_restore_redaction = _dict_value(rule_cache_restore_plan.get("redactionPolicy"))
    staged_file_policy = _dict_value(rule_cache_restore_plan.get("stagedFilePolicy"))
    restore_pin_policy = _dict_value(rule_cache_restore_plan.get("restorePinPolicy"))
    final_output_promotion_state = _dict_value(rule_cache_restore_plan.get("finalOutputPromotionState"))
    record_governance_audit_event(
        cfg,
        action="run.execution_context.read",
        actor=_actor(cfg),
        subject_kind="run_execution_context",
        subject_id=run_id,
        details={
            "hasJob": isinstance(context.get("job"), dict),
            "attemptCount": len(attempts),
            "activeLeasePresent": isinstance(context.get("activeLease"), dict),
            "retryEligible": bool(_dict_value(context.get("retryEligibility")).get("eligible")),
            "retryEligibleNow": bool(_dict_value(context.get("retryEligibility")).get("eligibleNow")),
            "resumeSupported": bool(context.get("resumeSupported")),
            "ruleRetryFailedRuleCount": _safe_int(rule_retry_plan.get("failedRuleCount")),
            "ruleRetrySelectedAttemptCount": _safe_int(rule_retry_plan.get("selectedAttemptCount")),
            "ruleRetryExecutionEnabled": bool(rule_retry_execution_plan.get("executionEnabled")),
            "ruleRetryActivationReady": bool(rule_retry_readiness.get("executionReady")),
            "ruleRetryActivationBlockedCount": _safe_int(rule_retry_readiness.get("blockedCheckCount")),
            "ruleRetryActivationMutationEnabled": bool(rule_retry_readiness.get("executionEnabled")),
            "resumeActivationReady": bool(resume_readiness.get("executionReady")),
            "resumeActivationBlockedCount": _safe_int(resume_readiness.get("blockedCheckCount")),
            "resumeActivationMutationEnabled": bool(resume_readiness.get("executionEnabled")),
            "workdirReusePolicyPresent": bool(workdir_reuse_policy),
            "workdirReusable": bool(workdir_reuse_policy.get("workDirReusable")),
            "workdirDirectoryPresent": bool(workdir_reuse_policy.get("directoryPresent")),
            "workdirRunConfigPresent": bool(workdir_reuse_policy.get("runConfigPresent")),
            "workdirPathsExposed": bool(workdir_reuse_policy.get("pathExposed")),
            "ruleCacheRestorePlanPresent": bool(rule_cache_restore_plan),
            "ruleCacheRestorePlanHashPresent": bool(str(rule_cache_restore_plan.get("planHash") or "").strip()),
            "ruleCacheRestoreOutputCount": _safe_int(rule_cache_restore_plan.get("outputCount")),
            "ruleCacheRestoreHitCount": _safe_int(rule_cache_restore_plan.get("cacheHitCount")),
            "ruleCacheRestoreMissCount": _safe_int(rule_cache_restore_plan.get("cacheMissCount")),
            "ruleCacheRestoreRawIdentifiersExposed": bool(rule_cache_restore_redaction.get("cacheKeysExposed")),
            "ruleCacheRestoreFingerprintsExposed": bool(
                rule_cache_restore_redaction.get("cacheKeyFingerprintsExposed")
            ),
            "ruleCacheRestoreStorageUrisExposed": bool(rule_cache_restore_redaction.get("storageUrisExposed")),
            "ruleCacheRestorePathsExposed": bool(rule_cache_restore_redaction.get("pathsExposed")),
            "stagedFilePolicyPreviewAvailable": bool(staged_file_policy.get("previewAvailable")),
            "stagedFilePolicyTargetCount": _safe_int(staged_file_policy.get("targetCount")),
            "stagedFilePolicyManagedTargetCount": _safe_int(staged_file_policy.get("managedTargetCount")),
            "stagedFilePolicyCacheHitTargetCount": _safe_int(staged_file_policy.get("cacheHitTargetCount")),
            "stagedFilePolicyCacheMissTargetCount": _safe_int(staged_file_policy.get("cacheMissTargetCount")),
            "stagedFilePolicyUnmappedTargetCount": _safe_int(staged_file_policy.get("unmappedTargetCount")),
            "stagedFilePolicyPathsExposed": bool(staged_file_policy.get("pathExposed")),
            "stagedFilePolicyStorageUrisExposed": bool(staged_file_policy.get("storageUriExposed")),
            "restorePinPolicyPreviewAvailable": bool(restore_pin_policy.get("previewAvailable")),
            "restorePinPolicyCandidatePinCount": _safe_int(restore_pin_policy.get("candidatePinCount")),
            "restorePinPolicyRequiredPinCount": _safe_int(restore_pin_policy.get("requiredPinCount")),
            "restorePinPolicyEligiblePinCount": _safe_int(restore_pin_policy.get("eligiblePinCount")),
            "restorePinPolicyBlockedPinCount": _safe_int(restore_pin_policy.get("blockedPinCount")),
            "restorePinPolicyCreatedPinCount": _safe_int(restore_pin_policy.get("createdPinCount")),
            "restorePinPolicyOwnerIdsExposed": bool(restore_pin_policy.get("ownerIdExposed")),
            "restorePinPolicyRawIdentifiersExposed": bool(restore_pin_policy.get("cacheKeyExposed")),
            "restorePinPolicyStorageUrisExposed": bool(restore_pin_policy.get("storageUriExposed")),
            "finalOutputPromotionTargetCount": _safe_int(final_output_promotion_state.get("targetCount")),
            "finalOutputPromotionCandidateOutputCount": _safe_int(
                final_output_promotion_state.get("candidateOutputCount")
            ),
            "finalOutputPromotionPromotedCount": _safe_int(
                final_output_promotion_state.get("promotedFinalOutputCount")
            ),
            "finalOutputPromotionPendingCount": _safe_int(
                final_output_promotion_state.get("pendingFinalOutputCount")
            ),
            "finalOutputPromotionPathsExposed": bool(final_output_promotion_state.get("pathExposed")),
            "finalOutputPromotionStorageUrisExposed": bool(final_output_promotion_state.get("storageUriExposed")),
        },
    )


def record_run_attempts_read_audit(cfg: RemoteRunnerConfig, run_id: str, attempts_model: dict[str, Any]) -> None:
    summary = _dict_value(attempts_model.get("summary"))
    record_governance_audit_event(
        cfg,
        action="run.attempts.read",
        actor=_actor(cfg),
        subject_kind="run_attempts",
        subject_id=run_id,
        details={
            "attemptCount": _safe_int(summary.get("attemptCount")),
            "slotCount": _safe_int(summary.get("slotCount")),
            "activeLeasePresent": bool(summary.get("activeLeasePresent")),
            "attemptStates": _string_int_map(summary.get("attemptsByState")),
            "slotStates": _string_int_map(summary.get("slotsByState")),
        },
    )


def record_run_logs_read_audit(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    stream: str,
    cursor: str | None,
    log_lines: dict[str, Any],
) -> None:
    record_governance_audit_event(
        cfg,
        action="run.logs.read",
        actor=_actor(cfg),
        subject_kind="run_logs",
        subject_id=run_id,
        details={
            "stream": str(stream or ""),
            "cursorProvided": bool(str(cursor or "").strip()),
            "returnedLineCount": len(_list_value(log_lines.get("lines"))),
            "nextCursorProvided": bool(str(log_lines.get("nextCursor") or "").strip()),
        },
    )


def record_run_rules_read_audit(cfg: RemoteRunnerConfig, run_id: str, rules: dict[str, Any]) -> None:
    items = _list_value(rules.get("items"))
    statuses = Counter(str(item.get("status") or "unknown") for item in items if isinstance(item, dict))
    event_count = sum(len(_list_value(item.get("events"))) for item in items if isinstance(item, dict))
    log_contexts = [_dict_value(item.get("logContext")) for item in items if isinstance(item, dict)]
    log_reasons = Counter(str(context.get("reasonCode") or "unknown") for context in log_contexts)
    log_statuses = Counter(str(context.get("status") or "unknown") for context in log_contexts)
    rules_with_source_locations = sum(
        isinstance(item, dict) and isinstance(item.get("sourceLocation"), dict)
        for item in items
    )
    record_governance_audit_event(
        cfg,
        action="run.rules.read",
        actor=_actor(cfg),
        subject_kind="run_rules",
        subject_id=run_id,
        details={
            "ruleCount": len(items),
            "ruleEventCount": event_count,
            "ruleStatuses": dict(sorted(statuses.items())),
            "rulesWithLogReferences": sum(_safe_int(item.get("logReferenceCount")) > 0 for item in items if isinstance(item, dict)),
            "rulesWithSourceLocations": rules_with_source_locations,
            "sourceLocationsSanitized": bool(_dict_value(rules.get("redactionPolicy")).get("sourceLocationsSanitized")),
            "ruleLogStatuses": dict(sorted(log_statuses.items())),
            "ruleLogReasonCodes": dict(sorted(log_reasons.items())),
        },
    )


def record_run_failure_locator_read_audit(cfg: RemoteRunnerConfig, run_id: str, locator: dict[str, Any]) -> None:
    log_context = _dict_value(locator.get("logContext"))
    rule_log_context = _dict_value(locator.get("ruleLogContext"))
    artifact_context = _dict_value(locator.get("artifactContext"))
    failed_rule = _dict_value(locator.get("failedRule"))
    record_governance_audit_event(
        cfg,
        action="run.failure_locator.read",
        actor=_actor(cfg),
        subject_kind="run_failure_locator",
        subject_id=run_id,
        details={
            "available": bool(locator.get("available")),
            "reasonCode": str(locator.get("reasonCode") or ""),
            "failedRulePresent": isinstance(locator.get("failedRule"), dict),
            "sourceLocationPresent": isinstance(failed_rule.get("sourceLocation"), dict),
            "sourceLocationsSanitized": bool(_dict_value(locator.get("redactionPolicy")).get("sourceLocationsSanitized")),
            "stderrLineCount": _safe_int(log_context.get("stderrLineCount")),
            "stderrTailLineCount": len(_list_value(log_context.get("stderrTail"))),
            "ruleLogStatus": str(rule_log_context.get("status") or ""),
            "ruleLogReasonCode": str(rule_log_context.get("reasonCode") or ""),
            "relatedArtifactCount": _safe_int(artifact_context.get("relatedArtifactCount")),
        },
    )


def _actor(cfg: RemoteRunnerConfig) -> str:
    return str(cfg.api_token_actor or "").strip() or "remote-runner-api"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(item) for key, item in sorted(value.items())}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
