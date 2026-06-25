from __future__ import annotations

from typing import Any

from .execution_plan_hash import attach_plan_hash
from .rule_cache_restore_plan import blocked_rule_cache_restore_plan
from .rule_output_invalidation_plan import blocked_rule_output_invalidation_plan
from .rule_retry_plan import PARTIAL_RETRY_UNSUPPORTED, RULE_RETRY_PLAN_SCHEMA_VERSION
from .workflow_engine_adapter import WorkflowRuntimeCommandError, normalize_forcerun_rules


RULE_RETRY_EXECUTION_PLAN_SCHEMA_VERSION = "rule-retry-execution-plan.v1"
RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION = "run-job-execution-options.v1"
SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION = "snakemake-rule-rerun-options.v1"
UNSAFE_SNAKEMAKE_RULE_RETRY_FLAGS = ["--forceall", "--touch", "--ignore-incomplete"]
RULE_RETRY_EXECUTION_BLOCKERS = [
    "ATTEMPT_OUTPUT_RESTORE_UNPROVEN",
    "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED",
    "PER_RULE_CACHE_ELIGIBILITY_UNPROVEN",
    "STAGED_FILE_POLICY_UNREPRESENTED",
    "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE",
    "CACHE_ADOPTION_UNPROVEN",
    "ARTIFACT_ADOPTION_UNPROVEN",
    "RULE_RETRY_MUTATION_API_DISABLED",
]


