from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import record_artifact_blob_for_path, record_run_artifact_edge
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.execution_plan_hash import stable_plan_hash
from apps.remote_runner.rule_cache_restore_plan import build_rule_cache_restore_plan
from apps.remote_runner.rule_output_invalidation_plan import build_rule_output_invalidation_plan
from apps.remote_runner.rule_output_invalidation_storage import apply_rule_output_invalidation_plan
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_cache_restore_plan_uses_output_invalidation_edges_without_rule_outputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_cache_restore_source", workflow_revision_id=workflow_revision_id)
    current_run = _create_run(cfg, "run_cache_restore_current", workflow_revision_id=workflow_revision_id)
    align_cache_artifact = persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    report_cache_artifact = persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="html",
        path=_managed_output(cfg, source_run["runId"], "report.html", b"cached report\n"),
        mime_type="text/html",
        artifact_key="html",
        step_id="report",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="report", port_name="html")
    rule_retry_plan = _rule_retry_plan(current_run["runId"], workflow_revision_id)
    output_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )

    plan = build_rule_cache_restore_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
        output_invalidation_plan=output_invalidation_plan,
    )

    assert plan["schemaVersion"] == "rule-cache-restore-plan.v1"
    assert plan["planHash"] == stable_plan_hash(plan)
    assert plan["sideEffectFree"] is True
    assert plan["restoreEnabled"] is False
    assert plan["cacheEligibility"]["outputScopeSource"] == "rule-output-invalidation-plan"
    assert plan["cacheEligibility"]["outputInvalidationPlanHashPresent"] is True
    assert plan["outputCount"] == 2
    assert plan["cacheHitCount"] == 2
    assert plan["cacheMissCount"] == 0
    assert plan["stagedFilePolicy"]["previewAvailable"] is False
    assert plan["stagedFilePolicy"]["reasonCode"] == "STAGED_FILE_POLICY_UNREPRESENTED"
    assert plan["stagedFilePolicy"]["targetCount"] == 2
    assert plan["stagedFilePolicy"]["cacheHitTargetCount"] == 2
    assert plan["stagedFilePolicy"]["pathExposed"] is False
    assert plan["stagedFilePolicy"]["storageUriExposed"] is False
    assert plan["restorePinPolicy"]["previewAvailable"] is False
    assert plan["restorePinPolicy"]["reasonCode"] == "RESTORE_PIN_POLICY_UNREPRESENTED"
    assert plan["restorePinPolicy"]["candidatePinCount"] == 2
    assert plan["restorePinPolicy"]["requiredPinCount"] == 0
    assert plan["restorePinPolicy"]["createdPinCount"] == 0
    assert plan["restorePinPolicy"]["pinCreationAllowed"] is False
    assert plan["restorePinPolicy"]["ownerIdExposed"] is False
    assert plan["restorePinPolicy"]["storageUriExposed"] is False
    assert [rule["ruleName"] for rule in plan["rules"]] == ["align", "report"]
    assert [rule["invalidationRole"] for rule in plan["rules"]] == ["selected_failed_rule", "downstream_rule"]
    assert [output["artifactKey"] for rule in plan["rules"] for output in rule["outputs"]] == ["bam", "html"]
    assert [output["runArtifactEdgeId"] for rule in plan["rules"] for output in rule["outputs"]]
    assert plan["rules"][0]["outputs"][0]["cacheEntry"]["artifactId"] == align_cache_artifact["artifactId"]
    assert plan["rules"][1]["outputs"][0]["cacheEntry"]["artifactId"] == report_cache_artifact["artifactId"]
    serialized = json.dumps(plan, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized
    assert list_evidence_events(cfg, event_type="artifact.cache.lookup.v1") == []
    assert list_artifact_cache_pins(cfg)["items"] == []
    with get_connection(cfg) as connection:
        hit_counts = [
            row["hit_count"]
            for row in connection.execute(
                "SELECT hit_count FROM artifact_cache_entries ORDER BY artifact_key ASC"
            ).fetchall()
        ]
    assert hit_counts == [0, 0]


def test_rule_cache_restore_plan_keeps_applied_invalidation_scope_without_apply_blocker(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_cache_restore_applied_source", workflow_revision_id=workflow_revision_id)
    current_run = _create_run(cfg, "run_cache_restore_applied_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="html",
        path=_managed_output(cfg, source_run["runId"], "report.html", b"cached report\n"),
        mime_type="text/html",
        artifact_key="html",
        step_id="report",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="report", port_name="html")
    rule_retry_plan = _rule_retry_plan(current_run["runId"], workflow_revision_id)
    output_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )
    apply_rule_output_invalidation_plan(
        cfg,
        output_invalidation_plan,
        plan_hash=output_invalidation_plan["planHash"],
        now="2099-06-07T10:01:00Z",
    )
    applied_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )

    plan = build_rule_cache_restore_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
        output_invalidation_plan=applied_invalidation_plan,
    )

    assert applied_invalidation_plan["reasonCode"] == "OUTPUT_EDGE_INVALIDATION_ALREADY_APPLIED"
    assert plan["cacheEligibility"]["outputScopeSource"] == "applied-rule-output-invalidation-plan"
    assert plan["cacheEligibility"]["outputInvalidationApplied"] is True
    assert plan["outputCount"] == 2
    assert plan["cacheHitCount"] == 2
    assert "OUTPUT_EDGE_INVALIDATION_APPLY_REQUIRED" not in plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_UNREPRESENTED" not in plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_EXECUTION_DISABLED" in plan["blockedReasonCodes"]
    assert "PARTIAL_RESTORE_EXECUTOR_UNAVAILABLE" in plan["blockedReasonCodes"]
    assert plan["stagedFilePolicy"]["previewAvailable"] is True
    assert plan["stagedFilePolicy"]["enabled"] is False
    assert plan["stagedFilePolicy"]["reasonCode"] == "STAGED_FILE_POLICY_PREVIEW_ONLY"
    assert plan["stagedFilePolicy"]["blockedReasonCodes"] == ["STAGED_FILE_POLICY_EXECUTION_DISABLED"]
    assert plan["stagedFilePolicy"]["overwriteAllowed"] is False
    assert plan["stagedFilePolicy"]["deleteUnknownOutputs"] is False
    assert plan["stagedFilePolicy"]["pinCreationAllowed"] is False
    assert plan["stagedFilePolicy"]["pathExposed"] is False
    assert plan["stagedFilePolicy"]["storageUriExposed"] is False
    assert plan["stagedFilePolicy"]["cacheKeyExposed"] is False
    assert plan["stagedFilePolicy"]["unknownOutputHandling"] == "refuse"
    assert plan["stagedFilePolicy"]["unknownOutputScanAvailable"] is False
    assert plan["stagedFilePolicy"]["targetCount"] == 2
    assert plan["stagedFilePolicy"]["managedTargetCount"] == 2
    assert plan["stagedFilePolicy"]["selectedOutputCount"] == 1
    assert plan["stagedFilePolicy"]["downstreamOutputCount"] == 1
    assert plan["stagedFilePolicy"]["cacheHitTargetCount"] == 2
    assert plan["stagedFilePolicy"]["cacheMissTargetCount"] == 0
    assert plan["stagedFilePolicy"]["unmappedTargetCount"] == 0
    assert plan["stagedFilePolicy"]["restorePinnedCount"] == 0
    assert plan["restorePinPolicy"]["previewAvailable"] is True
    assert plan["restorePinPolicy"]["creationEnabled"] is False
    assert plan["restorePinPolicy"]["pinCreationAllowed"] is False
    assert plan["restorePinPolicy"]["reasonCode"] == "RESTORE_PIN_POLICY_PREVIEW_ONLY"
    assert plan["restorePinPolicy"]["blockedReasonCodes"] == ["RESTORE_PIN_CREATION_DISABLED"]
    assert plan["restorePinPolicy"]["pinScope"] == "restore"
    assert plan["restorePinPolicy"]["ownerKind"] == "run_attempt"
    assert plan["restorePinPolicy"]["ttlSeconds"] == 3600
    assert plan["restorePinPolicy"]["attemptScoped"] is True
    assert plan["restorePinPolicy"]["ownerIdExposed"] is False
    assert plan["restorePinPolicy"]["cacheKeyExposed"] is False
    assert plan["restorePinPolicy"]["storageUriExposed"] is False
    assert plan["restorePinPolicy"]["pathExposed"] is False
    assert plan["restorePinPolicy"]["targetCount"] == 2
    assert plan["restorePinPolicy"]["candidatePinCount"] == 2
    assert plan["restorePinPolicy"]["requiredPinCount"] == 2
    assert plan["restorePinPolicy"]["eligiblePinCount"] == 2
    assert plan["restorePinPolicy"]["blockedPinCount"] == 0
    assert plan["restorePinPolicy"]["createdPinCount"] == 0
    for rule in plan["rules"]:
        assert "OUTPUT_EDGE_INVALIDATION_APPLY_REQUIRED" not in rule["blockedReasonCodes"]
        assert "STAGED_FILE_POLICY_EXECUTION_DISABLED" in rule["blockedReasonCodes"]
        assert "RESTORE_PIN_CREATION_DISABLED" in rule["blockedReasonCodes"]
        for output in rule["outputs"]:
            assert output["cacheHit"] is True
            assert "OUTPUT_EDGE_INVALIDATION_APPLY_REQUIRED" not in output["blockedReasonCodes"]
            assert "STAGED_FILE_POLICY_EXECUTION_DISABLED" in output["blockedReasonCodes"]
            assert "RESTORE_PIN_CREATION_DISABLED" in output["blockedReasonCodes"]
            assert output["restoreTarget"]["reasonCode"] == "STAGED_FILE_POLICY_PREVIEW_ONLY"
            assert output["restorePinPolicy"]["candidate"] is True
            assert output["restorePinPolicy"]["required"] is True
            assert output["restorePinPolicy"]["eligible"] is True
            assert output["restorePinPolicy"]["created"] is False
            assert output["restorePinPolicy"]["pinCreationAllowed"] is False
            assert output["restorePinPolicy"]["ownerIdExposed"] is False
    serialized = json.dumps(plan, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized
    assert list_artifact_cache_pins(cfg)["items"] == []


def test_rule_cache_restore_plan_staged_policy_counts_mixed_applied_outputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_cache_restore_mixed_source", workflow_revision_id=workflow_revision_id)
    current_run = _create_run(cfg, "run_cache_restore_mixed_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="unsafe/path")
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="report", port_name="html")
    rule_retry_plan = _rule_retry_plan(current_run["runId"], workflow_revision_id)
    output_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )
    apply_rule_output_invalidation_plan(
        cfg,
        output_invalidation_plan,
        plan_hash=output_invalidation_plan["planHash"],
        now="2099-06-07T10:02:00Z",
    )
    applied_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )

    plan = build_rule_cache_restore_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
        output_invalidation_plan=applied_invalidation_plan,
    )

    assert plan["outputCount"] == 3
    assert plan["cacheHitCount"] == 1
    assert plan["cacheMissCount"] == 2
    assert plan["stagedFilePolicy"]["previewAvailable"] is True
    assert plan["stagedFilePolicy"]["targetCount"] == 3
    assert plan["stagedFilePolicy"]["managedTargetCount"] == 3
    assert plan["stagedFilePolicy"]["selectedOutputCount"] == 2
    assert plan["stagedFilePolicy"]["downstreamOutputCount"] == 1
    assert plan["stagedFilePolicy"]["cacheHitTargetCount"] == 1
    assert plan["stagedFilePolicy"]["cacheMissTargetCount"] == 1
    assert plan["stagedFilePolicy"]["unmappedTargetCount"] == 1
    assert plan["stagedFilePolicy"]["unknownOutputCount"] == 0
    assert plan["stagedFilePolicy"]["pathExposed"] is False
    assert plan["stagedFilePolicy"]["storageUriExposed"] is False
    assert plan["stagedFilePolicy"]["cacheKeyExposed"] is False
    assert plan["restorePinPolicy"]["previewAvailable"] is True
    assert plan["restorePinPolicy"]["targetCount"] == 3
    assert plan["restorePinPolicy"]["candidatePinCount"] == 1
    assert plan["restorePinPolicy"]["requiredPinCount"] == 1
    assert plan["restorePinPolicy"]["eligiblePinCount"] == 1
    assert plan["restorePinPolicy"]["blockedPinCount"] == 2
    assert plan["restorePinPolicy"]["createdPinCount"] == 0
    outputs = [output for rule in plan["rules"] for output in rule["outputs"]]
    by_artifact_key = {output["artifactKey"]: output for output in outputs}
    assert by_artifact_key["bam"]["cacheHit"] is True
    assert by_artifact_key["bam"]["restorePinPolicy"]["candidate"] is True
    assert by_artifact_key["bam"]["restorePinPolicy"]["eligible"] is True
    assert by_artifact_key["html"]["cacheHit"] is False
    assert by_artifact_key["html"]["restorePinPolicy"]["candidate"] is False
    assert any(output["cacheReason"] == "rule_output_artifact_key_unmapped" for output in outputs)
    assert any(output["restorePinPolicy"]["reasonCode"] == "RESTORE_PIN_CACHE_HIT_REQUIRED" for output in outputs)
    serialized = json.dumps(plan, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def _create_revision(cfg) -> dict[str, Any]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_rule_cache_restore",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "snake"}]},
        graph_snapshot={"nodes": [{"id": "align"}, {"id": "report"}]},
        runtime_lock={"snakemake": "9.23.1", "python": "3.12"},
        compiler={"name": "h2ometa", "version": "rule-cache-restore-test"},
    )


