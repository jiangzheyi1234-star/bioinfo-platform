from __future__ import annotations

import re
from typing import Any

from .config import RemoteRunnerConfig
from .execution_plan_hash import stable_plan_hash
from .execution_job_records import run_job_row_to_dict
from .storage_core import get_connection
from .workflow_engine_adapter import WorkflowRuntimeCommandError, normalize_forcerun_rules


RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_SCHEMA_VERSION = "rule-partial-rerun-claim-preflight.v1"
RULE_PARTIAL_RERUN_CLAIM_BINDING_SCHEMA_VERSION = "rule-partial-rerun-claim-binding.v1"
RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION = "run-job-execution-options.v1"
SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION = "snakemake-rule-rerun-options.v1"
RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION = "rule-output-adoption-scope.v1"
READY_REASON = "RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_READY"

_PLAN_HASH = re.compile(r"^[a-f0-9]{64}$")
_SAFE_OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def rule_partial_rerun_execution_options_requested(execution_options: dict[str, Any] | None) -> bool:
    if not isinstance(execution_options, dict):
        return False
    snakemake = _dict_value(execution_options.get("snakemake"))
    scope = _dict_value(execution_options.get("outputAdoptionScope"))
    return (
        snakemake.get("schemaVersion") == SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION
        or scope.get("mode") == "rule-partial-rerun"
    )


