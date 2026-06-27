from __future__ import annotations

from typing import Any


RULE_OUTPUT_INVALIDATION_APPLIED_EVENT_TYPE = "rule.output_invalidation.applied.v1"
RULE_OUTPUT_INVALIDATION_APPLIED_PLAN_SNAPSHOT_SCHEMA_VERSION = (
    "rule-output-invalidation-applied-plan-snapshot.v1"
)


def build_rule_output_invalidation_applied_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": RULE_OUTPUT_INVALIDATION_APPLIED_PLAN_SNAPSHOT_SCHEMA_VERSION,
        "pathExposed": False,
        "storageReferenceExposed": False,
        "outputEdgeSummary": _summary_snapshot(_dict(plan.get("outputEdgeSummary"))),
        "preservedOutputs": _output_ref_snapshots(plan.get("preservedOutputs")),
        "unmatchedOutputs": _output_ref_snapshots(plan.get("unmatchedOutputs")),
    }


def validate_rule_output_invalidation_applied_snapshot(
    snapshot: dict[str, Any],
    *,
    applied_output_edge_count: int,
) -> dict[str, Any]:
    if snapshot.get("schemaVersion") != RULE_OUTPUT_INVALIDATION_APPLIED_PLAN_SNAPSHOT_SCHEMA_VERSION:
        return _unavailable_snapshot("RULE_OUTPUT_INVALIDATION_APPLIED_SNAPSHOT_UNAVAILABLE")
    if snapshot.get("pathExposed") is True or snapshot.get("storageReferenceExposed") is True:
        return _unavailable_snapshot("RULE_OUTPUT_INVALIDATION_APPLIED_SNAPSHOT_REDACTION_UNSAFE")
    summary = snapshot.get("outputEdgeSummary") if isinstance(snapshot.get("outputEdgeSummary"), dict) else {}
    preserved_outputs = _output_ref_snapshots(snapshot.get("preservedOutputs"))
    unmatched_outputs = _output_ref_snapshots(snapshot.get("unmatchedOutputs"))
    invalidated_count = _safe_int(summary.get("invalidatedOutputEdgeCount"))
    if (
        invalidated_count != applied_output_edge_count
        or _safe_int(summary.get("preservedOutputEdgeCount")) != len(preserved_outputs)
        or _safe_int(summary.get("unmatchedOutputEdgeCount")) != len(unmatched_outputs)
        or _safe_int(summary.get("outputEdgeCount"))
        != invalidated_count + len(preserved_outputs) + len(unmatched_outputs)
    ):
        return _unavailable_snapshot("RULE_OUTPUT_INVALIDATION_APPLIED_SNAPSHOT_COUNTS_INCONSISTENT")
    return {
        "available": True,
        "outputEdgeSummary": _summary_snapshot(summary),
        "preservedOutputs": preserved_outputs,
        "unmatchedOutputs": unmatched_outputs,
    }


def _unavailable_snapshot(reason_code: str) -> dict[str, Any]:
    return {"available": False, "reasonCode": reason_code}


def _summary_snapshot(summary: dict[str, Any]) -> dict[str, int | bool]:
    return {
        "outputEdgeCount": _safe_int(summary.get("outputEdgeCount")),
        "invalidatedOutputEdgeCount": _safe_int(summary.get("invalidatedOutputEdgeCount")),
        "selectedOutputEdgeCount": _safe_int(summary.get("selectedOutputEdgeCount")),
        "downstreamOutputEdgeCount": _safe_int(summary.get("downstreamOutputEdgeCount")),
        "preservedOutputEdgeCount": _safe_int(summary.get("preservedOutputEdgeCount")),
        "unmatchedOutputEdgeCount": _safe_int(summary.get("unmatchedOutputEdgeCount")),
        "invalidatedLineageEdgeCount": _safe_int(summary.get("invalidatedLineageEdgeCount")),
        "preservedLineageEdgeCount": _safe_int(summary.get("preservedLineageEdgeCount")),
        "alreadyInvalidatedOutputEdgeCount": _safe_int(summary.get("alreadyInvalidatedOutputEdgeCount")),
        "alreadyInvalidatedLineageEdgeCount": _safe_int(summary.get("alreadyInvalidatedLineageEdgeCount")),
        "payloadDeletionAllowed": summary.get("payloadDeletionAllowed") is True,
        "lineageMutationAllowed": summary.get("lineageMutationAllowed") is True,
    }


def _output_ref_snapshots(value: Any) -> list[dict[str, Any]]:
    return [_output_ref_snapshot(item) for item in value or [] if isinstance(item, dict)]


def _output_ref_snapshot(output: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "rule-output-edge-invalidation.v1",
        "runArtifactEdgeId": output.get("runArtifactEdgeId"),
        "artifactIds": [],
        "artifactBlobId": None,
        "role": "output",
        "portName": output.get("portName"),
        "stepId": output.get("stepId"),
        "contentHashPrefix": output.get("contentHashPrefix"),
        "lifecycleState": output.get("lifecycleState"),
        "invalidatedAt": output.get("invalidatedAt"),
        "invalidationEventId": output.get("invalidationEventId"),
        "wouldTombstoneOutputEdge": output.get("wouldTombstoneOutputEdge") is True,
        "wouldDeletePayload": False,
        "lineageEdgeCount": _safe_int(output.get("lineageEdgeCount")),
        "lineageEdges": [],
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
