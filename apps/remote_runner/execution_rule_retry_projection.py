from __future__ import annotations

from typing import Any

from .errors import RemoteRunnerOperationBlockedError


RUN_RULE_RETRY_PUBLIC_PLAN_SCHEMA_VERSION = "run-rule-retry-public-plan.v1"
_BOOL_POLICY_KEY_SUFFIXES = ("Allowed", "Enabled", "Available", "Ready", "Exposed", "Required", "Present")
_BOOL_POLICY_KEYS = {"enabled", "available", "previewAvailable", "executorReady"}


def rule_retry_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(code, rule_retry_blocked_payload(plan, code))


def rule_retry_blocked_payload(plan: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": str(plan.get("message") or "ruleRetryExecutionPlan is blocked."),
        "ruleRetryExecutionPlan": public_rule_retry_plan(plan, denial_code=code),
    }


def public_rule_retry_plan(plan: dict[str, Any], *, denial_code: str = "") -> dict[str, Any]:
    cache_restore = _dict_value(plan.get("cacheRestorePlan"))
    output_invalidation = _dict_value(plan.get("outputInvalidationPlan"))
    output_audit = _dict_value(plan.get("incompleteOutputAudit"))
    lifecycle = _dict_value(plan.get("partialRerunLifecycle"))
    output_closure = _dict_value(plan.get("partialRerunOutputClosure"))
    orchestration = _dict_value(plan.get("executorOrchestration"))
    snakemake = _dict_value(plan.get("snakemakeOptions"))
    readiness = _dict_value(plan.get("activationReadiness"))
    blocked_response = bool(str(denial_code or "").strip())
    return {
        "schemaVersion": RUN_RULE_RETRY_PUBLIC_PLAN_SCHEMA_VERSION,
        "planHash": str(plan.get("planHash") or ""),
        "runId": str(plan.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(plan.get("workflowRevisionId") or "").strip()),
        "supported": bool(plan.get("supported")),
        "eligible": bool(plan.get("eligible")),
        "eligibleNow": bool(plan.get("eligibleNow")),
        "executionEnabled": False if blocked_response else plan.get("executionEnabled") is True,
        "executionReasonCode": denial_code if blocked_response else str(plan.get("executionReasonCode") or ""),
        "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
        "reasonCode": str(plan.get("reasonCode") or ""),
        "blockedReasonCodes": _blocked_reasons(plan, denial_code),
        "requiresBeforeExecution": _requires_before_execution(plan, denial_code),
        "selectedRuleCount": _collection_size(plan.get("selectedRules")),
        "rerunRuleCount": _safe_int(_dict_value(plan.get("rerunScope")).get("ruleCount")),
        "cacheRestorePlan": _public_cache_restore_plan(cache_restore),
        "outputInvalidationPlan": _public_output_invalidation_plan(output_invalidation),
        "incompleteOutputAudit": _public_output_audit(output_audit),
        "partialRerunLifecycle": _public_partial_rerun_lifecycle(lifecycle),
        "partialRerunOutputClosure": _public_partial_output_closure(output_closure),
        "executorOrchestration": _public_executor_orchestration(orchestration, blocked_response=blocked_response),
        "snakemakeOptions": _public_snakemake_options(snakemake),
        "activationReadiness": _public_activation_readiness(readiness, blocked_response=blocked_response),
    }


