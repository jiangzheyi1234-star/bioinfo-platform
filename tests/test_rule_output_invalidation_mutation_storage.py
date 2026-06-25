from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_ledger_storage import (
    list_lineage_edges_for_run,
    list_run_artifact_edges,
    record_artifact_blob_for_path,
    record_lineage_edge,
    record_run_artifact_edge,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.rule_output_invalidation_plan import build_rule_output_invalidation_plan
from apps.remote_runner.rule_output_invalidation_storage import apply_rule_output_invalidation_plan
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_output_invalidation_tombstones_active_edges_without_deleting_payloads(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_apply"
    trim = _output_edge(cfg, tmp_path, run_id=run_id, step_id="trim_reads", port_name="trimmed")
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    report = _output_edge(cfg, tmp_path, run_id=run_id, step_id="report", port_name="html")
    _lineage(cfg, run_id=run_id, edge=trim)
    _lineage(cfg, run_id=run_id, edge=align)
    _lineage(cfg, run_id=run_id, edge=report)
    plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output_apply"},
        rule_retry_plan=_rule_retry_plan(run_id),
    )

    result = apply_rule_output_invalidation_plan(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        actor="operator",
        reason="partial_retry_output_scope",
        now="2099-06-07T10:01:00Z",
    )

    assert plan["invalidationEnabled"] is True
    assert plan["mutationPolicy"]["tombstoneOutputEdges"] is True
    assert plan["mutationPolicy"]["tombstoneLineageEdges"] is True
    assert plan["mutationPolicy"]["deleteArtifactPayloads"] is False
    assert result == {
        "schemaVersion": "rule-output-invalidation-apply-result.v1",
        "runId": run_id,
        "planHash": plan["planHash"],
        "status": "applied",
        "evidenceId": result["evidenceId"],
        "invalidatedOutputEdgeCount": 2,
        "invalidatedLineageEdgeCount": 2,
        "payloadDeleted": False,
        "appliedAt": "2099-06-07T10:01:00Z",
    }
    assert {edge["edgeId"] for edge in list_run_artifact_edges(cfg, run_id)} == {trim["edgeId"]}
    all_edges = list_run_artifact_edges(cfg, run_id, include_inactive=True)
    invalidated_edges = [edge for edge in all_edges if edge["lifecycleState"] == "invalidated"]
    assert {edge["edgeId"] for edge in invalidated_edges} == {align["edgeId"], report["edgeId"]}
    assert all(edge["invalidationEventId"] == result["evidenceId"] for edge in invalidated_edges)
    assert all(edge["invalidationReason"] == "partial_retry_output_scope" for edge in invalidated_edges)

    active_lineage = list_lineage_edges_for_run(cfg, run_id)
    all_lineage = list_lineage_edges_for_run(cfg, run_id, include_inactive=True)
    assert len(active_lineage) == 1
    assert active_lineage[0]["payload"]["runArtifactEdgeId"] == trim["edgeId"]
    assert len([edge for edge in all_lineage if edge["lifecycleState"] == "invalidated"]) == 2

    events = list_evidence_events(cfg, event_type="rule.output_invalidation.applied.v1")
    assert len(events) == 1
    assert events[0]["eventId"] == result["evidenceId"]
    assert events[0]["payload"]["outputEdgeCount"] == 2
    assert events[0]["payload"]["lineageEdgeCount"] == 2
    assert events[0]["payload"]["payloadDeletionAllowed"] is False
    serialized_payload = json.dumps(events[0]["payload"], sort_keys=True)
    assert align["edgeId"] not in serialized_payload
    assert report["edgeId"] not in serialized_payload
    assert "storageUri" not in serialized_payload
    assert str(tmp_path) not in serialized_payload

    applied_plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output_apply"},
        rule_retry_plan=_rule_retry_plan(run_id),
    )
    assert applied_plan["reasonCode"] == "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"
    assert applied_plan["invalidationEnabled"] is False
    assert applied_plan["outputInvalidationState"] == {
        "schemaVersion": "rule-output-invalidation-state.v1",
        "state": "applied",
        "appliedOutputEdgeCount": 2,
        "appliedLineageEdgeCount": 2,
        "evidenceEventCount": 1,
        "latestAppliedAt": "2099-06-07T10:01:00Z",
    }
    assert applied_plan["outputEdgeSummary"]["alreadyInvalidatedOutputEdgeCount"] == 2
    assert applied_plan["outputEdgeSummary"]["alreadyInvalidatedLineageEdgeCount"] == 2
    assert [rule["ruleName"] for rule in applied_plan["rules"]] == ["align", "report"]
    assert {output["lifecycleState"] for rule in applied_plan["rules"] for output in rule["outputs"]} == {"invalidated"}
    assert {output["invalidationEventId"] for rule in applied_plan["rules"] for output in rule["outputs"]} == {
        result["evidenceId"]
    }
    replacement = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    assert {edge["edgeId"] for edge in list_run_artifact_edges(cfg, run_id)} == {
        trim["edgeId"],
        replacement["edgeId"],
    }


