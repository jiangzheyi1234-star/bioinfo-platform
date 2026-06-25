from __future__ import annotations

import re
from typing import Any

from .artifact_cache_storage import preview_artifact_cache_entry
from .config import RemoteRunnerConfig
from .rule_execution_storage import fetch_run_rules
from .rule_retry_plan import RULE_RETRY_PLAN_SCHEMA_VERSION


RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION = "rule-cache-restore-plan.v1"
PER_RULE_CACHE_ELIGIBILITY_SCHEMA_VERSION = "per-rule-cache-eligibility.v1"
STAGED_FILE_POLICY_PLAN_SCHEMA_VERSION = "staged-file-policy-plan.v1"
PARTIAL_RESTORE_EXECUTOR_SCHEMA_VERSION = "partial-restore-executor-plan.v1"
PER_RULE_CACHE_RESTORE_BLOCKERS = [
    "PER_RULE_CACHE_ELIGIBILITY_UNPROVEN",
    "OUTPUT_EDGE_INVALIDATION_MUTATION_DISABLED",
    "STAGED_FILE_POLICY_UNREPRESENTED",
    "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE",
]
_SAFE_OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def blocked_rule_cache_restore_plan(
    rule_retry_plan: dict[str, Any],
    reason_code: str = "PER_RULE_CACHE_PREFLIGHT_UNAVAILABLE",
) -> dict[str, Any]:
    return _finalize_plan(
        _base_plan(rule_retry_plan),
        reason_code=reason_code,
        rules=[],
        output_count=0,
        cache_hit_count=0,
    )


def build_rule_cache_restore_plan(
    cfg: RemoteRunnerConfig,
    *,
    run: dict[str, Any],
    rule_retry_plan: dict[str, Any],
) -> dict[str, Any]:
    base = _base_plan(rule_retry_plan)
    if rule_retry_plan.get("schemaVersion") != RULE_RETRY_PLAN_SCHEMA_VERSION:
        return _finalize_plan(base, reason_code="RULE_RETRY_PLAN_SCHEMA_UNSUPPORTED", rules=[])
    if not rule_retry_plan.get("invalidationPlanAvailable"):
        return _finalize_plan(
            base,
            reason_code=str(rule_retry_plan.get("reasonCode") or "RULE_RETRY_INVALIDATION_PLAN_UNAVAILABLE"),
            rules=[],
        )

    workflow_revision_id = str(rule_retry_plan.get("workflowRevisionId") or run.get("workflowRevisionId") or "").strip()
    if not workflow_revision_id:
        return _finalize_plan(base, reason_code="WORKFLOW_REVISION_MISSING", rules=[])

    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    source_rules = _latest_rules(fetch_run_rules(cfg, str(rule_retry_plan.get("runId") or ""))["items"])
    source_by_key = _source_rules_by_key(source_rules)
    planned_rules = []
    output_count = 0
    cache_hit_count = 0
    for rule in [item for item in rule_retry_plan.get("rules") or [] if isinstance(item, dict)]:
        source_rule = source_by_key.get(_rule_identity(rule), rule)
        planned = _rule_restore_plan(
            cfg,
            run_spec=run_spec,
            workflow_revision_id=workflow_revision_id,
            planned_rule=rule,
            source_rule=source_rule,
        )
        planned_rules.append(planned)
        output_count += int(planned["outputCount"])
        cache_hit_count += int(planned["cacheHitCount"])

    return _finalize_plan(
        base,
        reason_code="PER_RULE_CACHE_RESTORE_UNPROVEN",
        rules=planned_rules,
        output_count=output_count,
        cache_hit_count=cache_hit_count,
    )


