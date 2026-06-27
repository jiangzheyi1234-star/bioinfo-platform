from __future__ import annotations

from collections import defaultdict
from typing import Any

from .artifact_ledger_storage import list_lineage_edges_for_run, list_run_artifact_edges
from .config import RemoteRunnerConfig
from .evidence_storage import list_evidence_events
from .execution_plan_hash import attach_plan_hash
from .rule_output_invalidation_snapshot import (
    RULE_OUTPUT_INVALIDATION_APPLIED_EVENT_TYPE,
    validate_rule_output_invalidation_applied_snapshot,
)
from .rule_retry_plan import RULE_RETRY_PLAN_SCHEMA_VERSION
from .storage_core import get_connection


RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION = "rule-output-invalidation-plan.v1"
RULE_OUTPUT_INVALIDATION_POLICY_SCHEMA_VERSION = "rule-output-invalidation-policy.v1"
LINEAGE_EDGE_INVALIDATION_SCHEMA_VERSION = "rule-output-lineage-invalidation.v1"
OUTPUT_INVALIDATION_BLOCKERS = [
    "OUTPUT_EDGE_INVALIDATION_MUTATION_DISABLED",
    "LINEAGE_TOMBSTONE_MUTATION_DISABLED",
    "ARTIFACT_PAYLOAD_DELETION_DISABLED",
]


def blocked_rule_output_invalidation_plan(
    rule_retry_plan: dict[str, Any],
    reason_code: str = "RULE_OUTPUT_INVALIDATION_PREFLIGHT_UNAVAILABLE",
) -> dict[str, Any]:
    return attach_plan_hash(
        {
            **_base_plan(rule_retry_plan),
            "previewAvailable": False,
            "reasonCode": reason_code,
            "message": f"Rule output invalidation planning is unavailable: {reason_code}.",
            "outputEdgeSummary": _empty_summary(),
            "rules": [],
            "preservedOutputs": [],
            "unmatchedOutputs": [],
        }
    )


def build_rule_output_invalidation_plan(
    cfg: RemoteRunnerConfig,
    *,
    run: dict[str, Any],
    rule_retry_plan: dict[str, Any],
) -> dict[str, Any]:
    base = _base_plan(rule_retry_plan)
    if rule_retry_plan.get("schemaVersion") != RULE_RETRY_PLAN_SCHEMA_VERSION:
        return _blocked(base, "RULE_RETRY_PLAN_SCHEMA_UNSUPPORTED")
    if not rule_retry_plan.get("invalidationPlanAvailable"):
        return _blocked(
            base,
            str(rule_retry_plan.get("reasonCode") or "RULE_RETRY_INVALIDATION_PLAN_UNAVAILABLE"),
        )
    run_id = str(rule_retry_plan.get("runId") or run.get("runId") or "").strip()
    if not run_id:
        return _blocked(base, "RUN_ID_REQUIRED")

    output_edges = _output_edges(cfg, run_id)
    lineage = _lineage_by_output(cfg, run_id, output_edges=output_edges)
    artifact_ids = _artifact_ids_by_content_hash(cfg, run_id)
    selected_keys = {_rule_identity(rule) for rule in _rule_items(rule_retry_plan.get("rules"))}
    invalidated_rules = _rule_items(rule_retry_plan.get("invalidatedRules"))
    preserved_rules = _rule_items(rule_retry_plan.get("preservedRules"))
    matched_edge_ids: set[str] = set()
    planned_rules = _planned_rule_outputs(
        invalidated_rules,
        output_edges,
        selected_keys=selected_keys,
        lineage=lineage,
        artifact_ids=artifact_ids,
        matched_edge_ids=matched_edge_ids,
    )

    preserved_outputs = []
    for rule in preserved_rules:
        outputs = _matched_outputs(rule, output_edges, lineage=lineage, artifact_ids=artifact_ids)
        matched_edge_ids.update(str(output["runArtifactEdgeId"]) for output in outputs)
        preserved_outputs.extend(outputs)
    unmatched_outputs = [
        _output_summary(edge, lineage=lineage, artifact_ids=artifact_ids)
        for edge in output_edges
        if str(edge["edgeId"]) not in matched_edge_ids
    ]
    summary = _summary(
        output_edges=output_edges,
        rules=planned_rules,
        preserved_outputs=preserved_outputs,
        unmatched_outputs=unmatched_outputs,
    )
    mutation_ready = int(summary["invalidatedOutputEdgeCount"]) > 0
    applied_plan = _already_applied_plan(
        cfg,
        base=base,
        run_id=run_id,
        active_output_edges=output_edges,
        invalidated_rules=invalidated_rules,
        selected_keys=selected_keys,
        artifact_ids=artifact_ids,
    )
    if applied_plan is not None:
        return applied_plan
    return attach_plan_hash(
        {
            **base,
            **({"supported": True, "eligible": True, "eligibleNow": True, "invalidationEnabled": True} if mutation_ready else {}),
            "previewAvailable": True,
            "reasonCode": (
                "OUTPUT_EDGE_INVALIDATION_TOMBSTONE_READY"
                if mutation_ready
                else "OUTPUT_EDGE_INVALIDATION_SCOPE_EMPTY"
            ),
            "message": (
                "Rule output invalidation can tombstone active output and lineage edges without deleting payloads."
                if mutation_ready
                else "Rule output invalidation has no active selected or downstream output edges to tombstone."
            ),
            "mutationPolicy": _mutation_policy_ready() if mutation_ready else base["mutationPolicy"],
            "blockedReasonCodes": ["ARTIFACT_PAYLOAD_DELETION_DISABLED"] if mutation_ready else base["blockedReasonCodes"],
            "outputEdgeSummary": summary,
            "rules": planned_rules,
            "preservedOutputs": preserved_outputs,
            "unmatchedOutputs": unmatched_outputs,
        }
    )