def build_rule_partial_rerun_claim_preflight(
    execution_options: dict[str, Any] | None,
    *,
    run_id: str = "",
    attempt_id: str = "",
    lease_generation: int | None = None,
) -> dict[str, Any]:
    options = _dict_value(execution_options)
    snakemake = _dict_value(options.get("snakemake"))
    scope = _dict_value(options.get("outputAdoptionScope"))
    binding = _dict_value(options.get("rulePartialRerunClaimBinding"))
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    output_keys = _output_keys(scope)
    target_output_keys = _output_keys(scope, key_name="targetOutputKeys")
    outputs = _scope_outputs(scope)
    binding_blockers = rule_partial_rerun_claim_binding_blockers(scope, binding)

    blockers: list[str] = []
    blockers.extend(binding_blockers)
    if not rule_partial_rerun_execution_options_requested(options):
        blockers.append("RULE_PARTIAL_RERUN_EXECUTION_OPTIONS_NOT_REQUESTED")
    if options.get("schemaVersion") != RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION:
        blockers.append("RUN_JOB_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake.get("schemaVersion") != SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION:
        blockers.append("SNAKEMAKE_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake.get("rerunIncomplete") is not True:
        blockers.append("RULE_PARTIAL_RERUN_RERUN_INCOMPLETE_REQUIRED")
    try:
        forcerun_rules = normalize_forcerun_rules(snakemake.get("forcerunRules"))
    except WorkflowRuntimeCommandError as exc:
        forcerun_rules = []
        blockers.append(str(exc).split(":", 1)[0] or "SNAKEMAKE_FORCERUN_RULES_INVALID")
    if not forcerun_rules:
        blockers.append("RULE_PARTIAL_RERUN_FORCERUN_RULES_REQUIRED")
    if scope.get("schemaVersion") != RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION:
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_SCHEMA_UNSUPPORTED")
    if scope.get("mode") != "rule-partial-rerun":
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_MODE_UNSUPPORTED")
    if scope.get("pathExposed") is True or scope.get("storageUriExposed") is True:
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REDACTION_UNSAFE")
    if scope.get("finalizeRunOnAdoption") is not False:
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_FINALIZE_FORBIDDEN")
    if not _PLAN_HASH.fullmatch(source_plan_hash):
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED")
    if not output_keys:
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    if any(not _SAFE_OUTPUT_KEY.fullmatch(key) for key in output_keys):
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_KEY_UNSAFE")
    if _safe_int(scope.get("outputCount")) != len(output_keys):
        blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_COUNT_MISMATCH")
    if not target_output_keys:
        blockers.append("RULE_RERUN_TARGET_OUTPUT_KEYS_REQUIRED")
    if any(not _SAFE_OUTPUT_KEY.fullmatch(key) for key in target_output_keys):
        blockers.append("RULE_RERUN_TARGET_OUTPUT_KEY_UNSAFE")
    if set(target_output_keys) != set(output_keys):
        blockers.append("RULE_RERUN_TARGET_OUTPUT_KEYS_MISMATCH")
    if outputs:
        output_key_set = set(output_keys)
        output_entries_by_key = {str(item.get("outputKey") or "").strip(): item for item in outputs}
        if set(output_entries_by_key) != output_key_set:
            blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_OUTPUTS_MISMATCH")
        if any(not str(item.get("stepId") or "").strip() for item in outputs):
            blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_STEP_ID_REQUIRED")
        if any(_safe_int(item.get("outputOrdinal")) <= 0 for item in outputs):
            blockers.append("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_ORDINAL_REQUIRED")
    if not str(run_id or "").strip():
        blockers.append("RUN_ID_REQUIRED")
    if not str(attempt_id or "").strip():
        blockers.append("ATTEMPT_ID_REQUIRED")
    if _safe_int(lease_generation) <= 0:
        blockers.append("LEASE_GENERATION_REQUIRED")

    unique_blockers = _unique_strings(blockers)
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_SCHEMA_VERSION,
        "available": True,
        "mode": "rule-partial-rerun",
        "claimReady": not unique_blockers,
        "reasonCode": READY_REASON if not unique_blockers else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "runIdPresent": bool(str(run_id or "").strip()),
        "attemptIdPresent": bool(str(attempt_id or "").strip()),
        "leaseGenerationPresent": _safe_int(lease_generation) > 0,
        "sourcePlanHash": source_plan_hash,
        "sourcePlanHashPresent": bool(source_plan_hash),
        "claimBindingPresent": bool(binding),
        "sourcePlanHashMatchesBinding": "RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_STALE" not in unique_blockers,
        "outputAdoptionScopePlanHashMatches": "RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE_STALE"
        not in unique_blockers,
        "outputAdoptionScopeReady": not any(
            item.startswith("RULE_RERUN_OUTPUT_ADOPTION_SCOPE") or item.startswith("RULE_RERUN_TARGET_OUTPUT")
            or item.startswith("RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE")
            for item in unique_blockers
        )
        and "RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED" not in unique_blockers
        and "RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_STALE" not in unique_blockers,
        "outputAdoptionScopeOutputCount": len(output_keys),
        "outputKeys": output_keys,
        "targetOutputKeys": target_output_keys,
        "forcerunRuleCount": len(forcerun_rules),
        "rerunIncomplete": snakemake.get("rerunIncomplete") is True,
        "pathExposed": scope.get("pathExposed") is True,
        "storageUriExposed": scope.get("storageUriExposed") is True,
        "finalizeRunOnAdoption": scope.get("finalizeRunOnAdoption") is True,
    }


def validate_rule_partial_rerun_claim_preflight(
    execution_options: dict[str, Any] | None,
    *,
    run_id: str = "",
    attempt_id: str = "",
    lease_generation: int | None = None,
) -> dict[str, Any]:
    preflight = build_rule_partial_rerun_claim_preflight(
        execution_options,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    if preflight.get("claimReady") is not True:
        raise ValueError(str(preflight.get("reasonCode") or "RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_UNPROVEN"))
    return preflight


def build_rule_partial_rerun_claim_binding(output_adoption_scope: dict[str, Any]) -> dict[str, Any]:
    scope = _dict_value(output_adoption_scope)
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_CLAIM_BINDING_SCHEMA_VERSION,
        "mode": "rule-partial-rerun",
        "sourcePlanHash": str(scope.get("sourcePlanHash") or "").strip(),
        "outputAdoptionScopeFingerprint": rule_partial_rerun_output_scope_fingerprint(scope),
        "pathExposed": False,
        "storageUriExposed": False,
    }


def rule_partial_rerun_claim_binding_blockers(
    output_adoption_scope: dict[str, Any],
    claim_binding: dict[str, Any],
) -> list[str]:
    scope = _dict_value(output_adoption_scope)
    binding = _dict_value(claim_binding)
    blockers: list[str] = []
    if not binding:
        return ["RULE_PARTIAL_RERUN_CLAIM_BINDING_REQUIRED"]
    if binding.get("schemaVersion") != RULE_PARTIAL_RERUN_CLAIM_BINDING_SCHEMA_VERSION:
        blockers.append("RULE_PARTIAL_RERUN_CLAIM_BINDING_SCHEMA_UNSUPPORTED")
    if binding.get("mode") != "rule-partial-rerun":
        blockers.append("RULE_PARTIAL_RERUN_CLAIM_BINDING_MODE_UNSUPPORTED")
    if binding.get("pathExposed") is True or binding.get("storageUriExposed") is True:
        blockers.append("RULE_PARTIAL_RERUN_CLAIM_BINDING_REDACTION_UNSAFE")
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    binding_source_hash = str(binding.get("sourcePlanHash") or "").strip()
    if binding_source_hash != source_plan_hash:
        blockers.append("RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_STALE")
    binding_scope_hash = str(binding.get("outputAdoptionScopeFingerprint") or "").strip()
    if not _PLAN_HASH.fullmatch(binding_scope_hash):
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE_FINGERPRINT_REQUIRED")
    elif binding_scope_hash != rule_partial_rerun_output_scope_fingerprint(scope):
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_ADOPTION_SCOPE_STALE")
    return _unique_strings(blockers)


def rule_partial_rerun_output_scope_fingerprint(output_adoption_scope: dict[str, Any]) -> str:
    scope = _dict_value(output_adoption_scope)
    outputs = []
    for item in _scope_outputs(scope):
        outputs.append(
            {
                "outputKey": str(item.get("outputKey") or "").strip(),
                "stepId": str(item.get("stepId") or "").strip(),
                "outputOrdinal": _safe_int(item.get("outputOrdinal")),
                "invalidationRole": str(item.get("invalidationRole") or "").strip(),
                "cacheHit": item.get("cacheHit") is True,
            }
        )
    payload = {
        "schemaVersion": str(scope.get("schemaVersion") or ""),
        "mode": str(scope.get("mode") or ""),
        "sourcePlanHash": str(scope.get("sourcePlanHash") or "").strip(),
        "scopeSource": str(scope.get("scopeSource") or "").strip(),
        "outputCount": _safe_int(scope.get("outputCount")),
        "outputKeys": _output_keys(scope),
        "targetOutputKeys": _output_keys(scope, key_name="targetOutputKeys"),
        "finalizeRunOnAdoption": scope.get("finalizeRunOnAdoption") is True,
        "pathExposed": scope.get("pathExposed") is True,
        "storageUriExposed": scope.get("storageUriExposed") is True,
        "outputs": outputs,
    }
    return stable_plan_hash(payload)


def validate_rule_partial_rerun_claim_state(
    cfg: RemoteRunnerConfig,
    execution_options: dict[str, Any] | None,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    preflight = build_rule_partial_rerun_claim_preflight(
        execution_options,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    blockers = list(preflight.get("blockedReasonCodes") or [])
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        attempt = connection.execute("SELECT * FROM run_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        lease = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()
        if job is None:
            blockers.append("RULE_PARTIAL_RERUN_CLAIM_JOB_NOT_FOUND")
        elif str(job["state"]) != "claimed":
            blockers.append("RULE_PARTIAL_RERUN_CLAIM_JOB_NOT_CLAIMED")
        if attempt is None:
            blockers.append("RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_NOT_FOUND")
        else:
            if str(attempt["run_id"]) != run_id:
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_RUN_MISMATCH")
            if str(attempt["state"]) != "running":
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_NOT_RUNNING")
            if _safe_int(attempt["lease_generation"]) != _safe_int(lease_generation):
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_LEASE_MISMATCH")
            if job is not None and str(attempt["job_id"]) != str(job["job_id"]):
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_JOB_MISMATCH")
        if lease is None:
            blockers.append("RULE_PARTIAL_RERUN_CLAIM_ACTIVE_LEASE_REQUIRED")
        else:
            if str(lease["attempt_id"]) != attempt_id:
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ACTIVE_LEASE_ATTEMPT_MISMATCH")
            if _safe_int(lease["lease_generation"]) != _safe_int(lease_generation):
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ACTIVE_LEASE_GENERATION_MISMATCH")
            if str(lease["state"]) != "active":
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_ACTIVE_LEASE_NOT_ACTIVE")
        if job is not None:
            persisted_options = run_job_row_to_dict(job).get("executionOptions")
            if persisted_options != (execution_options or {}):
                blockers.append("RULE_PARTIAL_RERUN_CLAIM_EXECUTION_OPTIONS_MISMATCH")
    unique_blockers = _unique_strings([str(item) for item in blockers])
    result = {
        **preflight,
        "claimReady": not unique_blockers,
        "reasonCode": READY_REASON if not unique_blockers else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "jobClaimed": "RULE_PARTIAL_RERUN_CLAIM_JOB_NOT_CLAIMED" not in unique_blockers
        and "RULE_PARTIAL_RERUN_CLAIM_JOB_NOT_FOUND" not in unique_blockers,
        "attemptRunning": "RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_NOT_RUNNING" not in unique_blockers
        and "RULE_PARTIAL_RERUN_CLAIM_ATTEMPT_NOT_FOUND" not in unique_blockers,
        "activeLeaseMatchesAttempt": not any(
            item.startswith("RULE_PARTIAL_RERUN_CLAIM_ACTIVE_LEASE") for item in unique_blockers
        ),
        "persistedExecutionOptionsMatch": "RULE_PARTIAL_RERUN_CLAIM_EXECUTION_OPTIONS_MISMATCH"
        not in unique_blockers,
    }
    if result["claimReady"] is not True:
        raise ValueError(str(result.get("reasonCode") or "RULE_PARTIAL_RERUN_CLAIM_PREFLIGHT_UNPROVEN"))
    return result


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _output_keys(scope: dict[str, Any], *, key_name: str = "outputKeys") -> list[str]:
    raw_keys = scope.get(key_name)
    if not isinstance(raw_keys, list):
        return []
    seen: set[str] = set()
    keys: list[str] = []
    for raw_key in raw_keys:
        key = str(raw_key or "").strip()
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _scope_outputs(scope: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in scope.get("outputs") or [] if isinstance(item, dict)]


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
