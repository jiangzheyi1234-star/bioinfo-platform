from __future__ import annotations

from typing import Any


RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_SCHEMA_VERSION = "rule-partial-rerun-launch-preflight.v1"
RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_READY = "RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_READY"
RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_PREVIEW_ONLY = "RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_PREVIEW_ONLY"
RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION = "rule-output-adoption-scope.v1"

_BROAD_FORCE_FLAGS = {"--forceall", "--touch", "--ignore-incomplete"}
_LAUNCH_MUTATION_BLOCKERS = [
    RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_PREVIEW_ONLY,
    "RULE_PARTIAL_RERUN_PLAN_HASH_REVALIDATION_REQUIRED",
    "RULE_PARTIAL_RERUN_TARGET_ATTEMPT_REQUIRED",
    "RULE_PARTIAL_RERUN_ACTIVE_LEASE_REQUIRED",
    "PARTIAL_RERUN_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY",
    "RULE_RETRY_MUTATION_API_DISABLED",
]


def build_rule_partial_rerun_launch_preflight(
    execution_plan: dict[str, Any],
    *,
    workdir_reuse_policy: dict[str, Any] | None,
    orchestration_contract_ready: bool,
    orchestration_blockers: list[str],
) -> dict[str, Any]:
    cache_restore = _dict_value(execution_plan.get("cacheRestorePlan"))
    snakemake = _dict_value(execution_plan.get("snakemakeOptions"))
    lifecycle = _dict_value(execution_plan.get("partialRerunLifecycle"))
    source_attempt = _dict_value(lifecycle.get("sourceAttempt"))
    target_attempt = _dict_value(lifecycle.get("targetAttempt"))
    output_closure = _dict_value(execution_plan.get("partialRerunOutputClosure"))
    workdir = _dict_value(workdir_reuse_policy)
    adoption_scope = _output_adoption_scope_preview(cache_restore)
    args_preview = [str(item) for item in _list_value(snakemake.get("argsPreview"))]
    unsafe_args = [arg for arg in args_preview if arg in _BROAD_FORCE_FLAGS]

    terminal_source_attempt_ready = (
        source_attempt.get("attemptPresent") is True
        and source_attempt.get("selectedAttemptPresent") is True
        and source_attempt.get("leaseReleased") is True
    )
    workdir_present = workdir.get("directoryPresent") is True
    workdir_managed = workdir.get("managedRoot") is True
    workdir_reusable = workdir.get("workDirReusable") is True
    workdir_ready = workdir_present and workdir_managed and workdir_reusable
    output_closure_ready = output_closure.get("closureReady") is True
    lifecycle_ready = lifecycle.get("contractReady") is True
    active_lease_policy_ready = (
        target_attempt.get("activeLeaseRequiredBeforeMutation") is False
        and target_attempt.get("activeLeaseRequiredDuringExecution") is True
    )
    snakemake_options_ready = (
        execution_plan.get("commandPreviewAvailable") is True
        and snakemake.get("rerunIncomplete") is True
        and bool(_list_value(snakemake.get("forcerunRules")))
        and "--rerun-incomplete" in args_preview
        and "--forcerun" in args_preview
        and not unsafe_args
    )
    path_exposed = (
        bool(_dict_value(cache_restore.get("redactionPolicy")).get("pathsExposed"))
        or _redaction_exposed(lifecycle, "pathExposed")
        or _redaction_exposed(output_closure, "pathExposed")
        or workdir.get("pathExposed") is True
        or adoption_scope.get("pathExposed") is True
    )
    storage_uri_exposed = (
        bool(_dict_value(cache_restore.get("redactionPolicy")).get("storageUrisExposed"))
        or _redaction_exposed(lifecycle, "storageUriExposed")
        or _redaction_exposed(output_closure, "storageUriExposed")
        or adoption_scope.get("storageUriExposed") is True
    )

    blockers: list[str] = []
    if not orchestration_contract_ready:
        blockers.extend(orchestration_blockers or ["RULE_PARTIAL_RERUN_ORCHESTRATION_CONTRACT_UNPROVEN"])
    if not terminal_source_attempt_ready:
        blockers.append("RULE_PARTIAL_RERUN_TERMINAL_SOURCE_ATTEMPT_UNPROVEN")
    if not active_lease_policy_ready:
        blockers.append("RULE_PARTIAL_RERUN_ACTIVE_LEASE_POLICY_UNPROVEN")
    if not workdir_ready:
        blockers.append(_first_nonempty(workdir.get("reasonCode"), "RULE_PARTIAL_RERUN_WORKDIR_UNPROVEN"))
    if not adoption_scope.get("available"):
        blockers.append(_first_nonempty(adoption_scope.get("reasonCode"), "RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE_UNPROVEN"))
    if not snakemake_options_ready:
        blockers.append("SNAKEMAKE_RULE_RERUN_OPTIONS_UNPROVEN")
    if unsafe_args:
        blockers.append("SNAKEMAKE_RULE_RERUN_UNSAFE_FLAGS_PRESENT")
    if not output_closure_ready:
        blockers.append(_first_nonempty(output_closure.get("reasonCode"), "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_UNPROVEN"))
    if not lifecycle_ready:
        blockers.append(_first_nonempty(lifecycle.get("reasonCode"), "RULE_PARTIAL_RERUN_LIFECYCLE_UNPROVEN"))
    if path_exposed or storage_uri_exposed:
        blockers.append("RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_REDACTION_UNSAFE")

    evidence_blockers = _unique_strings(blockers)
    preflight_ready = not evidence_blockers
    blocked_reason_codes = _unique_strings([*evidence_blockers, *_LAUNCH_MUTATION_BLOCKERS])
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_SCHEMA_VERSION,
        "available": True,
        "mode": "operator-preview",
        "preflightReady": preflight_ready,
        "launchReady": False,
        "reasonCode": RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_PREVIEW_ONLY
        if preflight_ready
        else blocked_reason_codes[0],
        "preflightReasonCode": RULE_PARTIAL_RERUN_LAUNCH_PREFLIGHT_READY
        if preflight_ready
        else blocked_reason_codes[0],
        "blockedReasonCodes": blocked_reason_codes,
        "evidenceBlockedReasonCodes": evidence_blockers,
        "orchestrationContractReady": orchestration_contract_ready,
        "terminalSourceAttemptReady": terminal_source_attempt_ready,
        "sourceAttemptIdPresent": bool(str(source_attempt.get("attemptId") or "").strip()),
        "sourceAttemptLeaseGeneration": source_attempt.get("leaseGeneration"),
        "sourcePlanHash": "",
        "sourcePlanHashPresent": False,
        "planHashCurrent": False,
        "planHashMatches": False,
        "executionPlanHashRevalidationRequired": True,
        "sourcePlanHashRevalidationRequired": target_attempt.get("sourcePlanHashRevalidationRequired") is True,
        "outputAdoptionScopeRevalidationRequired": target_attempt.get("outputAdoptionScopeRevalidationRequired") is True,
        "outputAdoptionScopePlanHashMatches": False,
        "targetAttemptRequired": target_attempt.get("targetAttemptRequired") is True,
        "targetAttemptPresent": False,
        "activeLeaseRequired": target_attempt.get("activeLeaseRequiredDuringExecution") is True,
        "activeLeaseRequiredBeforeMutation": target_attempt.get("activeLeaseRequiredBeforeMutation") is True,
        "activeLeaseRequiredDuringExecution": target_attempt.get("activeLeaseRequiredDuringExecution") is True,
        "activeLeasePresent": False,
        "activeLeaseMatchesAttempt": False,
        "activeLeasePolicyReady": active_lease_policy_ready,
        "workDirPresent": workdir_present,
        "workDirManaged": workdir_managed,
        "workDirReusable": workdir_reusable,
        "workdirReady": workdir_ready,
        "outputAdoptionScopeReady": adoption_scope.get("available") is True,
        "outputAdoptionScopeOutputCount": _safe_int(adoption_scope.get("outputCount")),
        "outputAdoptionScope": adoption_scope,
        "snakemakeOptionsReady": snakemake_options_ready,
        "unsafeFlagsAbsent": not unsafe_args,
        "unsafeFlags": unsafe_args,
        "outputClosureReady": output_closure_ready,
        "edgeClosureReady": output_closure.get("edgeClosureReady") is True,
        "lifecycleContractReady": lifecycle_ready,
        "executorStartAllowed": False,
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": path_exposed,
        "storageUriExposed": storage_uri_exposed,
    }