def test_rule_output_invalidation_rejects_stale_plan_after_first_apply(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_stale"
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    _lineage(cfg, run_id=run_id, edge=align)
    plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output_apply"},
        rule_retry_plan=_rule_retry_plan(run_id, include_report=False),
    )
    apply_rule_output_invalidation_plan(cfg, plan, plan_hash=plan["planHash"])
    applied_plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output_apply"},
        rule_retry_plan=_rule_retry_plan(run_id, include_report=False),
    )

    with pytest.raises(ValueError, match="RULE_OUTPUT_INVALIDATION_EDGE_SCOPE_STALE"):
        apply_rule_output_invalidation_plan(cfg, plan, plan_hash=plan["planHash"])
    with pytest.raises(ValueError, match="OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"):
        apply_rule_output_invalidation_plan(cfg, applied_plan, plan_hash=applied_plan["planHash"])


def test_rule_output_invalidation_rejects_plan_hash_mismatch_before_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_hash_mismatch"
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    _lineage(cfg, run_id=run_id, edge=align)
    plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output_apply"},
        rule_retry_plan=_rule_retry_plan(run_id, include_report=False),
    )

    with pytest.raises(ValueError, match="RULE_OUTPUT_INVALIDATION_PLAN_HASH_MISMATCH"):
        apply_rule_output_invalidation_plan(cfg, plan, plan_hash="0" * 64)

    assert list_run_artifact_edges(cfg, run_id)[0]["lifecycleState"] == "active"
    assert list_evidence_events(cfg, event_type="rule.output_invalidation.applied.v1") == []


def _output_edge(cfg, tmp_path: Path, *, run_id: str, step_id: str, port_name: str) -> dict[str, Any]:
    path = tmp_path / f"{run_id}-{step_id}-{port_name}.txt"
    path.write_text(f"{step_id}:{port_name}\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(
        cfg,
        path=path,
        media_type="text/plain",
        created_at="2099-06-07T10:00:00Z",
    )
    return record_run_artifact_edge(
        cfg,
        run_id=run_id,
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name=port_name,
        step_id=step_id,
        created_at="2099-06-07T10:00:01Z",
    )


def _lineage(cfg, *, run_id: str, edge: dict[str, Any]) -> None:
    record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id=str(edge["artifactBlobId"]),
        run_id=run_id,
        workflow_revision_id="wfrev_rule_output_apply",
        payload={
            "runArtifactEdgeId": edge["edgeId"],
            "portName": edge["portName"],
            "stepId": edge["stepId"],
        },
        content_hash=str(edge["contentHash"]),
        created_at="2099-06-07T10:00:02Z",
    )


def _rule_retry_plan(run_id: str, *, include_report: bool = True) -> dict[str, Any]:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    align = _rule("align", selected_attempt=selected_attempt, status="failed")
    report = _rule("report", status="blocked")
    trim = _rule("trim_reads", status="succeeded")
    invalidated = [align, report] if include_report else [align]
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": run_id,
        "workflowRevisionId": "wfrev_rule_output_apply",
        "invalidationPlanAvailable": True,
        "rules": [align],
        "invalidatedRules": invalidated,
        "preservedRules": [trim],
        "blockedReasonCodes": ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"],
    }


def _rule(
    rule_name: str,
    *,
    status: str,
    selected_attempt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "runRuleId": f"rr_{rule_name}",
        "ruleName": rule_name,
        "stepId": rule_name,
        "runtimeStatusKey": f"rule:{rule_name}",
        "status": status,
        "attemptId": (selected_attempt or {}).get("attemptId"),
        "leaseGeneration": (selected_attempt or {}).get("leaseGeneration"),
        "attemptNumber": (selected_attempt or {}).get("attemptNumber"),
        **({"selectedAttempt": selected_attempt} if selected_attempt else {}),
    }