def _already_applied_plan(
    cfg: RemoteRunnerConfig,
    *,
    base: dict[str, Any],
    run_id: str,
    active_output_edges: list[dict[str, Any]],
    invalidated_rules: list[dict[str, Any]],
    selected_keys: set[str],
    artifact_ids: dict[str, list[str]],
) -> dict[str, Any] | None:
    applied_edges = _applied_output_edges(cfg, run_id)
    if not applied_edges:
        return None
    applied_lineage = _lineage_by_output(cfg, run_id, output_edges=applied_edges, include_inactive=True)
    matched_edge_ids: set[str] = set()
    planned_rules = _planned_rule_outputs(
        invalidated_rules,
        applied_edges,
        selected_keys=selected_keys,
        lineage=applied_lineage,
        artifact_ids=artifact_ids,
        matched_edge_ids=matched_edge_ids,
    )
    if not any(rule["outputs"] for rule in planned_rules):
        return None
    applied_state = _applied_state(planned_rules)
    snapshot = _load_applied_plan_snapshot(
        cfg,
        run_id=run_id,
        evidence_ids=_applied_evidence_ids(planned_rules),
        applied_output_edge_count=int(applied_state["appliedOutputEdgeCount"]),
    )
    if snapshot["available"] is not True:
        return _blocked_applied_plan(base, applied_state=applied_state, reason_code=str(snapshot["reasonCode"]))
    preserved_outputs = snapshot["preservedOutputs"]
    unmatched_outputs = snapshot["unmatchedOutputs"]
    summary = {
        **snapshot["outputEdgeSummary"],
        "alreadyInvalidatedOutputEdgeCount": int(applied_state["appliedOutputEdgeCount"]),
        "alreadyInvalidatedLineageEdgeCount": int(applied_state["appliedLineageEdgeCount"]),
    }
    return attach_plan_hash(
        {
            **base,
            "previewAvailable": True,
            "reasonCode": "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED",
            "message": "Rule output invalidation was already applied; the tombstoned output scope is retained for restore planning.",
            "mutationPolicy": {
                **base["mutationPolicy"],
                "reasonCode": "OUTPUT_INVALIDATION_ALREADY_APPLIED",
            },
            "blockedReasonCodes": [
                "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED",
                "ARTIFACT_PAYLOAD_DELETION_DISABLED",
            ],
            "outputInvalidationState": applied_state,
            "outputEdgeSummary": summary,
            "rules": planned_rules,
            "preservedOutputs": preserved_outputs,
            "unmatchedOutputs": unmatched_outputs,
        }
    )


def _blocked_applied_plan(
    base: dict[str, Any],
    *,
    applied_state: dict[str, Any],
    reason_code: str,
) -> dict[str, Any]:
    return attach_plan_hash(
        {
            **base,
            "previewAvailable": False,
            "reasonCode": reason_code,
            "message": f"Applied rule output invalidation snapshot is unavailable: {reason_code}.",
            "mutationPolicy": {
                **base["mutationPolicy"],
                "reasonCode": reason_code,
            },
            "blockedReasonCodes": _unique_strings(
                [
                    reason_code,
                    "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED",
                    "ARTIFACT_PAYLOAD_DELETION_DISABLED",
                ]
            ),
            "outputInvalidationState": applied_state,
            "outputEdgeSummary": {
                **_empty_summary(),
                "alreadyInvalidatedOutputEdgeCount": int(applied_state["appliedOutputEdgeCount"]),
                "alreadyInvalidatedLineageEdgeCount": int(applied_state["appliedLineageEdgeCount"]),
            },
            "rules": [],
            "preservedOutputs": [],
            "unmatchedOutputs": [],
        }
    )


