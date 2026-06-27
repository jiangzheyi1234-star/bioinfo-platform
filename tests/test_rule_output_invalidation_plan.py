from __future__ import annotations

from pathlib import Path

from apps.remote_runner.artifact_ledger_storage import (
    record_artifact_blob_for_path,
    record_lineage_edge,
    record_run_artifact_edge,
)
from apps.remote_runner.execution_plan_hash import stable_plan_hash
from apps.remote_runner.rule_output_invalidation_plan import build_rule_output_invalidation_plan
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_output_invalidation_plan_maps_edges_and_lineage_without_paths(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_plan"
    trim = _output_edge(cfg, tmp_path, run_id=run_id, step_id="trim_reads", port_name="trimmed")
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    report = _output_edge(cfg, tmp_path, run_id=run_id, step_id="report", port_name="html")
    orphan = _output_edge(cfg, tmp_path, run_id=run_id, step_id="orphan", port_name="orphan")
    _lineage(cfg, run_id=run_id, edge=align, workflow_revision_id="wfrev_rule_output")
    _lineage(cfg, run_id=run_id, edge=report, workflow_revision_id="wfrev_rule_output")
    _lineage(cfg, run_id=run_id, edge=trim, workflow_revision_id="wfrev_rule_output")

    plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": run_id, "workflowRevisionId": "wfrev_rule_output"},
        rule_retry_plan=_rule_retry_plan(run_id),
    )

    assert plan["schemaVersion"] == "rule-output-invalidation-plan.v1"
    assert plan["planHash"] == stable_plan_hash(plan)
    assert plan["previewAvailable"] is True
    assert plan["supported"] is True
    assert plan["eligible"] is True
    assert plan["eligibleNow"] is True
    assert plan["invalidationEnabled"] is True
    assert plan["sideEffectFree"] is True
    assert plan["pathExposed"] is False
    assert plan["storageReferenceExposed"] is False
    assert plan["reasonCode"] == "OUTPUT_EDGE_INVALIDATION_TOMBSTONE_READY"
    assert plan["mutationPolicy"]["tombstoneOutputEdges"] is True
    assert plan["mutationPolicy"]["tombstoneLineageEdges"] is True
    assert plan["mutationPolicy"]["deleteArtifactPayloads"] is False
    assert plan["blockedReasonCodes"] == ["ARTIFACT_PAYLOAD_DELETION_DISABLED"]
    assert plan["outputEdgeSummary"] == {
        "outputEdgeCount": 4,
        "invalidatedOutputEdgeCount": 2,
        "selectedOutputEdgeCount": 1,
        "downstreamOutputEdgeCount": 1,
        "preservedOutputEdgeCount": 1,
        "unmatchedOutputEdgeCount": 1,
        "invalidatedLineageEdgeCount": 2,
        "preservedLineageEdgeCount": 1,
        "alreadyInvalidatedOutputEdgeCount": 0,
        "alreadyInvalidatedLineageEdgeCount": 0,
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": True,
    }
    assert [rule["ruleName"] for rule in plan["rules"]] == ["align", "report"]
    assert [rule["invalidationRole"] for rule in plan["rules"]] == ["selected_failed_rule", "downstream_rule"]
    assert plan["rules"][0]["outputs"][0]["runArtifactEdgeId"] == align["edgeId"]
    assert plan["rules"][0]["outputs"][0]["portName"] == "bam"
    assert plan["rules"][0]["outputs"][0]["contentHashPrefix"] == align["contentHash"][:12]
    assert plan["rules"][0]["outputs"][0]["wouldDeletePayload"] is False
    assert plan["rules"][0]["outputs"][0]["lineageEdges"][0]["payloadKeys"] == [
        "portName",
        "runArtifactEdgeId",
        "stepId",
    ]
    assert plan["preservedOutputs"][0]["runArtifactEdgeId"] == trim["edgeId"]
    assert plan["unmatchedOutputs"][0]["runArtifactEdgeId"] == orphan["edgeId"]
    assert "storageUri" not in repr(plan)
    assert "localPath" not in repr(plan)
    assert str(tmp_path) not in repr(plan)


def test_rule_output_invalidation_plan_blocks_without_retry_invalidation_plan(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    plan = build_rule_output_invalidation_plan(
        cfg,
        run={"runId": "run_no_retry_plan"},
        rule_retry_plan={
            "schemaVersion": "rule-retry-plan.v1",
            "runId": "run_no_retry_plan",
            "workflowRevisionId": None,
            "invalidationPlanAvailable": False,
            "reasonCode": "WORKFLOW_REVISION_MISSING",
            "rules": [],
            "invalidatedRules": [],
            "preservedRules": [],
        },
    )

    assert plan["previewAvailable"] is False
    assert plan["reasonCode"] == "WORKFLOW_REVISION_MISSING"
    assert plan["outputEdgeSummary"]["outputEdgeCount"] == 0
    assert plan["rules"] == []


def _output_edge(cfg, tmp_path: Path, *, run_id: str, step_id: str, port_name: str) -> dict[str, object]:
    path = tmp_path / f"{step_id}-{port_name}.txt"
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


def _lineage(cfg, *, run_id: str, edge: dict[str, object], workflow_revision_id: str) -> None:
    record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id=str(edge["artifactBlobId"]),
        run_id=run_id,
        workflow_revision_id=workflow_revision_id,
        payload={
            "runArtifactEdgeId": edge["edgeId"],
            "portName": edge["portName"],
            "stepId": edge["stepId"],
        },
        content_hash=str(edge["contentHash"]),
        created_at="2099-06-07T10:00:03Z",
    )


def _rule_retry_plan(run_id: str) -> dict[str, object]:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    align = _rule("align", selected_attempt=selected_attempt, status="failed")
    report = _rule("report", status="blocked")
    trim = _rule("trim_reads", status="succeeded")
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": run_id,
        "workflowRevisionId": "wfrev_rule_output",
        "invalidationPlanAvailable": True,
        "rules": [align],
        "invalidatedRules": [align, report],
        "preservedRules": [trim],
        "blockedReasonCodes": ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"],
    }


def _rule(
    rule_name: str,
    *,
    status: str,
    selected_attempt: dict[str, object] | None = None,
) -> dict[str, object]:
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
