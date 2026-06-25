from __future__ import annotations

from collections import defaultdict
from typing import Any

from .artifact_ledger_storage import list_lineage_edges_for_run, list_run_artifact_edges
from .config import RemoteRunnerConfig
from .execution_plan_hash import attach_plan_hash
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
    lineage = _lineage_by_output(cfg, run_id)
    artifact_ids = _artifact_ids_by_content_hash(cfg, run_id)
    selected_keys = {_rule_identity(rule) for rule in _rule_items(rule_retry_plan.get("rules"))}
    invalidated_rules = _rule_items(rule_retry_plan.get("invalidatedRules"))
    preserved_rules = _rule_items(rule_retry_plan.get("preservedRules"))
    matched_edge_ids: set[str] = set()
    planned_rules = []
    for rule in invalidated_rules:
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
    return attach_plan_hash(
        {
            **base,
            "previewAvailable": True,
            "reasonCode": "OUTPUT_EDGE_INVALIDATION_PREVIEW_ONLY",
            "message": "Rule output invalidation is represented as a read-only plan; mutation remains disabled.",
            "outputEdgeSummary": summary,
            "rules": planned_rules,
            "preservedOutputs": preserved_outputs,
            "unmatchedOutputs": unmatched_outputs,
        }
    )


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


def _lineage_by_output(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, list[dict[str, Any]]]:
    by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_blob: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in list_lineage_edges_for_run(cfg, run_id):
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        run_artifact_edge_id = str(payload.get("runArtifactEdgeId") or "").strip()
        if run_artifact_edge_id:
            by_edge[run_artifact_edge_id].append(edge)
        object_id = str(edge.get("objectId") or "").strip()
        if object_id:
            by_blob[object_id].append(edge)
    output_edges = _output_edges(cfg, run_id)
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
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": False,
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
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": False,
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
