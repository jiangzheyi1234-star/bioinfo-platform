from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .execution_plan_hash import stable_plan_hash
from .rule_output_invalidation_snapshot import (
    RULE_OUTPUT_INVALIDATION_APPLIED_EVENT_TYPE,
    build_rule_output_invalidation_applied_snapshot,
)
from .rule_output_invalidation_plan import (
    RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION,
)
from .storage_core import get_connection, now_iso


RULE_OUTPUT_INVALIDATION_APPLIED_SCHEMA_NAME = "RuleOutputInvalidationApplied"


def apply_rule_output_invalidation_plan(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    actor: str | None = None,
    reason: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    _validate_plan(plan, plan_hash=plan_hash)
    run_id = _required_text(plan.get("runId"), "RULE_OUTPUT_INVALIDATION_RUN_ID_REQUIRED")
    occurred_at = _optional_text(now) or now_iso()
    normalized_reason = _optional_text(reason) or "operator_rule_output_invalidation"
    output_edge_ids = _invalidated_output_edge_ids(plan)
    lineage_edge_ids = _invalidated_lineage_edge_ids(plan)
    if not output_edge_ids:
        raise ValueError("RULE_OUTPUT_INVALIDATION_OUTPUT_EDGE_SCOPE_EMPTY")

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_active_output_edges(connection, run_id=run_id, edge_ids=output_edge_ids)
        _require_active_lineage_edges(connection, run_id=run_id, lineage_edge_ids=lineage_edge_ids)
        evidence = append_evidence_event(
            connection,
            event_type=RULE_OUTPUT_INVALIDATION_APPLIED_EVENT_TYPE,
            schema_name=RULE_OUTPUT_INVALIDATION_APPLIED_SCHEMA_NAME,
            subject_kind="run_rule_output_invalidation",
            subject_id=run_id,
            producer="rule_output_invalidation",
            occurred_at=occurred_at,
            payload={
                "schemaVersion": "rule-output-invalidation-applied.v1",
                "runId": run_id,
                "workflowRevisionId": plan.get("workflowRevisionId"),
                "planHash": plan_hash,
                "actorPresent": bool(_optional_text(actor)),
                "reasonCode": normalized_reason,
                "outputEdgeCount": len(output_edge_ids),
                "lineageEdgeCount": len(lineage_edge_ids),
                "selectedRuleCount": int(_dict(plan.get("scope")).get("selectedRuleCount") or 0),
                "invalidatedRuleCount": int(_dict(plan.get("scope")).get("invalidatedRuleCount") or 0),
                "payloadDeletionAllowed": False,
                "planSnapshot": build_rule_output_invalidation_applied_snapshot(plan),
            },
        )
        _mark_output_edges_invalidated(
            connection,
            edge_ids=output_edge_ids,
            invalidated_at=occurred_at,
            reason=normalized_reason,
            evidence_event_id=evidence["eventId"],
        )
        _mark_lineage_edges_invalidated(
            connection,
            lineage_edge_ids=lineage_edge_ids,
            invalidated_at=occurred_at,
            reason=normalized_reason,
            evidence_event_id=evidence["eventId"],
        )
        connection.commit()

    return {
        "schemaVersion": "rule-output-invalidation-apply-result.v1",
        "runId": run_id,
        "planHash": plan_hash,
        "status": "applied",
        "evidenceId": evidence["eventId"],
        "invalidatedOutputEdgeCount": len(output_edge_ids),
        "invalidatedLineageEdgeCount": len(lineage_edge_ids),
        "payloadDeleted": False,
        "appliedAt": occurred_at,
    }


def _validate_plan(plan: dict[str, Any], *, plan_hash: str) -> None:
    if not isinstance(plan, dict):
        raise ValueError("RULE_OUTPUT_INVALIDATION_PLAN_REQUIRED")
    if plan.get("schemaVersion") != RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_VERSION:
        raise ValueError("RULE_OUTPUT_INVALIDATION_PLAN_SCHEMA_UNSUPPORTED")
    normalized_plan_hash = _required_text(plan_hash, "RULE_OUTPUT_INVALIDATION_PLAN_HASH_REQUIRED")
    if str(plan.get("planHash") or "") != normalized_plan_hash:
        raise ValueError("RULE_OUTPUT_INVALIDATION_PLAN_HASH_MISMATCH")
    if stable_plan_hash(plan) != normalized_plan_hash:
        raise ValueError("RULE_OUTPUT_INVALIDATION_PLAN_HASH_STALE")
    if plan.get("previewAvailable") is not True:
        raise ValueError(str(plan.get("reasonCode") or "RULE_OUTPUT_INVALIDATION_PLAN_UNAVAILABLE"))
    policy = _dict(plan.get("mutationPolicy"))
    if plan.get("invalidationEnabled") is not True:
        raise ValueError(str(plan.get("reasonCode") or "RULE_OUTPUT_INVALIDATION_APPLY_DISABLED"))
    if policy.get("tombstoneOutputEdges") is not True or policy.get("tombstoneLineageEdges") is not True:
        raise ValueError("RULE_OUTPUT_INVALIDATION_MUTATION_DISABLED")
    if policy.get("deleteArtifactPayloads") is not False:
        raise ValueError("RULE_OUTPUT_INVALIDATION_PAYLOAD_DELETE_UNSAFE")
    if plan.get("pathExposed") is True or plan.get("storageReferenceExposed") is True:
        raise ValueError("RULE_OUTPUT_INVALIDATION_REDACTION_UNSAFE")


def _invalidated_output_edge_ids(plan: dict[str, Any]) -> list[str]:
    edge_ids: list[str] = []
    for rule in plan.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            edge_id = _optional_text(output.get("runArtifactEdgeId"))
            if edge_id and edge_id not in edge_ids:
                edge_ids.append(edge_id)
    return edge_ids


def _invalidated_lineage_edge_ids(plan: dict[str, Any]) -> list[str]:
    lineage_ids: list[str] = []
    for rule in plan.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            for lineage in output.get("lineageEdges") or []:
                if not isinstance(lineage, dict):
                    continue
                lineage_id = _optional_text(lineage.get("lineageEdgeId"))
                if lineage_id and lineage_id not in lineage_ids:
                    lineage_ids.append(lineage_id)
    return lineage_ids


def _require_active_output_edges(connection: Any, *, run_id: str, edge_ids: list[str]) -> None:
    placeholders = ",".join("?" for _ in edge_ids)
    rows = connection.execute(
        f"""
        SELECT edge_id
        FROM run_artifact_edges
        WHERE run_id = ?
          AND role = 'output'
          AND lifecycle_state = 'active'
          AND edge_id IN ({placeholders})
        """,
        (run_id, *edge_ids),
    ).fetchall()
    if {str(row["edge_id"]) for row in rows} != set(edge_ids):
        raise ValueError("RULE_OUTPUT_INVALIDATION_EDGE_SCOPE_STALE")


def _require_active_lineage_edges(connection: Any, *, run_id: str, lineage_edge_ids: list[str]) -> None:
    if not lineage_edge_ids:
        return
    placeholders = ",".join("?" for _ in lineage_edge_ids)
    rows = connection.execute(
        f"""
        SELECT lineage_edge_id
        FROM lineage_edges
        WHERE run_id = ?
          AND lifecycle_state = 'active'
          AND lineage_edge_id IN ({placeholders})
        """,
        (run_id, *lineage_edge_ids),
    ).fetchall()
    if {str(row["lineage_edge_id"]) for row in rows} != set(lineage_edge_ids):
        raise ValueError("RULE_OUTPUT_INVALIDATION_LINEAGE_SCOPE_STALE")


def _mark_output_edges_invalidated(
    connection: Any,
    *,
    edge_ids: list[str],
    invalidated_at: str,
    reason: str,
    evidence_event_id: str,
) -> None:
    placeholders = ",".join("?" for _ in edge_ids)
    connection.execute(
        f"""
        UPDATE run_artifact_edges
        SET lifecycle_state = 'invalidated',
            invalidated_at = ?,
            invalidation_reason = ?,
            invalidation_event_id = ?
        WHERE edge_id IN ({placeholders})
        """,
        (invalidated_at, reason, evidence_event_id, *edge_ids),
    )


def _mark_lineage_edges_invalidated(
    connection: Any,
    *,
    lineage_edge_ids: list[str],
    invalidated_at: str,
    reason: str,
    evidence_event_id: str,
) -> None:
    if not lineage_edge_ids:
        return
    placeholders = ",".join("?" for _ in lineage_edge_ids)
    connection.execute(
        f"""
        UPDATE lineage_edges
        SET lifecycle_state = 'invalidated',
            invalidated_at = ?,
            invalidation_reason = ?,
            invalidation_event_id = ?
        WHERE lineage_edge_id IN ({placeholders})
        """,
        (invalidated_at, reason, evidence_event_id, *lineage_edge_ids),
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str:
    return str(value or "").strip()