def _public_cache_restore_plan(plan: dict[str, Any]) -> dict[str, Any]:
    redaction = _dict_value(plan.get("redactionPolicy"))
    restore_pin = _dict_value(plan.get("restorePinPolicy"))
    staged_file = _dict_value(plan.get("stagedFilePolicy"))
    promotion = _dict_value(plan.get("finalOutputPromotionState"))
    partial_executor = _dict_value(plan.get("partialRestoreExecutor"))
    return {
        "schemaVersion": str(plan.get("schemaVersion") or ""),
        "planHashPresent": bool(str(plan.get("planHash") or "").strip()),
        "available": bool(plan.get("available")),
        "previewAvailable": bool(plan.get("previewAvailable")),
        "reasonCode": str(plan.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
        "outputCount": _safe_int(plan.get("outputCount")),
        "cacheHitCount": _safe_int(plan.get("cacheHitCount")),
        "cacheMissCount": _safe_int(plan.get("cacheMissCount")),
        "ruleCount": _collection_size(plan.get("rules")),
        "redactionPolicy": _bool_mapping(
            redaction,
            allowed_keys=("cacheKeysExposed", "cacheKeyFingerprintsExposed", "storageUrisExposed", "pathsExposed"),
        ),
        "restorePinPolicy": _count_policy(
            restore_pin,
            keys=(
                "previewAvailable",
                "creationEnabled",
                "pinCreationAllowed",
                "candidatePinCount",
                "requiredPinCount",
                "createdPinCount",
                "eligiblePinCount",
                "blockedPinCount",
                "pathExposed",
                "storageUriExposed",
                "cacheKeyExposed",
                "ownerIdExposed",
            ),
        ),
        "stagedFilePolicy": _count_policy(
            staged_file,
            keys=(
                "previewAvailable",
                "enabled",
                "materializationEnabled",
                "attemptStagingAllowed",
                "targetCount",
                "managedTargetCount",
                "restorePinnedCount",
                "unknownOutputCount",
                "pathExposed",
                "storageUriExposed",
                "cacheKeyExposed",
            ),
        ),
        "finalOutputPromotionState": _count_policy(
            promotion,
            keys=(
                "targetCount",
                "promotedFinalOutputCount",
                "adoptedCandidateOutputCount",
                "pathExposed",
                "storageUriExposed",
            ),
        ),
        "partialRestoreExecutor": _count_policy(
            partial_executor,
            keys=("available", "enabled", "executorReady", "pathExposed", "storageUriExposed"),
        ),
    }


def _public_output_invalidation_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = _dict_value(plan.get("outputEdgeSummary"))
    state = _dict_value(plan.get("outputInvalidationState"))
    return {
        "schemaVersion": str(plan.get("schemaVersion") or ""),
        "planHashPresent": bool(str(plan.get("planHash") or "").strip()),
        "previewAvailable": bool(plan.get("previewAvailable")),
        "supported": bool(plan.get("supported")),
        "eligible": bool(plan.get("eligible")),
        "eligibleNow": bool(plan.get("eligibleNow")),
        "invalidationEnabled": bool(plan.get("invalidationEnabled")),
        "pathExposed": bool(plan.get("pathExposed")),
        "storageReferenceExposed": bool(plan.get("storageReferenceExposed")),
        "reasonCode": str(plan.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(plan.get("blockedReasonCodes")),
        "outputEdgeSummary": _int_mapping(summary),
        "outputInvalidationState": {
            "state": str(state.get("state") or "unknown"),
            "appliedOutputEdgeCount": _safe_int(state.get("appliedOutputEdgeCount")),
            "appliedLineageEdgeCount": _safe_int(state.get("appliedLineageEdgeCount")),
            "evidenceEventCount": _safe_int(state.get("evidenceEventCount")),
            "latestAppliedAtPresent": bool(str(state.get("latestAppliedAt") or "").strip()),
        },
    }


def _public_output_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(audit.get("schemaVersion") or ""),
        "available": bool(audit.get("available")),
        "pathExposed": bool(audit.get("pathExposed")),
        "storageUriExposed": bool(audit.get("storageUriExposed")),
        "expectedOutputCount": _safe_int(audit.get("expectedOutputCount")),
        "checkedOutputCount": _safe_int(audit.get("checkedOutputCount")),
        "verifiedOutputCount": _safe_int(audit.get("verifiedOutputCount")),
        "checksumVerifiedOutputCount": _safe_int(audit.get("checksumVerifiedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(audit.get("rerunRequiredOutputCount")),
        "adoptedOutputCount": _safe_int(audit.get("adoptedOutputCount")),
        "unsafeOutputCount": _safe_int(audit.get("unsafeOutputCount")),
        "uncheckedOutputCount": _safe_int(audit.get("uncheckedOutputCount")),
        "unverifiedOutputCount": _safe_int(audit.get("unverifiedOutputCount")),
        "outputCount": _collection_size(audit.get("outputs")),
        "reasonCode": str(audit.get("reasonCode") or ""),
    }


def _public_partial_rerun_lifecycle(lifecycle: dict[str, Any]) -> dict[str, Any]:
    source = _dict_value(lifecycle.get("sourceAttempt"))
    target = _dict_value(lifecycle.get("targetAttempt"))
    output_closure = _dict_value(lifecycle.get("outputClosure"))
    return {
        "schemaVersion": str(lifecycle.get("schemaVersion") or ""),
        "available": bool(lifecycle.get("available")),
        "mode": str(lifecycle.get("mode") or ""),
        "contractReady": bool(lifecycle.get("contractReady")),
        "mutationReady": bool(lifecycle.get("mutationReady")),
        "reasonCode": str(lifecycle.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(lifecycle.get("blockedReasonCodes")),
        "sourceAttempt": {
            "attemptPresent": bool(source.get("attemptPresent")),
            "selectedAttemptPresent": bool(source.get("selectedAttemptPresent")),
            "leaseReleased": bool(source.get("leaseReleased")),
            "leaseGeneration": _safe_int(source.get("leaseGeneration")),
        },
        "targetAttempt": {
            "targetAttemptRequired": bool(target.get("targetAttemptRequired")),
            "creationMode": str(target.get("creationMode") or ""),
            "activeLeaseRequiredBeforeMutation": bool(target.get("activeLeaseRequiredBeforeMutation")),
            "activeLeaseRequiredDuringExecution": bool(target.get("activeLeaseRequiredDuringExecution")),
            "sourcePlanHashRevalidationRequired": bool(target.get("sourcePlanHashRevalidationRequired")),
            "outputAdoptionScopeRevalidationRequired": bool(target.get("outputAdoptionScopeRevalidationRequired")),
        },
        "outputClosure": {
            "preservedOutputEdgesRequired": bool(output_closure.get("preservedOutputEdgesRequired")),
        },
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(lifecycle.get("pathExposed")),
        "storageUriExposed": bool(lifecycle.get("storageUriExposed")),
    }


def _public_partial_output_closure(closure: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(closure.get("schemaVersion") or ""),
        "available": bool(closure.get("available")),
        "edgeClosureReady": bool(closure.get("edgeClosureReady")),
        "closureReady": bool(closure.get("closureReady")),
        "reasonCode": str(closure.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(closure.get("blockedReasonCodes")),
        "declaredOutputBlockedReasonCodes": _string_list(closure.get("declaredOutputBlockedReasonCodes")),
        "scopedOutputCount": _safe_int(closure.get("scopedOutputCount")),
        "adoptedScopedOutputCount": _safe_int(closure.get("adoptedScopedOutputCount")),
        "pendingScopedOutputCount": _safe_int(closure.get("pendingScopedOutputCount")),
        "preservedRuleCount": _safe_int(closure.get("preservedRuleCount")),
        "preservedOutputEdgeCount": _safe_int(closure.get("preservedOutputEdgeCount")),
        "missingPreservedOutputEdgeCount": _safe_int(closure.get("missingPreservedOutputEdgeCount")),
        "unknownActiveOutputEdgeCount": _safe_int(closure.get("unknownActiveOutputEdgeCount")),
        "declaredOutputCount": _safe_int(closure.get("declaredOutputCount")),
        "checkedDeclaredOutputCount": _safe_int(closure.get("checkedDeclaredOutputCount")),
        "verifiedDeclaredOutputCount": _safe_int(closure.get("verifiedDeclaredOutputCount")),
        "adoptedDeclaredOutputCount": _safe_int(closure.get("adoptedDeclaredOutputCount")),
        "missingDeclaredOutputCount": _safe_int(closure.get("missingDeclaredOutputCount")),
        "rerunRequiredDeclaredOutputCount": _safe_int(closure.get("rerunRequiredDeclaredOutputCount")),
        "allDeclaredOutputsVerified": bool(closure.get("allDeclaredOutputsVerified")),
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(closure.get("pathExposed")),
        "storageUriExposed": bool(closure.get("storageUriExposed")),
    }


def _public_executor_orchestration(orchestration: dict[str, Any], *, blocked_response: bool) -> dict[str, Any]:
    launch = _dict_value(orchestration.get("launchPreflight"))
    boundary = _dict_value(orchestration.get("executionBoundary"))
    executor_ready = orchestration.get("executorReady") is True and not blocked_response
    return {
        "schemaVersion": str(orchestration.get("schemaVersion") or ""),
        "mode": str(orchestration.get("mode") or ""),
        "available": bool(orchestration.get("available")),
        "contractReady": bool(orchestration.get("contractReady")),
        "executorReady": executor_ready,
        "reasonCode": str(orchestration.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(orchestration.get("blockedReasonCodes")),
        "requiresBeforeExecution": _string_list(orchestration.get("requiresBeforeExecution")),
        "launchPreflight": _public_launch_preflight(launch, blocked_response=blocked_response),
        "launchPreflightReady": bool(orchestration.get("launchPreflightReady")),
        "launchReady": False,
        "executionBoundary": _public_execution_boundary(boundary),
        "executionBoundaryReady": bool(orchestration.get("executionBoundaryReady")),
        "selectedRuleCount": _safe_int(orchestration.get("selectedRuleCount")),
        "rerunRuleCount": _safe_int(orchestration.get("rerunRuleCount")),
        "cacheRestoreOutputCount": _safe_int(orchestration.get("cacheRestoreOutputCount")),
        "cacheRestoreHitCount": _safe_int(orchestration.get("cacheRestoreHitCount")),
        "targetOutputCount": _safe_int(orchestration.get("targetOutputCount")),
        "adoptedOutputCount": _safe_int(orchestration.get("adoptedOutputCount")),
        "verifiedOutputCount": _safe_int(orchestration.get("verifiedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(orchestration.get("rerunRequiredOutputCount")),
        "lifecycleContractReady": bool(orchestration.get("lifecycleContractReady")),
        "sourceAttemptLeaseReleased": bool(orchestration.get("sourceAttemptLeaseReleased")),
        "targetAttemptRequired": bool(orchestration.get("targetAttemptRequired")),
        "activeLeaseRequired": bool(orchestration.get("activeLeaseRequired")),
        "workdirReuseRequired": bool(orchestration.get("workdirReuseRequired")),
        "workdirReusable": bool(orchestration.get("workdirReusable")),
        "resultDirReuseRequired": bool(orchestration.get("resultDirReuseRequired")),
        "runConfigRewriteAllowed": bool(orchestration.get("runConfigRewriteAllowed")),
        "snakemakeMetadataRequired": bool(orchestration.get("snakemakeMetadataRequired")),
        "executionOptionsSchemaVersion": str(orchestration.get("executionOptionsSchemaVersion") or ""),
        "rerunIncompleteRequired": bool(orchestration.get("rerunIncompleteRequired")),
        "forcerunRulesRequired": bool(orchestration.get("forcerunRulesRequired")),
        "cacheAdoptionBypassRequired": bool(orchestration.get("cacheAdoptionBypassRequired")),
        "artifactAdoptionRequired": bool(orchestration.get("artifactAdoptionRequired")),
        "finalizeRunAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(orchestration.get("pathExposed")),
        "storageUriExposed": bool(orchestration.get("storageUriExposed")),
    }


def _public_launch_preflight(launch: dict[str, Any], *, blocked_response: bool) -> dict[str, Any]:
    return {
        "schemaVersion": str(launch.get("schemaVersion") or ""),
        "available": bool(launch.get("available")),
        "mode": str(launch.get("mode") or ""),
        "preflightReady": bool(launch.get("preflightReady")),
        "launchReady": False,
        "reasonCode": str(launch.get("reasonCode") or ""),
        "preflightReasonCode": str(launch.get("preflightReasonCode") or ""),
        "blockedReasonCodes": _blocked_preflight_reasons(launch, blocked_response=blocked_response),
        "evidenceBlockedReasonCodes": _string_list(launch.get("evidenceBlockedReasonCodes")),
        "orchestrationContractReady": bool(launch.get("orchestrationContractReady")),
        "terminalSourceAttemptReady": bool(launch.get("terminalSourceAttemptReady")),
        "sourceAttemptIdPresent": bool(launch.get("sourceAttemptIdPresent")),
        "sourceAttemptLeaseGeneration": _safe_int(launch.get("sourceAttemptLeaseGeneration")),
        "sourcePlanHashPresent": bool(launch.get("sourcePlanHashPresent")),
        "planHashCurrent": bool(launch.get("planHashCurrent")),
        "planHashMatches": bool(launch.get("planHashMatches")),
        "executionPlanHashRevalidationRequired": bool(launch.get("executionPlanHashRevalidationRequired")),
        "sourcePlanHashRevalidationRequired": bool(launch.get("sourcePlanHashRevalidationRequired")),
        "outputAdoptionScopeRevalidationRequired": bool(launch.get("outputAdoptionScopeRevalidationRequired")),
        "outputAdoptionScopePlanHashMatches": bool(launch.get("outputAdoptionScopePlanHashMatches")),
        "targetAttemptRequired": bool(launch.get("targetAttemptRequired")),
        "targetAttemptPresent": bool(launch.get("targetAttemptPresent")),
        "activeLeaseRequired": bool(launch.get("activeLeaseRequired")),
        "activeLeaseRequiredBeforeMutation": bool(launch.get("activeLeaseRequiredBeforeMutation")),
        "activeLeaseRequiredDuringExecution": bool(launch.get("activeLeaseRequiredDuringExecution")),
        "activeLeasePresent": bool(launch.get("activeLeasePresent")),
        "activeLeaseMatchesAttempt": bool(launch.get("activeLeaseMatchesAttempt")),
        "activeLeasePolicyReady": bool(launch.get("activeLeasePolicyReady")),
        "workDirPresent": bool(launch.get("workDirPresent")),
        "workDirManaged": bool(launch.get("workDirManaged")),
        "workDirReusable": bool(launch.get("workDirReusable")),
        "workdirReady": bool(launch.get("workdirReady")),
        "outputAdoptionScopeReady": bool(launch.get("outputAdoptionScopeReady")),
        "outputAdoptionScopeOutputCount": _safe_int(launch.get("outputAdoptionScopeOutputCount")),
        "snakemakeOptionsReady": bool(launch.get("snakemakeOptionsReady")),
        "unsafeFlagsAbsent": bool(launch.get("unsafeFlagsAbsent")),
        "unsafeFlags": _string_list(launch.get("unsafeFlags")),
        "outputClosureReady": bool(launch.get("outputClosureReady")),
        "edgeClosureReady": bool(launch.get("edgeClosureReady")),
        "lifecycleContractReady": bool(launch.get("lifecycleContractReady")),
        "executorStartAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(launch.get("pathExposed")),
        "storageUriExposed": bool(launch.get("storageUriExposed")),
    }


def _public_execution_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(boundary.get("schemaVersion") or ""),
        "available": bool(boundary.get("available")),
        "boundaryReady": bool(boundary.get("boundaryReady")),
        "reasonCode": str(boundary.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(boundary.get("blockedReasonCodes")),
        "selectedRuleCount": _safe_int(boundary.get("selectedRuleCount")),
        "rerunRuleCount": _safe_int(boundary.get("rerunRuleCount")),
        "scopedOutputCount": _safe_int(boundary.get("scopedOutputCount")),
        "declaredOutputCount": _safe_int(boundary.get("declaredOutputCount")),
        "explicitTargetCount": _safe_int(boundary.get("explicitTargetCount")),
        "explicitTargetsPresent": bool(boundary.get("explicitTargetsPresent")),
        "freshAttemptWorkdir": bool(boundary.get("freshAttemptWorkdir")),
        "attemptScopedResultDir": bool(boundary.get("attemptScopedResultDir")),
        "postExecutionArtifactAdoptionMode": str(boundary.get("postExecutionArtifactAdoptionMode") or ""),
        "finalizeWouldCompleteRun": bool(boundary.get("finalizeWouldCompleteRun")),
        "finalizeRunAllowed": False,
        "executorStartAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(boundary.get("pathExposed")),
        "storageUriExposed": bool(boundary.get("storageUriExposed")),
    }


def _public_snakemake_options(snakemake: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(snakemake.get("schemaVersion") or ""),
        "rerunIncomplete": bool(snakemake.get("rerunIncomplete")),
        "forcerunRuleCount": _collection_size(snakemake.get("forcerunRules")),
        "targetOutputCount": _collection_size(snakemake.get("targetOutputKeys")),
        "argsPreviewCount": _collection_size(snakemake.get("argsPreview")),
        "unsafeFlagsProhibited": _string_list(snakemake.get("unsafeFlagsProhibited")),
    }


def _public_activation_readiness(readiness: dict[str, Any], *, blocked_response: bool) -> dict[str, Any]:
    return {
        "schemaVersion": str(readiness.get("schemaVersion") or ""),
        "runId": str(readiness.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(readiness.get("workflowRevisionId") or "").strip()),
        "executionReady": False if blocked_response else readiness.get("executionReady") is True,
        "executionEnabled": False if blocked_response else readiness.get("executionEnabled") is True,
        "reasonCode": str(readiness.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(readiness.get("blockedReasonCodes")),
        "readyCheckCount": _safe_int(readiness.get("readyCheckCount")),
        "blockedCheckCount": _safe_int(readiness.get("blockedCheckCount")),
        "checks": [_public_readiness_check(item) for item in _list_value(readiness.get("checks"))],
        "summary": _int_mapping(readiness.get("summary")),
        "redactionPolicy": _bool_mapping(
            readiness.get("redactionPolicy"),
            allowed_keys=("rawIdentifiersExposed", "fingerprintsExposed", "storageUrisExposed", "pathsExposed"),
        ),
    }


def _public_readiness_check(value: Any) -> dict[str, Any]:
    check = _dict_value(value)
    return {
        "name": str(check.get("name") or ""),
        "ready": bool(check.get("ready")),
        "reasonCode": str(check.get("reasonCode") or ""),
    }


def _count_policy(value: Any, *, keys: tuple[str, ...]) -> dict[str, Any]:
    policy = _dict_value(value)
    result: dict[str, Any] = {}
    for key in keys:
        raw = policy.get(key)
        result[key] = bool(raw) if _is_bool_policy_key(key, raw) else _safe_int(raw)
    if "reasonCode" in policy:
        result["reasonCode"] = str(policy.get("reasonCode") or "")
    if "blockedReasonCodes" in policy:
        result["blockedReasonCodes"] = _string_list(policy.get("blockedReasonCodes"))
    return result


def _blocked_reasons(plan: dict[str, Any], denial_code: str) -> list[str]:
    return _unique_strings([denial_code, *_string_list(plan.get("blockedReasonCodes"))])


def _requires_before_execution(plan: dict[str, Any], denial_code: str) -> list[str]:
    return _unique_strings([denial_code, *_string_list(plan.get("requiresBeforeExecution"))])


def _blocked_preflight_reasons(launch: dict[str, Any], *, blocked_response: bool) -> list[str]:
    reasons = _string_list(launch.get("blockedReasonCodes"))
    if blocked_response and not reasons:
        reasons = ["RULE_RETRY_EXECUTION_DISABLED"]
    return reasons


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(raw) for key, raw in value.items() if str(key or "").strip()}


def _bool_mapping(value: Any, *, allowed_keys: tuple[str, ...]) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: bool(source.get(key)) for key in allowed_keys}


def _is_bool_policy_key(key: str, value: Any) -> bool:
    return isinstance(value, bool) or key in _BOOL_POLICY_KEYS or key.endswith(_BOOL_POLICY_KEY_SUFFIXES)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _list_value(value) if str(item or "").strip()]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            unique.append(text)
            seen.add(text)
    return unique


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _collection_size(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0
