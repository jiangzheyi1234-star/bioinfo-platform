from __future__ import annotations

from typing import Any


RULE_RETRY_ACTIVATION_READINESS_SCHEMA_VERSION = "rule-retry-activation-readiness.v1"
RUN_RESUME_ACTIVATION_READINESS_SCHEMA_VERSION = "run-resume-activation-readiness.v1"


def build_rule_retry_activation_readiness(
    *,
    rule_retry_plan: dict[str, Any],
    execution_plan: dict[str, Any],
    workdir_reuse_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_restore = _dict_value(execution_plan.get("cacheRestorePlan"))
    output_invalidation = _dict_value(execution_plan.get("outputInvalidationPlan"))
    snakemake_options = _dict_value(execution_plan.get("snakemakeOptions"))
    output_state = _dict_value(output_invalidation.get("outputInvalidationState"))
    output_audit = _dict_value(execution_plan.get("incompleteOutputAudit"))
    staged_file_policy = _dict_value(cache_restore.get("stagedFilePolicy"))
    restore_pin_policy = _dict_value(cache_restore.get("restorePinPolicy"))
    promotion_state = _dict_value(cache_restore.get("finalOutputPromotionState"))
    partial_restore_executor = _dict_value(cache_restore.get("partialRestoreExecutor"))
    executor_orchestration = _dict_value(execution_plan.get("executorOrchestration"))
    lifecycle = _dict_value(execution_plan.get("partialRerunLifecycle"))
    lifecycle_path_exposed = _redaction_exposed(lifecycle, "pathExposed")
    lifecycle_storage_uri_exposed = _redaction_exposed(lifecycle, "storageUriExposed")
    redaction = _dict_value(cache_restore.get("redactionPolicy"))
    workdir_policy = _dict_value(workdir_reuse_policy)

    selected_rules = _list_value(execution_plan.get("selectedRules"))
    rerun_scope = _dict_value(execution_plan.get("rerunScope"))
    forcerun_rules = _list_value(snakemake_options.get("forcerunRules"))
    args_preview = _list_value(snakemake_options.get("argsPreview"))
    target_count = _safe_int(promotion_state.get("targetCount"))
    promoted_count = _safe_int(promotion_state.get("promotedFinalOutputCount"))
    adopted_count = _safe_int(promotion_state.get("adoptedCandidateOutputCount"))
    required_pin_count = _safe_int(restore_pin_policy.get("requiredPinCount"))
    created_pin_count = _safe_int(restore_pin_policy.get("createdPinCount"))

    checks = [
        _check(
            "attemptSelection",
            bool(rule_retry_plan.get("invalidationPlanAvailable"))
            and _safe_int(rule_retry_plan.get("selectedAttemptCount")) > 0
            and bool(selected_rules),
            _first_nonempty(
                execution_plan.get("sourceReasonCode"),
                execution_plan.get("reasonCode"),
                "RULE_RETRY_ATTEMPT_SELECTION_UNPROVEN",
            ),
        ),
        _check(
            "outputInvalidationApplied",
            output_state.get("state") == "applied" and _safe_int(output_state.get("appliedOutputEdgeCount")) > 0,
            "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED",
        ),
        _check(
            "perRuleCacheEligibility",
            _safe_int(cache_restore.get("outputCount")) > 0
            and _safe_int(cache_restore.get("cacheHitCount")) == _safe_int(cache_restore.get("outputCount")),
            _first_nonempty(cache_restore.get("reasonCode"), "PER_RULE_CACHE_ELIGIBILITY_UNPROVEN"),
        ),
        _check(
            "restorePins",
            required_pin_count > 0 and created_pin_count >= required_pin_count,
            _first_nonempty(restore_pin_policy.get("reasonCode"), "RESTORE_PIN_POLICY_UNPROVEN"),
        ),
        _check(
            "stagedFilePromotion",
            target_count > 0 and promoted_count >= target_count,
            _first_nonempty(staged_file_policy.get("reasonCode"), "STAGED_FILE_POLICY_UNPROVEN"),
        ),
        _check(
            "restoredOutputAdoption",
            target_count > 0 and adopted_count >= target_count,
            "RESTORED_OUTPUT_ADOPTION_REQUIRED",
        ),
        _check(
            "workdirReuse",
            workdir_policy.get("workDirReusable") is True,
            _first_nonempty(workdir_policy.get("reasonCode"), "WORKDIR_REUSE_POLICY_UNPROVEN"),
        ),
        _check(
            "incompleteOutputAudit",
            output_audit.get("available") is True
            and _safe_int(output_audit.get("unsafeOutputCount")) == 0
            and _safe_int(output_audit.get("uncheckedOutputCount")) == 0
            and _safe_int(output_audit.get("unverifiedOutputCount")) == 0,
            _first_nonempty(output_audit.get("reasonCode"), "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN"),
        ),
        _check(
            "partialRerunLifecycle",
            lifecycle.get("contractReady") is True
            and lifecycle_path_exposed is not True
            and lifecycle_storage_uri_exposed is not True,
            _first_nonempty(
                "RULE_PARTIAL_RERUN_LIFECYCLE_REDACTION_UNSAFE"
                if lifecycle_path_exposed or lifecycle_storage_uri_exposed
                else "",
                lifecycle.get("reasonCode"),
                "RULE_PARTIAL_RERUN_LIFECYCLE_UNPROVEN",
            ),
        ),
        _check(
            "snakemakeOptions",
            bool(execution_plan.get("commandPreviewAvailable"))
            and snakemake_options.get("rerunIncomplete") is True
            and bool(forcerun_rules)
            and "--forcerun" in args_preview,
            _first_nonempty(execution_plan.get("reasonCode"), "SNAKEMAKE_RULE_RERUN_OPTIONS_UNPROVEN"),
        ),
        _check(
            "partialRerunExecutor",
            executor_orchestration.get("executorReady") is True,
            _first_nonempty(
                executor_orchestration.get("reasonCode"),
                partial_restore_executor.get("reasonCode"),
                "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE",
            ),
        ),
        _check(
            "publicMutation",
            execution_plan.get("executionEnabled") is True,
            "RULE_RETRY_MUTATION_API_DISABLED",
        ),
    ]
    return _readiness(
        schema_version=RULE_RETRY_ACTIVATION_READINESS_SCHEMA_VERSION,
        run_id=execution_plan.get("runId"),
        workflow_revision_id=execution_plan.get("workflowRevisionId"),
        execution_enabled=execution_plan.get("executionEnabled") is True,
        checks=checks,
        summary={
            "selectedRuleCount": len(selected_rules),
            "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
            "cacheRestoreOutputCount": _safe_int(cache_restore.get("outputCount")),
            "cacheRestoreHitCount": _safe_int(cache_restore.get("cacheHitCount")),
            "restoreTargetCount": target_count,
            "promotedOutputCount": promoted_count,
            "adoptedOutputCount": adopted_count,
            "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
            "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
            "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
            "unverifiedOutputCount": _safe_int(output_audit.get("unverifiedOutputCount")),
            "lifecycleContractReady": 1 if lifecycle.get("contractReady") is True else 0,
            "lifecycleMutationReady": 1 if lifecycle.get("mutationReady") is True else 0,
            "executorContractReady": 1 if executor_orchestration.get("contractReady") is True else 0,
            "executorReady": 1 if executor_orchestration.get("executorReady") is True else 0,
            "unsafeFlagCount": len(_list_value(snakemake_options.get("unsafeFlagsProhibited"))),
        },
        redaction_policy={
            "rawIdentifiersExposed": bool(redaction.get("cacheKeysExposed")),
            "fingerprintsExposed": bool(redaction.get("cacheKeyFingerprintsExposed")),
            "storageUrisExposed": bool(redaction.get("storageUrisExposed"))
            or bool(executor_orchestration.get("storageUriExposed"))
            or lifecycle_storage_uri_exposed,
            "pathsExposed": bool(redaction.get("pathsExposed"))
            or bool(executor_orchestration.get("pathExposed"))
            or lifecycle_path_exposed,
        },
    )


def build_run_resume_activation_readiness(*, resume_plan: dict[str, Any]) -> dict[str, Any]:
    workdir = _dict_value(resume_plan.get("workdirEvidence"))
    output_audit = _dict_value(resume_plan.get("incompleteOutputAudit"))
    adoption = _dict_value(resume_plan.get("artifactAdoptionBoundary"))
    executor_orchestration = _dict_value(resume_plan.get("executorOrchestration"))
    snakemake_options = _dict_value(resume_plan.get("snakemakeOptions"))
    args_preview = _list_value(snakemake_options.get("argsPreview"))

    checks = [
        _check(
            "resumePreflight",
            bool(resume_plan.get("commandPreviewAvailable")),
            _first_nonempty(resume_plan.get("reasonCode"), "RUN_RESUME_PREFLIGHT_UNPROVEN"),
        ),
        _check(
            "workdirReuse",
            workdir.get("workDirReusable") is True,
            _first_nonempty(workdir.get("reasonCode"), "WORKDIR_REUSE_POLICY_UNPROVEN"),
        ),
        _check(
            "incompleteOutputAudit",
            output_audit.get("available") is True
            and _safe_int(output_audit.get("unsafeOutputCount")) == 0
            and _safe_int(output_audit.get("uncheckedOutputCount")) == 0
            and _safe_int(output_audit.get("unverifiedOutputCount")) == 0,
            _first_nonempty(output_audit.get("reasonCode"), "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN"),
        ),
        _check(
            "artifactAdoption",
            (adoption.get("enabled") is True or adoption.get("available") is True)
            and adoption.get("pathExposed") is not True
            and adoption.get("storageUriExposed") is not True,
            _first_nonempty(adoption.get("reasonCode"), "ARTIFACT_ADOPTION_UNPROVEN"),
        ),
        _check(
            "executorOrchestration",
            executor_orchestration.get("executorReady") is True,
            _first_nonempty(executor_orchestration.get("reasonCode"), "RUN_RESUME_EXECUTOR_ORCHESTRATION_UNPROVEN"),
        ),
        _check(
            "snakemakeOptions",
            bool(resume_plan.get("commandPreviewAvailable"))
            and snakemake_options.get("rerunIncomplete") is True
            and "--rerun-incomplete" in args_preview,
            _first_nonempty(resume_plan.get("reasonCode"), "SNAKEMAKE_RUN_RESUME_OPTIONS_UNPROVEN"),
        ),
        _check(
            "publicMutation",
            resume_plan.get("executionEnabled") is True,
            "RUN_RESUME_MUTATION_API_DISABLED",
        ),
    ]
    return _readiness(
        schema_version=RUN_RESUME_ACTIVATION_READINESS_SCHEMA_VERSION,
        run_id=resume_plan.get("runId"),
        workflow_revision_id=resume_plan.get("workflowRevisionId"),
        execution_enabled=resume_plan.get("executionEnabled") is True,
        checks=checks,
        summary={
            "attemptCount": _safe_int(resume_plan.get("attemptCount")),
            "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
            "checkedOutputCount": _safe_int(output_audit.get("checkedOutputCount")),
            "existingOutputCount": _safe_int(output_audit.get("existingOutputCount")),
            "missingOutputCount": _safe_int(output_audit.get("missingOutputCount")),
            "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
            "checksumVerifiedOutputCount": _safe_int(output_audit.get("checksumVerifiedOutputCount")),
            "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
            "rerunRequired": 1 if output_audit.get("rerunRequired") is True else 0,
            "unsafeOutputCount": _safe_int(output_audit.get("unsafeOutputCount")),
            "uncheckedOutputCount": _safe_int(output_audit.get("uncheckedOutputCount")),
            "unverifiedOutputCount": _safe_int(output_audit.get("unverifiedOutputCount")),
            "executorContractReady": 1 if executor_orchestration.get("contractReady") is True else 0,
            "executorReady": 1 if executor_orchestration.get("executorReady") is True else 0,
        },
        redaction_policy={
            "rawIdentifiersExposed": False,
            "fingerprintsExposed": False,
            "storageUrisExposed": bool(adoption.get("storageUriExposed"))
            or bool(executor_orchestration.get("storageUriExposed")),
            "pathsExposed": bool(workdir.get("pathExposed"))
            or bool(output_audit.get("pathExposed"))
            or bool(adoption.get("pathExposed"))
            or bool(executor_orchestration.get("pathExposed")),
        },
    )


def _readiness(
    *,
    schema_version: str,
    run_id: Any,
    workflow_revision_id: Any,
    execution_enabled: bool,
    checks: list[dict[str, Any]],
    summary: dict[str, int],
    redaction_policy: dict[str, bool],
) -> dict[str, Any]:
    blocked = [str(item["reasonCode"]) for item in checks if item.get("ready") is not True]
    unique_blocked = _unique_strings(blocked)
    return {
        "schemaVersion": schema_version,
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id,
        "executionReady": not unique_blocked and execution_enabled,
        "executionEnabled": execution_enabled,
        "reasonCode": unique_blocked[0] if unique_blocked else "ACTIVATION_READY",
        "blockedReasonCodes": unique_blocked,
        "readyCheckCount": sum(1 for item in checks if item.get("ready") is True),
        "blockedCheckCount": sum(1 for item in checks if item.get("ready") is not True),
        "checks": checks,
        "summary": summary,
        "redactionPolicy": redaction_policy,
    }


def _check(name: str, ready: bool, reason_code: Any) -> dict[str, Any]:
    return {
        "name": name,
        "ready": bool(ready),
        "reasonCode": "READY" if ready else str(reason_code or f"{name.upper()}_UNPROVEN"),
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return "UNPROVEN"


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _redaction_exposed(value: Any, field: str) -> bool:
    if isinstance(value, dict):
        if value.get(field) is True:
            return True
        return any(_redaction_exposed(item, field) for item in value.values())
    if isinstance(value, list):
        return any(_redaction_exposed(item, field) for item in value)
    return False
