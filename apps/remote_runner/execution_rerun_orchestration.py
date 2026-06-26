from __future__ import annotations

from typing import Any

from .rule_partial_rerun_execution_boundary import build_rule_partial_rerun_execution_boundary
from .rule_partial_rerun_launch_preflight import build_rule_partial_rerun_launch_preflight


RERUN_EXECUTOR_ORCHESTRATION_SCHEMA_VERSION = "rerun-executor-orchestration.v1"
RUN_RESUME_ARTIFACT_ADOPTION_BOUNDARY_SCHEMA_VERSION = "run-resume-artifact-adoption-boundary.v1"
RUN_RESUME_EXECUTOR_PREVIEW_ONLY = "RUN_RESUME_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY"
PARTIAL_RERUN_EXECUTOR_PREVIEW_ONLY = "PARTIAL_RERUN_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY"
RULE_RETRY_MUTATION_API_DISABLED = "RULE_RETRY_MUTATION_API_DISABLED"


def build_run_resume_artifact_adoption_boundary(
    *,
    workdir_evidence: dict[str, Any],
    output_audit: dict[str, Any],
) -> dict[str, Any]:
    workdir_ready = workdir_evidence.get("workDirReusable") is True
    audit_ready = _output_audit_ready(output_audit)
    available = workdir_ready and audit_ready and _safe_int(output_audit.get("expectedOutputCount")) > 0
    reason_code = (
        "RUN_RESUME_ARTIFACT_ADOPTION_BOUNDARY_VERIFIED"
        if available
        else _first_nonempty(
            workdir_evidence.get("reasonCode") if not workdir_ready else "",
            output_audit.get("reasonCode") if not audit_ready else "",
            "RUN_RESUME_ARTIFACT_ADOPTION_BOUNDARY_UNPROVEN",
        )
    )
    return {
        "schemaVersion": RUN_RESUME_ARTIFACT_ADOPTION_BOUNDARY_SCHEMA_VERSION,
        "enabled": available,
        "available": available,
        "reasonCode": reason_code,
        "adoptedArtifacts": [],
        "adoptedCacheEntries": [],
        "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
        "checksumVerifiedOutputCount": _safe_int(output_audit.get("checksumVerifiedOutputCount")),
        "retainedOutputCount": _safe_int(output_audit.get("existingOutputCount")),
        "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
        "unsafeOutputCount": _safe_int(output_audit.get("unsafeOutputCount")),
        "unverifiedOutputCount": _safe_int(output_audit.get("unverifiedOutputCount")),
        "preExecutionAdoptionAllowed": False,
        "postExecutionAdoptionRequired": True,
        "cacheAdoptionAllowed": False,
        "lineageMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "checksumValueExposed": False,
        "requires": [
            "managed_failed_attempt_workdir",
            "verified_declared_outputs",
            "missing_outputs_rerun_required",
            "post_resume_candidate_output_adoption",
        ],
    }


def build_run_resume_executor_orchestration(resume_plan: dict[str, Any]) -> dict[str, Any]:
    workdir = _dict_value(resume_plan.get("workdirEvidence"))
    output_audit = _dict_value(resume_plan.get("incompleteOutputAudit"))
    adoption = _dict_value(resume_plan.get("artifactAdoptionBoundary"))
    snakemake = _dict_value(resume_plan.get("snakemakeOptions"))
    latest_attempt = _dict_value(resume_plan.get("latestAttempt"))
    contract_blockers: list[str] = []
    if resume_plan.get("commandPreviewAvailable") is not True:
        contract_blockers.append(_first_nonempty(resume_plan.get("reasonCode"), "RUN_RESUME_COMMAND_PREVIEW_REQUIRED"))
    if workdir.get("workDirReusable") is not True:
        contract_blockers.append(_first_nonempty(workdir.get("reasonCode"), "WORKDIR_REUSE_POLICY_UNPROVEN"))
    if not _output_audit_ready(output_audit):
        contract_blockers.append(_first_nonempty(output_audit.get("reasonCode"), "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN"))
    if adoption.get("available") is not True and adoption.get("enabled") is not True:
        contract_blockers.append(_first_nonempty(adoption.get("reasonCode"), "ARTIFACT_ADOPTION_BOUNDARY_UNPROVEN"))
    if snakemake.get("rerunIncomplete") is not True:
        contract_blockers.append("SNAKEMAKE_RUN_RESUME_OPTIONS_UNPROVEN")
    contract_ready = not contract_blockers
    blocked_reason_codes = _unique_strings(
        [
            *contract_blockers,
            RUN_RESUME_EXECUTOR_PREVIEW_ONLY,
        ]
    )
    return {
        "schemaVersion": RERUN_EXECUTOR_ORCHESTRATION_SCHEMA_VERSION,
        "mode": "run-resume",
        "available": True,
        "contractReady": contract_ready,
        "executorReady": False,
        "reasonCode": RUN_RESUME_EXECUTOR_PREVIEW_ONLY if contract_ready else blocked_reason_codes[0],
        "blockedReasonCodes": blocked_reason_codes,
        "requiresBeforeExecution": blocked_reason_codes,
        "sourceAttempt": {
            "attemptPresent": bool(str(latest_attempt.get("attemptId") or "").strip()),
            "attemptNumber": latest_attempt.get("attemptNumber"),
            "leaseGeneration": latest_attempt.get("leaseGeneration"),
            "state": latest_attempt.get("state"),
        },
        "targetAttemptRequired": True,
        "activeLeaseRequired": False,
        "workdirReuseRequired": True,
        "workdirReusable": workdir.get("workDirReusable") is True,
        "resultDirReuseRequired": True,
        "runConfigRewriteAllowed": False,
        "snakemakeMetadataRequired": False,
        "executionOptionsSchemaVersion": "run-job-execution-options.v1",
        "rerunIncompleteRequired": True,
        "forcerunRulesRequired": False,
        "cacheAdoptionBypassRequired": True,
        "artifactAdoptionRequired": True,
        "finalizeRunAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
    }