def _create_run(cfg, run_id: str, *, workflow_revision_id: str) -> dict[str, Any]:
    run_spec = _run_spec(run_id, workflow_revision_id)
    create_run_record(
        cfg,
        server_id="srv_rule_cache_restore",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET status = 'completed', stage = 'complete' WHERE run_id = ?",
            (run_id,),
        )
        connection.execute("UPDATE run_jobs SET state = 'completed' WHERE run_id = ?", (run_id,))
        connection.commit()
    return {"runId": run_id, "workflowRevisionId": workflow_revision_id, "runSpec": run_spec}


def _run_spec(run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    return {
        "runId": run_id,
        "projectId": "proj_rule_cache_restore",
        "pipelineId": "pipeline_rule_cache_restore",
        "pipelineVersion": "0.1.0",
        "workflowRevisionId": workflow_revision_id,
        "inputs": [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _managed_output(cfg, run_id: str, filename: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _output_edge(cfg, tmp_path: Path, *, run_id: str, step_id: str, port_name: str) -> dict[str, Any]:
    safe_port = port_name.replace("/", "_").replace("\\", "_")
    path = tmp_path / f"{run_id}-{step_id}-{safe_port}.txt"
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


def _rule_retry_plan(run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    align = _rule("align", status="failed", selected_attempt=selected_attempt)
    report = _rule("report", status="blocked")
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id,
        "invalidationPlanAvailable": True,
        "rules": [align],
        "invalidatedRules": [align, report],
        "preservedRules": [],
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