def _load_applied_plan_snapshot(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    evidence_ids: set[str],
    applied_output_edge_count: int,
) -> dict[str, Any]:
    if len(evidence_ids) != 1:
        return _unavailable_snapshot("RULE_OUTPUT_INVALIDATION_APPLIED_EVIDENCE_AMBIGUOUS")
    evidence_id = next(iter(evidence_ids))
    events = list_evidence_events(
        cfg,
        subject_kind="run_rule_output_invalidation",
        subject_id=run_id,
        event_type=RULE_OUTPUT_INVALIDATION_APPLIED_EVENT_TYPE,
        limit=500,
    )
    event = next((item for item in events if str(item.get("eventId") or "") == evidence_id), None)
    if event is None:
        return _unavailable_snapshot("RULE_OUTPUT_INVALIDATION_APPLIED_EVIDENCE_MISSING")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    snapshot = payload.get("planSnapshot") if isinstance(payload.get("planSnapshot"), dict) else {}
    return validate_rule_output_invalidation_applied_snapshot(
        snapshot,
        applied_output_edge_count=applied_output_edge_count,
    )


def _unavailable_snapshot(reason_code: str) -> dict[str, Any]:
    return {"available": False, "reasonCode": reason_code}


def _applied_evidence_ids(planned_rules: list[dict[str, Any]]) -> set[str]:
    return {
        str(output.get("invalidationEventId") or "").strip()
        for rule in planned_rules
        for output in _rule_items(rule.get("outputs"))
        if str(output.get("invalidationEventId") or "").strip()
    }


def _planned_rule_outputs(
    rules: list[dict[str, Any]],
    output_edges: list[dict[str, Any]],
    *,
    selected_keys: set[str],
    lineage: dict[str, list[dict[str, Any]]],
    artifact_ids: dict[str, list[str]],
    matched_edge_ids: set[str],
) -> list[dict[str, Any]]:
    planned_rules = []
    for rule in rules:
        role = "selected_failed_rule" if _rule_identity(rule) in selected_keys else "downstream_rule"
        outputs = _matched_outputs(rule, output_edges, lineage=lineage, artifact_ids=artifact_ids)
        matched_edge_ids.update(str(output["runArtifactEdgeId"]) for output in outputs)
        planned_rules.append(
            {
                **_rule_ref(rule),
                "invalidationRole": role,
                "outputEdgeCount": len(outputs),
                "lineageEdgeCount": sum(int(output["lineageEdgeCount"]) for output in outputs),
                "outputs": outputs,
            }
        )
    return planned_rules


def _base_plan(rule_retry_plan: dict[str, Any]) -> dict[str, Any]:
    invalidated = _rule_items(rule_retry_plan.get("invalidatedRules"))
    preserved = _rule_items(rule_retry_plan.get("preservedRules"))
    selected = _rule_items(rule_retry_plan.get("rules"))
    return {
        "schemaVersion": RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION,
        "runId": rule_retry_plan.get("runId"),
        "workflowRevisionId": rule_retry_plan.get("workflowRevisionId"),
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "invalidationEnabled": False,
        "sideEffectFree": True,
        "pathExposed": False,
        "storageReferenceExposed": False,
        "scope": {
            "selectedRuleCount": len(selected),
            "invalidatedRuleCount": len(invalidated),
            "preservedRuleCount": len(preserved),
            "selectedRules": [_rule_ref(rule) for rule in selected],
            "invalidatedRules": [_rule_ref(rule) for rule in invalidated],
            "preservedRules": [_rule_ref(rule) for rule in preserved],
        },
        "mutationPolicy": {
            "schemaVersion": RULE_OUTPUT_INVALIDATION_POLICY_SCHEMA_VERSION,
            "tombstoneOutputEdges": False,
            "tombstoneLineageEdges": False,
            "deleteArtifactPayloads": False,
            "reasonCode": "OUTPUT_INVALIDATION_MUTATION_DISABLED",
            "requires": [
                "attempt_scoped_output_selection",
                "selected_and_downstream_output_edges",
                "lineage_tombstone_policy",
                "artifact_payload_retention_policy",
            ],
        },
        "blockedReasonCodes": OUTPUT_INVALIDATION_BLOCKERS,
        "outputInvalidationState": {
            "schemaVersion": "rule-output-invalidation-state.v1",
            "state": "pending",
            "appliedOutputEdgeCount": 0,
            "appliedLineageEdgeCount": 0,
            "evidenceEventCount": 0,
            "latestAppliedAt": None,
        },
    }