def _output_adoption_scope_preview(cache_restore: dict[str, Any]) -> dict[str, Any]:
    redaction = _dict_value(cache_restore.get("redactionPolicy"))
    if redaction.get("pathsExposed") or redaction.get("storageUrisExposed"):
        return _blocked_output_scope("RULE_RETRY_OUTPUT_ADOPTION_SCOPE_REDACTION_UNSAFE")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in _list_value(cache_restore.get("rules")):
        if not isinstance(rule, dict):
            continue
        invalidation_role = str(rule.get("invalidationRole") or "").strip()
        for output in _list_value(rule.get("outputs")):
            if not isinstance(output, dict):
                continue
            output_key = str(output.get("artifactKey") or "").strip()
            if not output_key:
                return _blocked_output_scope("RULE_RETRY_OUTPUT_ADOPTION_SCOPE_UNMAPPED")
            if output_key in seen:
                continue
            entries.append(
                {
                    "outputKey": output_key,
                    "stepId": str(output.get("stepId") or rule.get("stepId") or "").strip(),
                    "outputOrdinal": _safe_int(output.get("outputOrdinal")),
                    "invalidationRole": invalidation_role,
                    "cacheHit": output.get("cacheHit") is True,
                }
            )
            seen.add(output_key)
    expected_count = _safe_int(cache_restore.get("outputCount"))
    if not entries:
        return _blocked_output_scope("RULE_RETRY_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    if expected_count and len(entries) != expected_count:
        return _blocked_output_scope("RULE_RETRY_OUTPUT_ADOPTION_SCOPE_COUNT_MISMATCH")
    return {
        "schemaVersion": RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION,
        "available": True,
        "reasonCode": "RULE_RETRY_OUTPUT_ADOPTION_SCOPE_READY",
        "mode": "rule-partial-rerun",
        "sourcePlanHash": "",
        "scopeSource": "ruleCacheRestorePlan.outputs",
        "outputCount": len(entries),
        "outputKeys": [entry["outputKey"] for entry in entries],
        "outputs": entries,
        "pathExposed": False,
        "storageUriExposed": False,
    }


def _blocked_output_scope(reason_code: str) -> dict[str, Any]:
    return {
        "schemaVersion": RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION,
        "available": False,
        "reasonCode": reason_code,
        "mode": "rule-partial-rerun",
        "sourcePlanHash": "",
        "scopeSource": "ruleCacheRestorePlan.outputs",
        "outputCount": 0,
        "outputKeys": [],
        "outputs": [],
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
