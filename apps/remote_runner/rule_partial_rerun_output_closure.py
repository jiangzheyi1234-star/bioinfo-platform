from __future__ import annotations

from typing import Any

from .rule_output_invalidation_plan import RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION


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
        "declaredOutputBlockedReasonCodes": [],
        "scopedOutputCount": 0,
        "adoptedScopedOutputCount": 0,
        "pendingScopedOutputCount": 0,
        "preservedRuleCount": 0,
        "preservedOutputEdgeCount": 0,
        "missingPreservedOutputEdgeCount": 0,
        "unknownActiveOutputEdgeCount": 0,
        "declaredOutputCount": 0,
        "checkedDeclaredOutputCount": 0,
        "verifiedDeclaredOutputCount": 0,
        "adoptedDeclaredOutputCount": 0,
        "missingDeclaredOutputCount": 0,
        "rerunRequiredDeclaredOutputCount": 0,
        "allDeclaredOutputsVerified": False,
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "scopedOutputs": [],
        "preservedOutputs": [],
        "unknownActiveOutputs": [],
        "declaredOutputs": [],
    }


def build_rule_partial_rerun_output_closure(
    *,
    run: dict[str, Any],
    rule_retry_plan: dict[str, Any],
    cache_restore_plan: dict[str, Any],
    output_invalidation_plan: dict[str, Any],
    output_audit: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(run.get("runId") or rule_retry_plan.get("runId") or "").strip()
    if not run_id:
        return blocked_rule_partial_rerun_output_closure("RUN_ID_REQUIRED")
    scoped_outputs = _scoped_outputs(cache_restore_plan, output_audit)
    scoped_keys = {item["outputKey"] for item in scoped_outputs if item["outputKey"]}
    preserved_rules = _rule_items(rule_retry_plan.get("preservedRules"))
    output_scope = _output_scope_from_invalidation_plan(
        output_invalidation_plan,
        preserved_rules=preserved_rules,
        scoped_keys=scoped_keys,
    )
    preserved_outputs = output_scope["preservedOutputs"]
    unknown_active_outputs = output_scope["unknownActiveOutputs"]
    adopted_scoped_count = sum(1 for item in scoped_outputs if item["state"] == "adopted")
    pending_scoped_count = max(0, len(scoped_outputs) - adopted_scoped_count)
    missing_preserved_count = _safe_int(output_scope["missingPreservedOutputEdgeCount"])
    declared = _declared_output_closure(output_audit)
    blockers: list[str] = [*output_scope["blockedReasonCodes"]]
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
    if edge_closure_ready and not declared["allDeclaredOutputsVerified"]:
        blockers.extend(
            declared["declaredOutputBlockedReasonCodes"]
            or ["RULE_PARTIAL_RERUN_DECLARED_OUTPUT_CLOSURE_UNPROVEN"]
        )
    unique_blockers = _unique_strings(blockers)
    return {
        "schemaVersion": RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_SCHEMA_VERSION,
        "available": True,
        "edgeClosureReady": edge_closure_ready,
        "closureReady": edge_closure_ready and declared["allDeclaredOutputsVerified"],
        "reasonCode": "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_READY" if not unique_blockers else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "scopedOutputCount": len(scoped_outputs),
        "adoptedScopedOutputCount": adopted_scoped_count,
        "pendingScopedOutputCount": pending_scoped_count,
        "preservedRuleCount": len(preserved_rules),
        "preservedOutputEdgeCount": _safe_int(output_scope["preservedOutputEdgeCount"]),
        "missingPreservedOutputEdgeCount": missing_preserved_count,
        "unknownActiveOutputEdgeCount": len(unknown_active_outputs),
        **declared,
        "finalizeAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": output_scope["pathExposed"],
        "storageUriExposed": output_scope["storageUriExposed"],
        "scopedOutputs": scoped_outputs,
        "preservedOutputs": preserved_outputs,
        "unknownActiveOutputs": unknown_active_outputs,
    }


def _output_scope_from_invalidation_plan(
    output_invalidation_plan: dict[str, Any],
    *,
    preserved_rules: list[dict[str, Any]],
    scoped_keys: set[str],
) -> dict[str, Any]:
    plan = output_invalidation_plan if isinstance(output_invalidation_plan, dict) else {}
    summary = plan.get("outputEdgeSummary") if isinstance(plan.get("outputEdgeSummary"), dict) else {}
    raw_preserved = _rule_items(plan.get("preservedOutputs"))
    raw_unmatched = _rule_items(plan.get("unmatchedOutputs"))
    raw_rules = _rule_items(plan.get("rules"))
    invalidated_output_count = sum(len(_rule_items(rule.get("outputs"))) for rule in raw_rules)
    blockers: list[str] = []
    path_exposed = plan.get("pathExposed") is True
    storage_uri_exposed = plan.get("storageReferenceExposed") is True or plan.get("storageUriExposed") is True
    if plan.get("schemaVersion") != RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION:
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_SCHEMA_UNSUPPORTED")
    if plan.get("previewAvailable") is not True:
        blockers.append(
            str(plan.get("reasonCode") or "RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_PLAN_UNAVAILABLE")
        )
    if path_exposed or storage_uri_exposed:
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_REDACTION_UNSAFE")
    if not isinstance(plan.get("outputEdgeSummary"), dict) or (
        _safe_int(summary.get("preservedOutputEdgeCount")) != len(raw_preserved)
        or _safe_int(summary.get("unmatchedOutputEdgeCount")) != len(raw_unmatched)
        or _safe_int(summary.get("invalidatedOutputEdgeCount")) != invalidated_output_count
        or _safe_int(summary.get("outputEdgeCount"))
        != invalidated_output_count + len(raw_preserved) + len(raw_unmatched)
    ):
        blockers.append("RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_COUNTS_INCONSISTENT")
    preserved_outputs: list[dict[str, Any]] = []
    matched_preserved_rule_keys: set[str] = set()
    for item in raw_preserved:
        if str(item.get("portName") or "").strip() in scoped_keys:
            blockers.append("RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_SCOPE_CONFLICT")
        matched_rule = _matching_preserved_rule(item, preserved_rules)
        if matched_rule is None:
            blockers.append("RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_RULE_UNMATCHED")
        else:
            matched_preserved_rule_keys.add(_rule_identity(matched_rule))
        preserved_outputs.append(_preserved_output_ref(item, matched_rule))
    unknown_active_outputs = [
        _invalidation_edge_ref(item)
        for item in raw_unmatched
        if str(item.get("portName") or "").strip() not in scoped_keys
    ]
    required_preserved_rule_keys = {_rule_identity(rule) for rule in preserved_rules if _rule_identity(rule)}
    missing_preserved_count = len(required_preserved_rule_keys - matched_preserved_rule_keys)
    if missing_preserved_count:
        blockers.append("RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING")
    return {
        "blockedReasonCodes": _unique_strings(blockers),
        "preservedOutputEdgeCount": len(preserved_outputs),
        "missingPreservedOutputEdgeCount": missing_preserved_count,
        "unknownActiveOutputs": unknown_active_outputs,
        "preservedOutputs": preserved_outputs,
        "pathExposed": path_exposed,
        "storageUriExposed": storage_uri_exposed,
    }


def _declared_output_closure(output_audit: dict[str, Any]) -> dict[str, Any]:
    outputs = _declared_output_refs(output_audit)
    expected_count = _safe_int(output_audit.get("expectedOutputCount"))
    checked_count = _safe_int(output_audit.get("checkedOutputCount"))
    verified_count = _safe_int(output_audit.get("verifiedOutputCount"))
    adopted_count = _safe_int(output_audit.get("adoptedOutputCount"))
    missing_count = _safe_int(output_audit.get("missingOutputCount"))
    rerun_required_count = _safe_int(output_audit.get("rerunRequiredOutputCount"))
    blockers: list[str] = []
    if output_audit.get("schemaVersion") != "rule-output-audit.v1":
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_SCHEMA_UNSUPPORTED")
    if output_audit.get("available") is not True:
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_UNAVAILABLE")
    if output_audit.get("pathExposed") is True or output_audit.get("storageUriExposed") is True:
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_REDACTION_UNSAFE")
    if expected_count <= 0:
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_SCOPE_EMPTY")
    if expected_count > 0 and (checked_count != expected_count or len(outputs) != expected_count):
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_INCOMPLETE")
    if (
        expected_count > 0
        and (
            verified_count != expected_count
            or _safe_int(output_audit.get("unsafeOutputCount"))
            or _safe_int(output_audit.get("uncheckedOutputCount"))
            or _safe_int(output_audit.get("unverifiedOutputCount"))
            or any(output["verificationState"] != "verified" or output["checksumVerified"] is not True for output in outputs)
        )
    ):
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_VERIFIED")
    if missing_count or rerun_required_count or any(output["rerunRequired"] is True for output in outputs):
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_RERUN_REQUIRED")
    if expected_count > 0 and (adopted_count != expected_count or any(output["state"] != "adopted" for output in outputs)):
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_ADOPTED")
    if expected_count > 0 and any(not output["stepId"] or output["outputOrdinal"] <= 0 for output in outputs):
        blockers.append("RULE_PARTIAL_RERUN_DECLARED_OUTPUT_IDENTITY_UNPROVEN")
    unique_blockers = _unique_strings(blockers)
    return {
        "declaredOutputCount": expected_count,
        "checkedDeclaredOutputCount": checked_count,
        "verifiedDeclaredOutputCount": verified_count,
        "adoptedDeclaredOutputCount": adopted_count,
        "missingDeclaredOutputCount": missing_count,
        "rerunRequiredDeclaredOutputCount": rerun_required_count,
        "allDeclaredOutputsVerified": not unique_blockers,
        "declaredOutputAuditReasonCode": str(output_audit.get("reasonCode") or ""),
        "declaredOutputBlockedReasonCodes": unique_blockers,
        "declaredOutputs": outputs,
    }


def _declared_output_refs(output_audit: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for item in _rule_items(output_audit.get("outputs")):
        outputs.append(
            {
                "stepId": str(item.get("stepId") or "").strip(),
                "outputOrdinal": _safe_int(item.get("outputOrdinal")),
                "invalidationRole": str(item.get("invalidationRole") or "").strip(),
                "state": str(item.get("state") or "").strip(),
                "verificationState": str(item.get("verificationState") or "").strip(),
                "rerunRequired": item.get("rerunRequired") is True,
                "checksumVerified": item.get("checksumVerified") is True,
                "pathExposed": False,
                "storageUriExposed": False,
            }
        )
    return outputs


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


def _matching_preserved_rule(output: dict[str, Any], preserved_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    step_id = str(output.get("stepId") or "").strip()
    for rule in preserved_rules:
        if step_id in _rule_keys(rule):
            return rule
    return None


def _preserved_output_ref(output: dict[str, Any], preserved_rule: dict[str, Any] | None) -> dict[str, Any]:
    rule_ref = _rule_ref(preserved_rule) if preserved_rule is not None else _empty_rule_ref()
    return {**rule_ref, **_invalidation_edge_ref(output), "edgePresent": True}


def _invalidation_edge_ref(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "runArtifactEdgeId": str(edge.get("runArtifactEdgeId") or edge.get("edgeId") or ""),
        "portName": str(edge.get("portName") or ""),
        "stepId": str(edge.get("stepId") or ""),
        "contentHashPrefix": str(edge.get("contentHashPrefix") or edge.get("contentHash") or "")[:12],
        "lifecycleState": str(edge.get("lifecycleState") or ""),
        "pathExposed": False,
        "storageUriExposed": False,
    }


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


def _rule_identity(rule: dict[str, Any]) -> str:
    return (
        str(rule.get("runtimeStatusKey") or "").strip()
        or str(rule.get("stepId") or "").strip()
        or str(rule.get("ruleName") or "").strip()
        or str(rule.get("runRuleId") or "").strip()
    )


def _empty_rule_ref() -> dict[str, Any]:
    return {
        "runRuleId": None,
        "ruleName": None,
        "stepId": "",
        "runtimeStatusKey": None,
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
