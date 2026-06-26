from __future__ import annotations

from typing import Any

from .artifact_ledger_storage import list_run_artifact_edges
from .config import RemoteRunnerConfig


RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_SCHEMA_VERSION = "rule-partial-rerun-output-closure.v1"


def blocked_rule_partial_rerun_output_closure(
    reason_code: str = "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_UNAVAILABLE",
) -> dict[str, Any]:
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_SCHEMA_VERSION,
        "available": False,
        "edgeClosureReady": False,
        "closureReady": False,
        "reasonCode": reason_code,
        "blockedReasonCodes": [reason_code],
        "scopedOutputCount": 0,
        "adoptedScopedOutputCount": 0,
        "pendingScopedOutputCount": 0,
        "preservedRuleCount": 0,
        "preservedOutputEdgeCount": 0,
        "missingPreservedOutputEdgeCount": 0,
        "unknownActiveOutputEdgeCount": 0,
        "allDeclaredOutputsVerified": False,
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "scopedOutputs": [],
        "preservedOutputs": [],
        "unknownActiveOutputs": [],
    }


def build_rule_partial_rerun_output_closure(
    cfg: RemoteRunnerConfig,
    *,
    run: dict[str, Any],
    rule_retry_plan: dict[str, Any],
    cache_restore_plan: dict[str, Any],
    output_audit: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(run.get("runId") or rule_retry_plan.get("runId") or "").strip()
    if not run_id:
        return blocked_rule_partial_rerun_output_closure("RUN_ID_REQUIRED")
    active_edges = [
        edge
        for edge in list_run_artifact_edges(cfg, run_id)
        if str(edge.get("role") or "") == "output"
    ]
    scoped_outputs = _scoped_outputs(cache_restore_plan, output_audit)
    scoped_keys = {item["outputKey"] for item in scoped_outputs if item["outputKey"]}
    preserved_rules = _rule_items(rule_retry_plan.get("preservedRules"))
    preserved_outputs = _preserved_output_edges(active_edges, preserved_rules, scoped_keys=scoped_keys)
    preserved_edge_ids = {str(item["runArtifactEdgeId"]) for item in preserved_outputs if item["edgePresent"]}
    unknown_active_outputs = [
        _active_edge_ref(edge)
        for edge in active_edges
        if str(edge.get("portName") or "") not in scoped_keys
        and str(edge.get("edgeId") or "") not in preserved_edge_ids
    ]
    adopted_scoped_count = sum(1 for item in scoped_outputs if item["state"] == "adopted")
    pending_scoped_count = max(0, len(scoped_outputs) - adopted_scoped_count)
    missing_preserved_count = sum(1 for item in preserved_outputs if item["edgePresent"] is not True)
    blockers: list[str] = []
    if not scoped_outputs:
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_SCOPE_EMPTY")
    if _safe_int(output_audit.get("unsafeOutputCount")) or _safe_int(output_audit.get("uncheckedOutputCount")):
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_AUDIT_UNSAFE")
    if _safe_int(output_audit.get("unverifiedOutputCount")):
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_AUDIT_UNVERIFIED")
    if pending_scoped_count:
        blockers.append("RULE_PARTIAL_RERUN_SCOPED_OUTPUT_ADOPTION_PENDING")
    if missing_preserved_count:
        blockers.append("RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING")
    if unknown_active_outputs:
        blockers.append("RULE_PARTIAL_RERUN_UNKNOWN_ACTIVE_OUTPUTS")
    edge_closure_ready = not blockers
    all_declared_verified = False
    if edge_closure_ready and not all_declared_verified:
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_CLOSURE_UNPROVEN")
    unique_blockers = _unique_strings(blockers)
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_SCHEMA_VERSION,
        "available": True,
        "edgeClosureReady": edge_closure_ready,
        "closureReady": edge_closure_ready and all_declared_verified,
        "reasonCode": "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_READY" if not unique_blockers else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "scopedOutputCount": len(scoped_outputs),
        "adoptedScopedOutputCount": adopted_scoped_count,
        "pendingScopedOutputCount": pending_scoped_count,
        "preservedRuleCount": len(preserved_rules),
        "preservedOutputEdgeCount": sum(1 for item in preserved_outputs if item["edgePresent"] is True),
        "missingPreservedOutputEdgeCount": missing_preserved_count,
        "unknownActiveOutputEdgeCount": len(unknown_active_outputs),
        "allDeclaredOutputsVerified": all_declared_verified,
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "scopedOutputs": scoped_outputs,
        "preservedOutputs": preserved_outputs,
        "unknownActiveOutputs": unknown_active_outputs,
    }


