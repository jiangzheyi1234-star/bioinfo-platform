from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.remote_runner import route_utils
from apps.remote_runner.api_models import (
    RunResumeRequest,
    RunRuleCacheRestorePinApplyRequest,
    RunRuleCacheRestorePinPrepareRequest,
    RunRuleCacheRestoreStagedFileApplyRequest,
    RunRuleCacheRestoreStagedFilePrepareRequest,
    RunRuleOutputInvalidationApplyRequest,
    RunRuleRetryRequest,
)
from apps.remote_runner.artifact_ledger_storage import (
    list_lineage_edges_for_run,
    list_run_artifact_edges,
    record_artifact_blob_for_path,
    record_lineage_edge,
    record_run_artifact_edge,
)
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.rule_execution_storage import upsert_run_rule_state
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from apps.remote_runner.workflow_run_storage import update_run_state
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_reexecution_requests_are_strict_and_confirmation_gated() -> None:
    rule_retry = RunRuleRetryRequest.model_validate(
        {"confirmation": "retry-failed-rules", "planHash": "a" * 64, "reason": "operator-reviewed"}
    )
    output_invalidation = RunRuleOutputInvalidationApplyRequest.model_validate(
        {"confirmation": "apply-rule-output-invalidation", "planHash": "c" * 64, "actor": "operator"}
    )
    pin_prepare = RunRuleCacheRestorePinPrepareRequest.model_validate(
        {
            "confirmation": "prepare-rule-cache-restore-pins",
            "planHash": "d" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    pin_apply = RunRuleCacheRestorePinApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-cache-restore-pins",
            "planHash": "e" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    staged_prepare = RunRuleCacheRestoreStagedFilePrepareRequest.model_validate(
        {
            "confirmation": "prepare-rule-cache-restore-staged-files",
            "planHash": "f" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    staged_apply = RunRuleCacheRestoreStagedFileApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-cache-restore-staged-files",
            "planHash": "9" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    resume = RunResumeRequest.model_validate(
        {"confirmation": "resume-run", "planHash": "b" * 64, "actor": "operator"}
    )

    assert rule_retry.planHash == "a" * 64
    assert output_invalidation.planHash == "c" * 64
    assert pin_prepare.attemptId == "att_1"
    assert pin_apply.leaseGeneration == 1
    assert staged_prepare.confirmation == "prepare-rule-cache-restore-staged-files"
    assert staged_apply.confirmation == "apply-rule-cache-restore-staged-files"
    assert resume.planHash == "b" * 64
    with pytest.raises(ValidationError) as wrong_confirmation:
        RunRuleRetryRequest.model_validate({"confirmation": "retry-rule", "planHash": "a" * 64})
    with pytest.raises(ValidationError) as wrong_invalidation_confirmation:
        RunRuleOutputInvalidationApplyRequest.model_validate(
            {"confirmation": "apply-output", "planHash": "c" * 64}
        )
    with pytest.raises(ValidationError) as short_hash:
        RunResumeRequest.model_validate({"confirmation": "resume-run", "planHash": "abc"})
    with pytest.raises(ValidationError) as stale_generation:
        RunRuleCacheRestorePinApplyRequest.model_validate(
            {
                "confirmation": "apply-rule-cache-restore-pins",
                "planHash": "e" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 0,
            }
        )
    with pytest.raises(ValidationError) as staged_extra:
        RunRuleCacheRestoreStagedFileApplyRequest.model_validate(
            {
                "confirmation": "apply-rule-cache-restore-staged-files",
                "planHash": "9" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "targetPath": "leak",
            }
        )
    with pytest.raises(ValidationError) as extra:
        RunRuleOutputInvalidationApplyRequest.model_validate(
            {
                "confirmation": "apply-rule-output-invalidation",
                "planHash": "c" * 64,
                "deleteArtifactPayloads": True,
            }
        )

    assert wrong_confirmation.value.errors()[0]["type"] == "literal_error"
    assert wrong_invalidation_confirmation.value.errors()[0]["type"] == "literal_error"
    assert short_hash.value.errors()[0]["type"] == "string_too_short"
    assert stale_generation.value.errors()[0]["type"] == "greater_than_equal"
    assert staged_extra.value.errors()[0]["type"] == "extra_forbidden"
    assert extra.value.errors()[0]["type"] == "extra_forbidden"


def test_rule_retry_route_records_blocked_intent_without_mutating_run(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    _create_failed_rule_run(cfg, "run_rule_retry_public")
    plan = fetch_run_execution_context(cfg, "run_rule_retry_public")["ruleRetryExecutionPlan"]

    response = TestClient(app).post(
        "/api/v1/runs/run_rule_retry_public/rules/retry",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "retry-failed-rules",
            "planHash": plan["planHash"],
            "actor": "operator",
            "reason": "reviewed failure locator",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RULE_RETRY_EXECUTION_DISABLED"
    assert detail["ruleRetryExecutionPlan"]["planHash"] == plan["planHash"]
    _assert_run_not_requeued(cfg, "run_rule_retry_public")
    events = list_governance_audit_events(cfg, action="run.rule_retry")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["reasonCode"] == "RULE_RETRY_EXECUTION_DISABLED"
    assert events[0]["subjectKind"] == "run_rule_retry"
    assert events[0]["subjectId"] == "run_rule_retry_public"
    assert events[0]["details"] == {
        "planHash": plan["planHash"],
        "executionEnabled": False,
        "commandPreviewAvailable": True,
        "selectedRuleCount": 1,
        "rerunRuleCount": 2,
        "blockedReasonCodes": plan["blockedReasonCodes"],
    }
    serialized = json.dumps(events[0], sort_keys=True)
    assert "executionOptions" not in serialized
    assert "reviewed failure locator" not in serialized
    assert "operator" not in json.dumps(events[0]["details"], sort_keys=True)


def test_rule_output_invalidation_apply_route_tombstones_edges_and_records_safe_audit(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id = "run_rule_output_public_apply"
    workflow_revision_id = _create_failed_rule_run(cfg, run_id)
    trim = _output_edge(cfg, tmp_path, run_id=run_id, step_id="trim_reads", port_name="trimmed")
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    report = _output_edge(cfg, tmp_path, run_id=run_id, step_id="report", port_name="html")
    _lineage(cfg, run_id=run_id, edge=trim, workflow_revision_id=workflow_revision_id)
    _lineage(cfg, run_id=run_id, edge=align, workflow_revision_id=workflow_revision_id)
    _lineage(cfg, run_id=run_id, edge=report, workflow_revision_id=workflow_revision_id)
    plan = fetch_run_execution_context(cfg, run_id)["ruleOutputInvalidationPlan"]

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/output-invalidation/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-output-invalidation",
            "planHash": plan["planHash"],
            "actor": "operator",
            "reason": "reviewed output scope",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["schemaVersion"] == "rule-output-invalidation-apply-result.v1"
    assert result["runId"] == run_id
    assert result["planHash"] == plan["planHash"]
    assert result["status"] == "applied"
    assert result["invalidatedOutputEdgeCount"] == 2
    assert result["invalidatedLineageEdgeCount"] == 2
    assert result["payloadDeleted"] is False
    _assert_run_not_requeued(cfg, run_id)
    assert {edge["edgeId"] for edge in list_run_artifact_edges(cfg, run_id)} == {trim["edgeId"]}
    invalidated_edges = [
        edge
        for edge in list_run_artifact_edges(cfg, run_id, include_inactive=True)
        if edge["lifecycleState"] == "invalidated"
    ]
    assert {edge["edgeId"] for edge in invalidated_edges} == {align["edgeId"], report["edgeId"]}
    assert all(edge["invalidationEventId"] == result["evidenceId"] for edge in invalidated_edges)
    assert len(list_lineage_edges_for_run(cfg, run_id)) == 1
    applied_plan = fetch_run_execution_context(cfg, run_id)["ruleOutputInvalidationPlan"]
    assert applied_plan["invalidationEnabled"] is False
    assert applied_plan["reasonCode"] == "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"
    assert applied_plan["outputInvalidationState"]["state"] == "applied"
    assert applied_plan["outputEdgeSummary"]["alreadyInvalidatedOutputEdgeCount"] == 2

    evidence = list_evidence_events(cfg, event_type="rule.output_invalidation.applied.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    assert evidence["payload"]["outputEdgeCount"] == 2
    assert evidence["payload"]["lineageEdgeCount"] == 2
    assert evidence["payload"]["actorPresent"] is True
    assert evidence["payload"]["payloadDeletionAllowed"] is False
    audit = list_governance_audit_events(cfg, action="run.rule_output_invalidation.apply")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_OUTPUT_INVALIDATION_APPLIED"
    assert audit[0]["subjectKind"] == "run_rule_output_invalidation"
    assert audit[0]["subjectId"] == run_id
    assert audit[0]["details"] == {
        "planHash": plan["planHash"],
        "previewAvailable": True,
        "invalidationEnabled": True,
        "requestReasonProvided": True,
        "invalidatedOutputEdgeCount": 2,
        "invalidatedLineageEdgeCount": 2,
        "payloadDeleted": False,
        "blockedReasonCodes": plan["blockedReasonCodes"],
    }
    serialized = json.dumps({"audit": audit, "evidence": evidence}, sort_keys=True)
    assert align["edgeId"] not in serialized
    assert report["edgeId"] not in serialized
    assert str(tmp_path) not in serialized
    assert "storageUri" not in serialized
    assert "reviewed output scope" not in serialized

    second_response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/output-invalidation/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-output-invalidation",
            "planHash": applied_plan["planHash"],
            "actor": "operator",
        },
    )
    assert second_response.status_code == 409
    second_detail = second_response.json()["detail"]
    assert second_detail["code"] == "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"
    public_plan = second_detail["ruleOutputInvalidationPlan"]
    assert public_plan["outputInvalidationState"] == {
        "state": "applied",
        "appliedOutputEdgeCount": 2,
        "appliedLineageEdgeCount": 2,
        "evidenceEventCount": 1,
        "latestAppliedAtPresent": True,
    }
    assert public_plan["outputEdgeSummary"]["alreadyInvalidatedOutputEdgeCount"] == 2
    assert public_plan["outputEdgeSummary"]["alreadyInvalidatedLineageEdgeCount"] == 2
    second_detail_text = json.dumps(second_detail, sort_keys=True)
    assert align["edgeId"] not in second_detail_text
    assert report["edgeId"] not in second_detail_text
    assert "runArtifactEdgeId" not in second_detail_text
    assert "lineageEdgeId" not in second_detail_text


def test_rule_output_invalidation_apply_route_rejects_stale_plan_hash_before_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id = "run_rule_output_public_stale"
    workflow_revision_id = _create_failed_rule_run(cfg, run_id)
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    _lineage(cfg, run_id=run_id, edge=align, workflow_revision_id=workflow_revision_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/output-invalidation/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "apply-rule-output-invalidation", "planHash": "0" * 64},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RULE_OUTPUT_INVALIDATION_PLAN_HASH_MISMATCH"
    detail_text = json.dumps(response.json()["detail"], sort_keys=True)
    assert align["edgeId"] not in detail_text
    assert align["artifactBlobId"] not in detail_text
    assert "runArtifactEdgeId" not in detail_text
    assert "lineageEdgeId" not in detail_text
    assert str(tmp_path) not in detail_text
    assert list_run_artifact_edges(cfg, run_id)[0]["lifecycleState"] == "active"
    assert list_evidence_events(cfg, event_type="rule.output_invalidation.applied.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_output_invalidation.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["reasonCode"] == "RULE_OUTPUT_INVALIDATION_PLAN_HASH_MISMATCH"


def test_rule_output_invalidation_apply_route_denies_wrong_role_before_read(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("execution context must not be read before authorization")

    monkeypatch.setattr(
        "apps.remote_runner.run_reexecution_service.fetch_run_execution_context",
        fail_context_read,
    )
    response = TestClient(app).post(
        "/api/v1/runs/run_rule_output_denied/rules/output-invalidation/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "apply-rule-output-invalidation", "planHash": "0" * 64},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    audit = list_governance_audit_events(cfg, action="run.rule_output_invalidation.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["subjectKind"] == "run_rule_output_invalidation"
    assert audit[0]["subjectId"] == "authorization"


def test_resume_route_records_blocked_intent_without_mutating_run(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    _create_failed_resumable_run(cfg, "run_resume_public", result_dir=Path(cfg.results_dir) / "results-public")
    plan = fetch_run_execution_context(cfg, "run_resume_public")["resumePlan"]

    response = TestClient(app).post(
        "/api/v1/runs/run_resume_public/resume",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "resume-run", "planHash": plan["planHash"], "actor": "operator"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RUN_RESUME_EXECUTION_DISABLED"
    assert detail["resumePlan"]["planHash"] == plan["planHash"]
    _assert_run_not_requeued(cfg, "run_resume_public")
    events = list_governance_audit_events(cfg, action="run.resume")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["reasonCode"] == "RUN_RESUME_EXECUTION_DISABLED"
    assert events[0]["subjectKind"] == "run_resume"
    assert events[0]["details"] == {
        "planHash": plan["planHash"],
        "executionEnabled": False,
        "commandPreviewAvailable": True,
        "latestAttemptState": "failed",
        "expectedOutputCount": 2,
        "missingOutputCount": 1,
        "unsafeOutputCount": 0,
        "blockedReasonCodes": plan["blockedReasonCodes"],
    }


def test_run_reexecution_routes_reject_stale_plan_hash_before_mutation(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    _create_failed_rule_run(cfg, "run_rule_retry_stale")

    response = TestClient(app).post(
        "/api/v1/runs/run_rule_retry_stale/rules/retry",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "retry-failed-rules", "planHash": "0" * 64},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RUN_REEXECUTION_PLAN_HASH_MISMATCH"
    _assert_run_not_requeued(cfg, "run_rule_retry_stale")
    events = list_governance_audit_events(cfg, action="run.rule_retry")["items"]
    assert events[0]["reasonCode"] == "RUN_REEXECUTION_PLAN_HASH_MISMATCH"


def _create_failed_rule_run(cfg, run_id: str) -> str:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"wfd_{run_id}",
        draft_revision=1,
        manifest={"schemaVersion": "workflow-revision-manifest.v1", "files": []},
        graph_snapshot={
            "schemaVersion": "workflow-graph-snapshot.v1",
            "runSpec": {
                "workflow": {
                    "nodes": [
                        {"id": "trim_reads", "toolRevisionId": "tool_trim"},
                        {"id": "align", "toolRevisionId": "tool_align"},
                        {"id": "report", "toolRevisionId": "tool_report"},
                    ],
                    "edges": [
                        {
                            "from": {"nodeId": "trim_reads", "port": "reads"},
                            "to": {"nodeId": "align", "port": "reads"},
                        },
                        {
                            "from": {"nodeId": "align", "port": "bam"},
                            "to": {"nodeId": "report", "port": "bam"},
                        },
                    ],
                }
            }
        },
        runtime_lock={"schemaVersion": "runtime-lock.v1"},
        compiler={"name": "test", "version": "1"},
    )
    _create_run(cfg, run_id, workflow_revision_id=revision["workflowRevisionId"])
    claim = claim_next_run_job(cfg, worker_id="worker_reexecution", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage="execute",
        message="Attempt failed.",
        request_id=f"req_{run_id}",
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    )
    for rule_name, status in (("trim_reads", "succeeded"), ("align", "failed"), ("report", "blocked")):
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=rule_name,
            runtime_status_key=f"rule:{rule_name}",
            status=status,
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
            attempt_number=int(claim["attempt"]["attemptNumber"]),
        )
    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    return str(revision["workflowRevisionId"])


def _create_failed_resumable_run(cfg, run_id: str, *, result_dir: Path) -> None:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"wfd_{run_id}",
        draft_revision=1,
        manifest={"schemaVersion": "workflow-revision-manifest.v1", "files": []},
        graph_snapshot={"workflow": {"nodes": [{"id": "summarize"}], "edges": []}},
        runtime_lock={"schemaVersion": "runtime-lock.v1"},
        compiler={"name": "test", "version": "1"},
    )
    _create_run(cfg, run_id, workflow_revision_id=revision["workflowRevisionId"])
    claim = claim_next_run_job(cfg, worker_id="worker_resume", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None
    work_dir = Path(str(claim["attempt"]["workDir"]))
    result_dir.mkdir(parents=True, exist_ok=True)
    present = result_dir / "present.txt"
    present.write_text("ok\n", encoding="utf-8")
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage="execute",
        message="Attempt failed.",
        request_id=f"req_{run_id}",
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET result_dir = ?, finished_at = ?, last_updated_at = ? WHERE run_id = ?",
            (str(result_dir), "2099-06-07T10:00:10Z", "2099-06-07T10:00:10Z", run_id),
        )
        connection.commit()


def _create_run(cfg, run_id: str, *, workflow_revision_id: str | None) -> None:
    create_run_record(
        cfg,
        server_id="srv_reexecution",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_reexecution",
            "pipelineId": "pipeline_reexecution",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
            "workflowRevisionId": workflow_revision_id,
            "execution": {"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def _assert_run_not_requeued(cfg, run_id: str) -> None:
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT status, stage FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        job = connection.execute("SELECT state, execution_options_json FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ? AND command_type = 'retry_run'",
            (run_id,),
        ).fetchone()["count"]
        retry_event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND event_type = 'run_retry_requested'",
            (run_id,),
        ).fetchone()["count"]
    assert dict(run) == {"status": "failed", "stage": "execute"}
    assert dict(job) == {"state": "failed", "execution_options_json": "{}"}
    assert command_count == 0
    assert retry_event_count == 0


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


def _lineage(
    cfg,
    *,
    run_id: str,
    edge: dict[str, Any],
    workflow_revision_id: str,
) -> None:
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
        created_at="2099-06-07T10:00:02Z",
    )