def _blocked(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return attach_plan_hash(
        {
            **base,
            "previewAvailable": False,
            "reasonCode": reason_code,
            "message": f"Rule output invalidation planning is blocked: {reason_code}.",
            "outputEdgeSummary": _empty_summary(),
            "rules": [],
            "preservedOutputs": [],
            "unmatchedOutputs": [],
        }
    )


def _output_edges(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    return [edge for edge in list_run_artifact_edges(cfg, run_id) if str(edge.get("role") or "") == "output"]


def _applied_output_edges(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    return [
        edge
        for edge in list_run_artifact_edges(cfg, run_id, include_inactive=True)
        if str(edge.get("role") or "") == "output"
        and str(edge.get("lifecycleState") or "") == "invalidated"
        and str(edge.get("invalidationEventId") or "").strip()
    ]


def _artifact_ids_by_content_hash(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, list[str]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT artifact_id, sha256
            FROM artifacts
            WHERE run_id = ?
            ORDER BY artifact_id ASC
            """,
            (run_id,),
        ).fetchall()
    by_hash: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_hash[str(row["sha256"] or "")].append(str(row["artifact_id"]))
    return dict(by_hash)


def _lineage_by_output(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    output_edges: list[dict[str, Any]],
    include_inactive: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_blob: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in list_lineage_edges_for_run(cfg, run_id, include_inactive=include_inactive):
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        run_artifact_edge_id = str(payload.get("runArtifactEdgeId") or "").strip()
        if run_artifact_edge_id:
            by_edge[run_artifact_edge_id].append(edge)
        object_id = str(edge.get("objectId") or "").strip()
        if object_id:
            by_blob[object_id].append(edge)
    result: dict[str, list[dict[str, Any]]] = {}
    for output in output_edges:
        edge_id = str(output.get("edgeId") or "")
        blob_id = str(output.get("artifactBlobId") or "")
        combined = [*by_edge.get(edge_id, []), *by_blob.get(blob_id, [])]
        result[edge_id] = _dedupe_lineage(combined)
    return result


def _matched_outputs(
    rule: dict[str, Any],
    output_edges: list[dict[str, Any]],
    *,
    lineage: dict[str, list[dict[str, Any]]],
    artifact_ids: dict[str, list[str]],
) -> list[dict[str, Any]]:
    return [
        _output_summary(edge, lineage=lineage, artifact_ids=artifact_ids)
        for edge in output_edges
        if _edge_matches_rule(edge, rule)
    ]


def _output_summary(
    edge: dict[str, Any],
    *,
    lineage: dict[str, list[dict[str, Any]]],
    artifact_ids: dict[str, list[str]],
) -> dict[str, Any]:
    edge_id = str(edge.get("edgeId") or "")
    edge_lineage = [_lineage_summary(item) for item in lineage.get(edge_id, [])]
    content_hash = str(edge.get("contentHash") or "")
    return {
        "schemaVersion": "rule-output-edge-invalidation.v1",
        "runArtifactEdgeId": edge_id,
        "artifactIds": artifact_ids.get(content_hash, []),
        "artifactBlobId": edge.get("artifactBlobId"),
        "role": "output",
        "portName": edge.get("portName"),
        "stepId": edge.get("stepId"),
        "contentHashPrefix": content_hash[:12],
        "lifecycleState": edge.get("lifecycleState"),
        "invalidatedAt": edge.get("invalidatedAt"),
        "invalidationEventId": edge.get("invalidationEventId"),
        "wouldTombstoneOutputEdge": True,
        "wouldDeletePayload": False,
        "lineageEdgeCount": len(edge_lineage),
        "lineageEdges": edge_lineage,
    }


def _lineage_summary(edge: dict[str, Any]) -> dict[str, Any]:
    payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
    return {
        "schemaVersion": LINEAGE_EDGE_INVALIDATION_SCHEMA_VERSION,
        "lineageEdgeId": edge.get("lineageEdgeId"),
        "predicate": edge.get("predicate"),
        "objectKind": edge.get("objectKind"),
        "objectId": edge.get("objectId"),
        "evidenceEventId": edge.get("evidenceEventId"),
        "workflowRevisionId": edge.get("workflowRevisionId"),
        "payloadKeys": sorted(str(key) for key in payload),
        "lifecycleState": edge.get("lifecycleState"),
        "invalidatedAt": edge.get("invalidatedAt"),
        "invalidationEventId": edge.get("invalidationEventId"),
        "wouldTombstoneLineageEdge": True,
    }


def _summary(
    *,
    output_edges: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    preserved_outputs: list[dict[str, Any]],
    unmatched_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    invalidated_outputs = [output for rule in rules for output in rule["outputs"]]
    selected_outputs = [
        output
        for rule in rules
        if rule["invalidationRole"] == "selected_failed_rule"
        for output in rule["outputs"]
    ]
    downstream_outputs = [
        output
        for rule in rules
        if rule["invalidationRole"] == "downstream_rule"
        for output in rule["outputs"]
    ]
    return {
        "outputEdgeCount": len(output_edges),
        "invalidatedOutputEdgeCount": len(invalidated_outputs),
        "selectedOutputEdgeCount": len(selected_outputs),
        "downstreamOutputEdgeCount": len(downstream_outputs),
        "preservedOutputEdgeCount": len(preserved_outputs),
        "unmatchedOutputEdgeCount": len(unmatched_outputs),
        "invalidatedLineageEdgeCount": sum(int(output["lineageEdgeCount"]) for output in invalidated_outputs),
        "preservedLineageEdgeCount": sum(int(output["lineageEdgeCount"]) for output in preserved_outputs),
        "alreadyInvalidatedOutputEdgeCount": 0,
        "alreadyInvalidatedLineageEdgeCount": 0,
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": bool(invalidated_outputs),
    }


def _applied_state(planned_rules: list[dict[str, Any]]) -> dict[str, Any]:
    outputs = [output for rule in planned_rules for output in rule["outputs"]]
    evidence_ids = {
        str(output.get("invalidationEventId") or "").strip()
        for output in outputs
        if str(output.get("invalidationEventId") or "").strip()
    }
    applied_at = [
        str(output.get("invalidatedAt") or "").strip()
        for output in outputs
        if str(output.get("invalidatedAt") or "").strip()
    ]
    return {
        "schemaVersion": "rule-output-invalidation-state.v1",
        "state": "applied",
        "appliedOutputEdgeCount": len(outputs),
        "appliedLineageEdgeCount": sum(int(output["lineageEdgeCount"]) for output in outputs),
        "evidenceEventCount": len(evidence_ids),
        "latestAppliedAt": max(applied_at) if applied_at else None,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "outputEdgeCount": 0,
        "invalidatedOutputEdgeCount": 0,
        "selectedOutputEdgeCount": 0,
        "downstreamOutputEdgeCount": 0,
        "preservedOutputEdgeCount": 0,
        "unmatchedOutputEdgeCount": 0,
        "invalidatedLineageEdgeCount": 0,
        "preservedLineageEdgeCount": 0,
        "alreadyInvalidatedOutputEdgeCount": 0,
        "alreadyInvalidatedLineageEdgeCount": 0,
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": False,
    }


def _mutation_policy_ready() -> dict[str, Any]:
    return {
        "schemaVersion": RULE_OUTPUT_INVALIDATION_POLICY_SCHEMA_VERSION,
        "tombstoneOutputEdges": True,
        "tombstoneLineageEdges": True,
        "deleteArtifactPayloads": False,
        "reasonCode": "OUTPUT_INVALIDATION_TOMBSTONE_READY",
        "requires": [
            "current_plan_hash",
            "active_output_edge_scope",
            "active_lineage_scope",
            "artifact_payload_retention_policy",
        ],
    }


def _edge_matches_rule(edge: dict[str, Any], rule: dict[str, Any]) -> bool:
    step_id = str(edge.get("stepId") or "").strip()
    return bool(step_id and step_id in _rule_keys(rule))


def _rule_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _rule_ref(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "status": rule.get("status"),
        "attemptId": rule.get("attemptId"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "attemptNumber": rule.get("attemptNumber"),
    }


def _rule_identity(rule: dict[str, Any]) -> str:
    return (
        str(rule.get("runtimeStatusKey") or "").strip()
        or str(rule.get("stepId") or "").strip()
        or str(rule.get("ruleName") or "").strip()
        or str(rule.get("runRuleId") or "").strip()
    )


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


def _dedupe_lineage(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        key = str(edge.get("lineageEdgeId") or "")
        if key and key not in seen:
            result.append(edge)
            seen.add(key)
    return result


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