def _scoped_outputs(cache_restore_plan: dict[str, Any], output_audit: dict[str, Any]) -> list[dict[str, Any]]:
    audit_by_key_hint = _audit_outputs_by_key_hint(output_audit)
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in _rule_items(cache_restore_plan.get("rules")):
        invalidation_role = str(rule.get("invalidationRole") or "").strip()
        for output in _rule_items(rule.get("outputs")):
            output_key = str(output.get("artifactKey") or "").strip()
            if not output_key or output_key in seen:
                continue
            step_id = str(output.get("stepId") or rule.get("stepId") or "").strip()
            output_ordinal = _safe_int(output.get("outputOrdinal"))
            audit = audit_by_key_hint.get(output_key) or audit_by_key_hint.get(f"{step_id}#{output_ordinal}", {})
            outputs.append(
                {
                    "outputKey": output_key,
                    "stepId": step_id,
                    "outputOrdinal": output_ordinal,
                    "invalidationRole": invalidation_role,
                    "cacheHit": output.get("cacheHit") is True,
                    "state": str(audit.get("state") or "pending"),
                    "verificationState": str(audit.get("verificationState") or ""),
                    "rerunRequired": audit.get("rerunRequired") is True,
                    "pathExposed": False,
                    "storageUriExposed": False,
                }
            )
            seen.add(output_key)
    return outputs


def _audit_outputs_by_key_hint(output_audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in _rule_items(output_audit.get("outputs")):
        step_id = str(item.get("stepId") or "").strip()
        output_ordinal = _safe_int(item.get("outputOrdinal"))
        key_hint = str(item.get("outputKey") or item.get("artifactKey") or "").strip()
        if key_hint:
            by_key[key_hint] = item
        elif step_id and output_ordinal:
            by_key[f"{step_id}#{output_ordinal}"] = item
    return by_key


def _preserved_output_edges(
    active_edges: list[dict[str, Any]],
    preserved_rules: list[dict[str, Any]],
    *,
    scoped_keys: set[str],
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for rule in preserved_rules:
        matched = [
            edge
            for edge in active_edges
            if _edge_matches_rule(edge, rule)
            and str(edge.get("portName") or "") not in scoped_keys
        ]
        if not matched:
            outputs.append(
                {
                    **_rule_ref(rule),
                    "edgePresent": False,
                    "runArtifactEdgeId": "",
                    "portName": "",
                    "contentHashPrefix": "",
                    "pathExposed": False,
                    "storageUriExposed": False,
                }
            )
            continue
        outputs.extend({**_rule_ref(rule), **_active_edge_ref(edge), "edgePresent": True} for edge in matched)
    return outputs


def _active_edge_ref(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "runArtifactEdgeId": str(edge.get("edgeId") or ""),
        "portName": str(edge.get("portName") or ""),
        "stepId": str(edge.get("stepId") or ""),
        "contentHashPrefix": str(edge.get("contentHash") or "")[:12],
        "lifecycleState": str(edge.get("lifecycleState") or ""),
        "pathExposed": False,
        "storageUriExposed": False,
    }


def _edge_matches_rule(edge: dict[str, Any], rule: dict[str, Any]) -> bool:
    step_id = str(edge.get("stepId") or "").strip()
    return bool(step_id and step_id in _rule_keys(rule))


def _rule_keys(rule: dict[str, Any]) -> set[str]:
    return {
        key
        for key in (
            str(rule.get("runtimeStatusKey") or "").strip(),
            str(rule.get("stepId") or "").strip(),
            str(rule.get("ruleName") or "").strip(),
        )
        if key
    }


def _rule_ref(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
    }


def _rule_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


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