def _base_plan(rule_retry_plan: dict[str, Any]) -> dict[str, Any]:
    invalidated = [item for item in rule_retry_plan.get("invalidatedRules") or [] if isinstance(item, dict)]
    preserved = [item for item in rule_retry_plan.get("preservedRules") or [] if isinstance(item, dict)]
    selected = [item for item in rule_retry_plan.get("rules") or [] if isinstance(item, dict)]
    return {
        "schemaVersion": RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION,
        "runId": rule_retry_plan.get("runId"),
        "workflowRevisionId": rule_retry_plan.get("workflowRevisionId"),
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "restoreEnabled": False,
        "sideEffectFree": True,
        "pathExposed": False,
        "restoreScope": {
            "selectedRuleCount": len(selected),
            "invalidatedRuleCount": len(invalidated),
            "preservedRuleCount": len(preserved),
            "selectedRules": [_rule_ref(rule) for rule in selected],
            "invalidatedRules": [_rule_ref(rule) for rule in invalidated],
            "preservedRules": [_rule_ref(rule) for rule in preserved],
        },
        "blockedReasonCodes": [
            *PER_RULE_CACHE_RESTORE_BLOCKERS,
            *[str(item) for item in rule_retry_plan.get("blockedReasonCodes") or []],
        ],
        "cacheEligibility": {
            "schemaVersion": PER_RULE_CACHE_ELIGIBILITY_SCHEMA_VERSION,
            "available": False,
            "previewAvailable": False,
            "reasonCode": "PER_RULE_CACHE_ELIGIBILITY_UNPROVEN",
            "requires": [
                "exact_rule_output_to_artifact_key_mapping",
                "verified_cache_key_payload",
                "managed_payload_checksum",
                "selected_and_downstream_output_edges",
            ],
        },
        "stagedFilePolicy": {
            "schemaVersion": STAGED_FILE_POLICY_PLAN_SCHEMA_VERSION,
            "enabled": False,
            "reasonCode": "STAGED_FILE_POLICY_UNREPRESENTED",
            "overwriteAllowed": False,
            "deleteUnknownOutputs": False,
            "pathExposed": False,
            "unknownOutputHandling": "refuse",
            "requires": [
                "managed_work_dir",
                "selected_output_overwrite_plan",
                "downstream_output_tombstone_plan",
                "unknown_output_quarantine_policy",
            ],
        },
        "partialRestoreExecutor": {
            "schemaVersion": PARTIAL_RESTORE_EXECUTOR_SCHEMA_VERSION,
            "available": False,
            "reasonCode": "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE",
            "pinCreationAllowed": False,
            "restoredArtifactCount": 0,
        },
        "rules": [],
    }


def _finalize_plan(
    base: dict[str, Any],
    *,
    reason_code: str,
    rules: list[dict[str, Any]],
    output_count: int = 0,
    cache_hit_count: int = 0,
) -> dict[str, Any]:
    cache_miss_count = max(0, output_count - cache_hit_count)
    return {
        **base,
        "reasonCode": reason_code,
        "message": f"Per-rule cache restore is blocked: {reason_code}.",
        "outputCount": output_count,
        "cacheHitCount": cache_hit_count,
        "cacheMissCount": cache_miss_count,
        "cacheEligibility": {
            **base["cacheEligibility"],
            "previewAvailable": output_count > 0,
            "hitCount": cache_hit_count,
            "missCount": cache_miss_count,
        },
        "rules": rules,
    }


def _rule_restore_plan(
    cfg: RemoteRunnerConfig,
    *,
    run_spec: dict[str, Any],
    workflow_revision_id: str,
    planned_rule: dict[str, Any],
    source_rule: dict[str, Any],
) -> dict[str, Any]:
    outputs = _output_restore_previews(
        cfg,
        run_spec=run_spec,
        workflow_revision_id=workflow_revision_id,
        planned_rule=planned_rule,
        source_rule=source_rule,
    )
    hit_count = sum(1 for output in outputs if output["cacheHit"])
    return {
        **_rule_ref(planned_rule),
        "eligible": False,
        "eligibleNow": False,
        "reasonCode": _rule_reason(outputs),
        "outputCount": len(outputs),
        "cacheHitCount": hit_count,
        "cacheMissCount": max(0, len(outputs) - hit_count),
        "blockedReasonCodes": _rule_blockers(outputs),
        "outputs": outputs,
    }


