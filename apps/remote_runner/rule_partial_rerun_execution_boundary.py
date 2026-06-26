from __future__ import annotations

from typing import Any


RULE_PARTIAL_RERUN_EXECUTION_BOUNDARY_SCHEMA_VERSION = "rule-partial-rerun-execution-boundary.v1"


def build_rule_partial_rerun_execution_boundary(execution_plan: dict[str, Any]) -> dict[str, Any]:
    snakemake = _dict_value(execution_plan.get("snakemakeOptions"))
    lifecycle = _dict_value(execution_plan.get("partialRerunLifecycle"))
    target_attempt = _dict_value(lifecycle.get("targetAttempt"))
    cache_restore = _dict_value(execution_plan.get("cacheRestorePlan"))
    output_closure = _dict_value(execution_plan.get("partialRerunOutputClosure"))
    rerun_scope = _dict_value(execution_plan.get("rerunScope"))
    selected_rules = _list_value(execution_plan.get("selectedRules"))
    explicit_targets = (
        _list_value(snakemake.get("targetOutputKeys"))
        or _list_value(snakemake.get("targetOutputs"))
        or _list_value(snakemake.get("targets"))
    )
    scoped_output_count = _safe_int(cache_restore.get("outputCount"))
    declared_output_count = _safe_int(output_closure.get("declaredOutputCount"))
    finalize_would_complete_run = True

    blockers: list[str] = []
    if not explicit_targets:
        blockers.append("SNAKEMAKE_RULE_RERUN_EXPLICIT_TARGETS_REQUIRED")
    if target_attempt.get("creationMode") == "next-worker-claim" and not explicit_targets:
        blockers.append("RULE_PARTIAL_RERUN_FRESH_ATTEMPT_TARGETS_UNPROVEN")
    if scoped_output_count <= 0 or declared_output_count <= 0:
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_SCOPE_UNPROVEN")
    if finalize_would_complete_run:
        blockers.append("RULE_PARTIAL_RERUN_FINALIZE_BOUNDARY_UNPROVEN")

    unique_blockers = _unique_strings(blockers)
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_EXECUTION_BOUNDARY_SCHEMA_VERSION,
        "available": True,
        "boundaryReady": not unique_blockers,
        "reasonCode": "RULE_PARTIAL_RERUN_EXECUTION_BOUNDARY_READY"
        if not unique_blockers
        else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "selectedRuleCount": len(selected_rules),
        "rerunRuleCount": _safe_int(rerun_scope.get("ruleCount")),
        "scopedOutputCount": scoped_output_count,
        "declaredOutputCount": declared_output_count,
        "explicitTargetCount": len(explicit_targets),
        "explicitTargetsPresent": bool(explicit_targets),
        "freshAttemptWorkdir": target_attempt.get("creationMode") == "next-worker-claim",
        "attemptScopedResultDir": True,
        "finalizeWouldCompleteRun": finalize_would_complete_run,
        "finalizeRunAllowed": False,
        "executorStartAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
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


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