def build_rule_partial_rerun_orchestration(
    execution_plan: dict[str, Any],
    *,
    workdir_reuse_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    cache_restore = _dict_value(execution_plan.get("cacheRestorePlan"))
    output_invalidation = _dict_value(execution_plan.get("outputInvalidationPlan"))
    output_state = _dict_value(output_invalidation.get("outputInvalidationState"))
    output_audit = _dict_value(execution_plan.get("incompleteOutputAudit"))
    lifecycle = _dict_value(execution_plan.get("partialRerunLifecycle"))
    source_attempt = _dict_value(lifecycle.get("sourceAttempt"))
    target_attempt = _dict_value(lifecycle.get("targetAttempt"))
    output_closure = _dict_value(lifecycle.get("outputClosure"))
    partial_output_closure = _dict_value(execution_plan.get("partialRerunOutputClosure"))
    lifecycle_path_exposed = _redaction_exposed(lifecycle, "pathExposed")
    lifecycle_storage_uri_exposed = _redaction_exposed(lifecycle, "storageUriExposed")
    closure_path_exposed = _redaction_exposed(partial_output_closure, "pathExposed")
    closure_storage_uri_exposed = _redaction_exposed(partial_output_closure, "storageUriExposed")
    snakemake = _dict_value(execution_plan.get("snakemakeOptions"))
    promotion = _dict_value(cache_restore.get("finalOutputPromotionState"))
    redaction = _dict_value(cache_restore.get("redactionPolicy"))
    workdir = _dict_value(workdir_reuse_policy)
    selected_rules = _list_value(execution_plan.get("selectedRules"))
    rerun_scope = _dict_value(execution_plan.get("rerunScope"))
    target_count = _safe_int(promotion.get("targetCount"))
    adopted_count = _safe_int(promotion.get("adoptedCandidateOutputCount"))
    cache_output_count = _safe_int(cache_restore.get("outputCount"))
    cache_hit_count = _safe_int(cache_restore.get("cacheHitCount"))
    contract_blockers: list[str] = []
    if execution_plan.get("commandPreviewAvailable") is not True:
        contract_blockers.append(_first_nonempty(execution_plan.get("reasonCode"), "RULE_RERUN_COMMAND_PREVIEW_REQUIRED"))
    if output_state.get("state") != "applied" or _safe_int(output_state.get("appliedOutputEdgeCount")) <= 0:
        contract_blockers.append("DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED")
    if cache_output_count <= 0 or cache_hit_count < cache_output_count:
        contract_blockers.append(_first_nonempty(cache_restore.get("reasonCode"), "PER_RULE_CACHE_ELIGIBILITY_UNPROVEN"))
    if target_count <= 0 or adopted_count < target_count:
        contract_blockers.append("RESTORED_OUTPUT_ADOPTION_REQUIRED")
    if not _output_audit_ready(output_audit):
        contract_blockers.append(_first_nonempty(output_audit.get("reasonCode"), "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN"))
    if lifecycle.get("contractReady") is not True:
        contract_blockers.append(_first_nonempty(lifecycle.get("reasonCode"), "RULE_PARTIAL_RERUN_LIFECYCLE_UNPROVEN"))
    if lifecycle_path_exposed or lifecycle_storage_uri_exposed:
        contract_blockers.append("RULE_PARTIAL_RERUN_LIFECYCLE_REDACTION_UNSAFE")
    if partial_output_closure.get("closureReady") is not True:
        contract_blockers.append(
            _first_nonempty(partial_output_closure.get("reasonCode"), "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_UNPROVEN")
        )
    if closure_path_exposed or closure_storage_uri_exposed:
        contract_blockers.append("RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_REDACTION_UNSAFE")
    if workdir.get("workDirReusable") is not True:
        contract_blockers.append(_first_nonempty(workdir.get("reasonCode"), "WORKDIR_REUSE_POLICY_UNPROVEN"))
    if snakemake.get("rerunIncomplete") is not True or not _list_value(snakemake.get("forcerunRules")):
        contract_blockers.append("SNAKEMAKE_RULE_RERUN_OPTIONS_UNPROVEN")
    contract_ready = not contract_blockers
    launch_preflight = build_rule_partial_rerun_launch_preflight(
        execution_plan,
        workdir_reuse_policy=workdir_reuse_policy,
        orchestration_contract_ready=contract_ready,
        orchestration_blockers=contract_blockers,
    )
    execution_boundary = build_rule_partial_rerun_execution_boundary(execution_plan)
    executor_ready = (
        contract_ready
        and launch_preflight.get("preflightReady") is True
        and execution_boundary.get("boundaryReady") is True
    )
    blocked_reason_codes = _unique_strings(
        [
            *contract_blockers,
            *[str(item) for item in launch_preflight.get("evidenceBlockedReasonCodes") or []],
            *[str(item) for item in execution_boundary.get("blockedReasonCodes") or []],
            *([] if executor_ready else [PARTIAL_RERUN_EXECUTOR_PREVIEW_ONLY]),
            RULE_RETRY_MUTATION_API_DISABLED,
        ]
    )
    return {
        "schemaVersion": RERUN_EXECUTOR_ORCHESTRATION_SCHEMA_VERSION,
        "mode": "rule-partial-rerun",
        "available": True,
        "contractReady": contract_ready,
        "executorReady": executor_ready,
        "reasonCode": RULE_RETRY_MUTATION_API_DISABLED if executor_ready else blocked_reason_codes[0],
        "blockedReasonCodes": blocked_reason_codes,
        "requiresBeforeExecution": blocked_reason_codes,
        "launchPreflight": launch_preflight,
        "launchPreflightReady": launch_preflight.get("preflightReady") is True,
        "launchReady": launch_preflight.get("launchReady") is True,
        "executionBoundary": execution_boundary,
        "executionBoundaryReady": execution_boundary.get("boundaryReady") is True,
        "selectedRuleCount": len(selected_rules),
        "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
        "cacheRestoreOutputCount": cache_output_count,
        "cacheRestoreHitCount": cache_hit_count,
        "targetOutputCount": target_count,
        "adoptedOutputCount": adopted_count,
        "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
        "lifecycleContractReady": lifecycle.get("contractReady") is True,
        "lifecycleMode": str(lifecycle.get("mode") or ""),
        "sourceAttemptLeaseReleased": source_attempt.get("leaseReleased") is True,
        "targetAttemptCreationMode": str(target_attempt.get("creationMode") or ""),
        "sourcePlanHashRevalidationRequired": target_attempt.get("sourcePlanHashRevalidationRequired") is True,
        "preservedOutputClosureRequired": output_closure.get("preservedOutputEdgesRequired") is True,
        "outputClosureReady": partial_output_closure.get("closureReady") is True,
        "edgeClosureReady": partial_output_closure.get("edgeClosureReady") is True,
        "declaredOutputCount": _safe_int(partial_output_closure.get("declaredOutputCount")),
        "verifiedDeclaredOutputCount": _safe_int(partial_output_closure.get("verifiedDeclaredOutputCount")),
        "adoptedDeclaredOutputCount": _safe_int(partial_output_closure.get("adoptedDeclaredOutputCount")),
        "allDeclaredOutputsVerified": partial_output_closure.get("allDeclaredOutputsVerified") is True,
        "preservedOutputEdgeCount": _safe_int(partial_output_closure.get("preservedOutputEdgeCount")),
        "missingPreservedOutputEdgeCount": _safe_int(partial_output_closure.get("missingPreservedOutputEdgeCount")),
        "unknownActiveOutputEdgeCount": _safe_int(partial_output_closure.get("unknownActiveOutputEdgeCount")),
        "targetAttemptRequired": True,
        "activeLeaseRequired": True,
        "workdirReuseRequired": True,
        "workdirReusable": workdir.get("workDirReusable") is True,
        "resultDirReuseRequired": False,
        "runConfigRewriteAllowed": False,
        "snakemakeMetadataRequired": False,
        "executionOptionsSchemaVersion": "run-job-execution-options.v1",
        "rerunIncompleteRequired": True,
        "forcerunRulesRequired": True,
        "cacheAdoptionBypassRequired": True,
        "artifactAdoptionRequired": True,
        "finalizeRunAllowed": execution_boundary.get("finalizeRunAllowed") is True,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(redaction.get("pathsExposed")) or lifecycle_path_exposed or closure_path_exposed,
        "storageUriExposed": bool(redaction.get("storageUrisExposed"))
        or lifecycle_storage_uri_exposed
        or closure_storage_uri_exposed,
    }


def _output_audit_ready(output_audit: dict[str, Any]) -> bool:
    return (
        output_audit.get("available") is True
        and _safe_int(output_audit.get("unsafeOutputCount")) == 0
        and _safe_int(output_audit.get("uncheckedOutputCount")) == 0
        and _safe_int(output_audit.get("unverifiedOutputCount")) == 0
    )


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
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


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