def _output_restore_previews(
    cfg: RemoteRunnerConfig,
    *,
    run_spec: dict[str, Any],
    workflow_revision_id: str,
    planned_rule: dict[str, Any],
    source_rule: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_outputs = source_rule.get("outputs") if isinstance(source_rule.get("outputs"), list) else []
    outputs: list[dict[str, Any]] = []
    step_id = str(planned_rule.get("stepId") or source_rule.get("stepId") or "").strip()
    for index, raw_output in enumerate(raw_outputs, start=1):
        artifact_key = _safe_artifact_key(raw_output)
        if not artifact_key:
            outputs.append(_unmapped_output(index, step_id))
            continue
        preview = preview_artifact_cache_entry(
            cfg,
            _lookup_payload(
                run_spec,
                workflow_revision_id=workflow_revision_id,
                artifact_key=artifact_key,
                step_id=step_id,
            ),
        )
        outputs.append(_output_preview(index, artifact_key, step_id, preview))
    return outputs


def _output_preview(index: int, artifact_key: str, step_id: str, preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "outputOrdinal": index,
        "artifactKey": artifact_key,
        "stepId": step_id,
        "role": "output",
        "cacheKey": preview.get("cacheKey"),
        "cacheHit": bool(preview.get("hit")),
        "cacheReason": preview.get("reason"),
        "cacheEntry": _safe_cache_entry(preview.get("entry")),
        "restoreTarget": _restore_target_policy("STAGED_FILE_POLICY_UNREPRESENTED"),
        "pinPolicy": _pin_policy(),
        "blockedReasonCodes": _output_blockers(preview),
    }


def _unmapped_output(index: int, step_id: str) -> dict[str, Any]:
    return {
        "outputOrdinal": index,
        "artifactKey": None,
        "stepId": step_id,
        "role": "output",
        "cacheKey": "",
        "cacheHit": False,
        "cacheReason": "rule_output_artifact_key_unmapped",
        "cacheEntry": None,
        "restoreTarget": _restore_target_policy("RULE_OUTPUT_ARTIFACT_KEY_UNMAPPED"),
        "pinPolicy": _pin_policy(),
        "blockedReasonCodes": ["RULE_OUTPUT_ARTIFACT_KEY_UNMAPPED", *PER_RULE_CACHE_RESTORE_BLOCKERS],
    }


def _lookup_payload(
    run_spec: dict[str, Any],
    *,
    workflow_revision_id: str,
    artifact_key: str,
    step_id: str,
) -> dict[str, Any]:
    return {
        "workflowRevisionId": workflow_revision_id,
        "artifactKey": artifact_key,
        "role": "output",
        "stepId": step_id,
        "inputs": run_spec.get("inputs") if "inputs" in run_spec else [],
        "params": run_spec.get("params") if "params" in run_spec else {},
        "resourceBindings": run_spec.get("resourceBindings") if "resourceBindings" in run_spec else {},
        "execution": run_spec.get("execution") if "execution" in run_spec else {},
    }


def _safe_cache_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    return {
        "cacheEntryId": entry.get("cacheEntryId"),
        "artifactId": entry.get("artifactId"),
        "artifactBlobId": entry.get("artifactBlobId"),
        "artifactKey": entry.get("artifactKey"),
        "stepId": entry.get("stepId"),
        "role": entry.get("role"),
        "sizeBytes": entry.get("sizeBytes"),
        "sha256": entry.get("sha256"),
        "lifecycleState": entry.get("lifecycleState"),
    }


def _restore_target_policy(reason_code: str) -> dict[str, Any]:
    return {
        "managedResultsDirRequired": True,
        "overwriteAllowed": False,
        "pathExposed": False,
        "reasonCode": reason_code,
    }


def _pin_policy() -> dict[str, Any]:
    return {
        "pinRequired": True,
        "pinCreated": False,
        "reasonCode": "RESTORE_PIN_NOT_CREATED_IN_READ_MODEL",
    }


def _output_blockers(preview: dict[str, Any]) -> list[str]:
    blockers = list(PER_RULE_CACHE_RESTORE_BLOCKERS)
    if not preview.get("hit"):
        blockers.insert(0, str(preview.get("reason") or "cache_miss").upper())
    return _unique_strings(blockers)


def _rule_reason(outputs: list[dict[str, Any]]) -> str:
    if not outputs:
        return "RULE_OUTPUT_CACHE_KEY_SCOPE_UNPROVEN"
    if any(output.get("artifactKey") is None for output in outputs):
        return "RULE_OUTPUT_ARTIFACT_KEY_UNMAPPED"
    if any(not output.get("cacheHit") for output in outputs):
        return "PER_RULE_CACHE_MISS_OR_UNVERIFIED"
    return "PER_RULE_CACHE_RESTORE_UNPROVEN"


def _rule_blockers(outputs: list[dict[str, Any]]) -> list[str]:
    blockers = ["PER_RULE_CACHE_ELIGIBILITY_UNPROVEN", *PER_RULE_CACHE_RESTORE_BLOCKERS]
    for output in outputs:
        blockers.extend(str(item) for item in output.get("blockedReasonCodes") or [])
    if not outputs:
        blockers.append("RULE_OUTPUT_CACHE_KEY_SCOPE_UNPROVEN")
    return _unique_strings(blockers)


def _safe_artifact_key(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("artifactKey", "key", "name", "as", "port"):
            candidate = str(value.get(key) or "").strip()
            if _safe_key(candidate):
                return candidate
        return ""
    candidate = str(value or "").strip()
    return candidate if _safe_key(candidate) and "/" not in candidate and "\\" not in candidate else ""


def _source_rules_by_key(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_rule_identity(rule): rule for rule in rules}


def _latest_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for rule in rules:
        key = _rule_identity(rule)
        existing = latest.get(key)
        if existing is None or _rule_attempt_sort_key(rule) > _rule_attempt_sort_key(existing):
            latest[key] = rule
    return list(latest.values())


def _rule_attempt_sort_key(rule: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _optional_int(rule.get("attemptNumber")),
        _optional_int(rule.get("leaseGeneration")),
        str(rule.get("updatedAt") or ""),
    )


def _rule_ref(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
    }


def _rule_identity(rule: dict[str, Any]) -> str:
    return (
        str(rule.get("runtimeStatusKey") or "").strip()
        or str(rule.get("stepId") or "").strip()
        or str(rule.get("ruleName") or "").strip()
        or str(rule.get("runRuleId") or id(rule))
    )


def _safe_key(value: str) -> bool:
    return bool(value and _SAFE_OUTPUT_KEY.fullmatch(value))


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = item.strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