def build_rule_retry_execution_plan(
    rule_retry_plan: dict[str, Any],
    cache_restore_plan: dict[str, Any] | None = None,
    output_invalidation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_cache_restore_plan = cache_restore_plan or blocked_rule_cache_restore_plan(rule_retry_plan)
    resolved_output_invalidation_plan = output_invalidation_plan or blocked_rule_output_invalidation_plan(rule_retry_plan)
    base = _base_plan(
        rule_retry_plan,
        cache_restore_plan=resolved_cache_restore_plan,
        output_invalidation_plan=resolved_output_invalidation_plan,
    )
    if rule_retry_plan.get("schemaVersion") != RULE_RETRY_PLAN_SCHEMA_VERSION:
        return _blocked(base, "RULE_RETRY_PLAN_SCHEMA_UNSUPPORTED")
    if not rule_retry_plan.get("invalidationPlanAvailable"):
        return _blocked(base, str(rule_retry_plan.get("reasonCode") or "RULE_RETRY_INVALIDATION_PLAN_UNAVAILABLE"))

    rules = [rule for rule in rule_retry_plan.get("rules") or [] if isinstance(rule, dict)]
    selected_rules = [rule for rule in rules if _attempt_selected(rule)]
    blocked_rule = next(
        (rule for rule in rules if str(rule.get("reasonCode") or "") != PARTIAL_RETRY_UNSUPPORTED),
        None,
    )
    if blocked_rule is not None:
        return _blocked(base, str(blocked_rule.get("reasonCode") or "RULE_RETRY_RULE_BLOCKED"))
    if not selected_rules:
        return _blocked(base, "RULE_RETRY_NO_SELECTED_RULE_ATTEMPTS")
    if len(selected_rules) != len(rules):
        return _blocked(base, "RULE_RETRY_ATTEMPT_SELECTION_INCOMPLETE")

    try:
        forcerun_rules = normalize_forcerun_rules([_required_rule_name(rule) for rule in selected_rules])
    except WorkflowRuntimeCommandError as exc:
        return _blocked(base, str(exc).split(":", 1)[0])

    args_preview = ["--rerun-incomplete", "--forcerun", *forcerun_rules]
    return attach_plan_hash(
        {
            **base,
            "reasonCode": PARTIAL_RETRY_UNSUPPORTED,
            "message": "Rule-level retry command options are planned but execution remains disabled until output restoration and adoption policies are proven.",
            "commandPreviewAvailable": True,
            "selectedRules": [_rule_ref(rule) for rule in selected_rules],
            "rerunScope": {
                "ruleCount": len(rule_retry_plan.get("invalidatedRules") or []),
                "rules": list(rule_retry_plan.get("invalidatedRules") or []),
            },
            "cacheRestorePlan": resolved_cache_restore_plan,
            "outputInvalidationPlan": resolved_output_invalidation_plan,
            "snakemakeOptions": {
                "schemaVersion": SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION,
                "rerunIncomplete": True,
                "forcerunRules": forcerun_rules,
                "argsPreview": args_preview,
                "unsafeFlagsProhibited": UNSAFE_SNAKEMAKE_RULE_RETRY_FLAGS,
            },
        }
    )


def rule_retry_execution_options(rule_retry_execution_plan: dict[str, Any]) -> dict[str, Any]:
    if rule_retry_execution_plan.get("schemaVersion") != RULE_RETRY_EXECUTION_PLAN_SCHEMA_VERSION:
        raise ValueError("RULE_RETRY_EXECUTION_PLAN_SCHEMA_UNSUPPORTED")
    if rule_retry_execution_plan.get("executionEnabled") is not True:
        raise ValueError(_disabled_reason(rule_retry_execution_plan))
    snakemake_options = rule_retry_execution_plan.get("snakemakeOptions")
    if not isinstance(snakemake_options, dict):
        raise ValueError("RULE_RETRY_SNAKEMAKE_OPTIONS_MISSING")
    if snakemake_options.get("schemaVersion") != SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION:
        raise ValueError("RULE_RETRY_SNAKEMAKE_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake_options.get("rerunIncomplete") is not True:
        raise ValueError("RULE_RETRY_RERUN_INCOMPLETE_REQUIRED")
    raw_forcerun_rules = snakemake_options.get("forcerunRules")
    if raw_forcerun_rules is not None and not isinstance(raw_forcerun_rules, list):
        raise ValueError("RULE_RETRY_FORCERUN_RULES_INVALID")
    forcerun_rules = normalize_forcerun_rules(raw_forcerun_rules)
    if not forcerun_rules:
        raise ValueError("RULE_RETRY_FORCERUN_RULES_REQUIRED")
    return {
        "schemaVersion": RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION,
        "snakemake": {
            "schemaVersion": SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION,
            "rerunIncomplete": True,
            "forcerunRules": forcerun_rules,
        },
    }


def _base_plan(
    rule_retry_plan: dict[str, Any],
    *,
    cache_restore_plan: dict[str, Any],
    output_invalidation_plan: dict[str, Any],
) -> dict[str, Any]:
    blocked = _unique_strings(
        [
            *RULE_RETRY_EXECUTION_BLOCKERS,
            *[str(item) for item in rule_retry_plan.get("blockedReasonCodes") or []],
            *[str(item) for item in cache_restore_plan.get("blockedReasonCodes") or []],
            *[str(item) for item in output_invalidation_plan.get("blockedReasonCodes") or []],
        ]
    )
    return {
        "schemaVersion": RULE_RETRY_EXECUTION_PLAN_SCHEMA_VERSION,
        "sourcePlanSchemaVersion": rule_retry_plan.get("schemaVersion"),
        "runId": rule_retry_plan.get("runId"),
        "workflowRevisionId": rule_retry_plan.get("workflowRevisionId"),
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "executionEnabled": False,
        "executionReasonCode": "RULE_RETRY_EXECUTION_DISABLED",
        "commandPreviewAvailable": False,
        "attemptSelection": rule_retry_plan.get("attemptSelection"),
        "cacheAdoptionBoundary": rule_retry_plan.get("cacheAdoptionBoundary"),
        "artifactAdoptionBoundary": rule_retry_plan.get("artifactAdoptionBoundary"),
        "sourceReasonCode": rule_retry_plan.get("reasonCode"),
        "sourceBlockedReasonCodes": list(rule_retry_plan.get("blockedReasonCodes") or []),
        "blockedReasonCodes": blocked,
        "requiresBeforeExecution": RULE_RETRY_EXECUTION_BLOCKERS,
        "selectedRules": [],
        "rerunScope": {"ruleCount": 0, "rules": []},
        "cacheRestorePlan": cache_restore_plan,
        "outputInvalidationPlan": output_invalidation_plan,
        "snakemakeOptions": {
            "schemaVersion": SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION,
            "rerunIncomplete": False,
            "forcerunRules": [],
            "argsPreview": [],
            "unsafeFlagsProhibited": UNSAFE_SNAKEMAKE_RULE_RETRY_FLAGS,
        },
    }


def _blocked(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return attach_plan_hash(
        {
            **base,
            "reasonCode": reason_code,
            "message": f"Rule-level retry execution planning is blocked: {reason_code}.",
        }
    )


def _disabled_reason(rule_retry_execution_plan: dict[str, Any]) -> str:
    blockers = _unique_strings(
        [
            *[str(item) for item in rule_retry_execution_plan.get("blockedReasonCodes") or []],
            *[str(item) for item in rule_retry_execution_plan.get("requiresBeforeExecution") or []],
        ]
    )
    suffix = ",".join(blockers)
    return f"RULE_RETRY_EXECUTION_DISABLED: {suffix}" if suffix else "RULE_RETRY_EXECUTION_DISABLED"


def _attempt_selected(rule: dict[str, Any]) -> bool:
    selection = rule.get("attemptSelection") if isinstance(rule.get("attemptSelection"), dict) else {}
    return selection.get("selected") is True


def _required_rule_name(rule: dict[str, Any]) -> str:
    rule_name = str(rule.get("ruleName") or "").strip()
    if not rule_name:
        raise WorkflowRuntimeCommandError("SNAKEMAKE_FORCERUN_RULE_REQUIRED")
    return rule_name


def _rule_ref(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "selectedAttempt": rule.get("selectedAttempt"),
    }


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = item.strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
