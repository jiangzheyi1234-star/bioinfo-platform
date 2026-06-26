from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import record_artifact_blob_for_path, record_run_artifact_edge
from apps.remote_runner.execution_plan_hash import stable_plan_hash
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.rule_execution_storage import upsert_run_rule_state
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str, *, execution: dict | None = None, workflow_revision_id: str | None = None) -> dict:
    spec = {
        "runId": run_id,
        "projectId": "proj_execution_context",
        "pipelineId": "pipeline_execution_context",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }
    if execution:
        spec["execution"] = execution
    if workflow_revision_id:
        spec["workflowRevisionId"] = workflow_revision_id
    return spec


def _create_run(
    cfg,
    run_id: str,
    *,
    execution: dict | None = None,
    workflow_revision_id: str | None = None,
):
    return create_run_record(
        cfg,
        server_id="srv_execution_context",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id, execution=execution, workflow_revision_id=workflow_revision_id),
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def _managed_report(cfg, run_id: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / "report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_run_execution_context_projects_attempts_and_active_lease(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_execution_context",
        execution={"retryPolicy": {"maxAttempts": 4, "backoffSeconds": 17}},
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_context",
        slot_id="slot-context",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None

    context = fetch_run_execution_context(cfg, "run_execution_context")

    assert context["schemaVersion"] == "run-execution-context.v1"
    assert context["runId"] == "run_execution_context"
    assert context["resumeSupported"] is False
    assert context["resumeEligibility"]["reasonCode"] == "ACTIVE_LEASE"
    assert context["resumePlan"]["commandPreviewAvailable"] is False
    assert context["resumePlan"]["snakemakeOptions"]["argsPreview"] == []
    assert context["job"]["attemptCount"] == 1
    assert context["job"]["maxAttempts"] == 4
    assert context["job"]["executionOptions"] == {}
    assert context["retryPolicy"]["backoffSeconds"] == 17
    assert context["activeLease"]["attemptId"] == claim["attemptId"]
    assert context["activeLease"]["leaseGeneration"] == 1
    assert context["retryEligibility"]["reasonCode"] == "ACTIVE_LEASE"
    assert context["retryEligibility"]["remainingAttempts"] == 3
    assert context["attempts"][0]["attemptNumber"] == 1
    assert context["attempts"][0]["workerId"] == "worker_context"
    assert "workDir" not in context["attempts"][0]
    assert "processPid" not in context["attempts"][0]
    assert "processGroupId" not in context["attempts"][0]


def test_run_execution_context_reports_retry_backoff_without_mutation(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_retry_backoff", execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 60}})
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'queued', attempt_count = 1, available_at = ?
            WHERE run_id = ?
            """,
            ("2999-06-07T10:00:00Z", "run_retry_backoff"),
        )
        connection.commit()

    context = fetch_run_execution_context(cfg, "run_retry_backoff")

    assert context["retryEligibility"] == {
        "eligible": True,
        "eligibleNow": False,
        "remainingAttempts": 2,
        "nextAttemptAt": "2999-06-07T10:00:00Z",
        "reasonCode": "RETRY_BACKOFF",
    }
    assert context["job"]["attemptCount"] == 1


def test_run_execution_context_reports_terminal_failed_run_retryable(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_retryable_failed", execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}})
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET status = 'failed', stage = 'execute', state_version = 2 WHERE run_id = ?",
            ("run_retryable_failed",),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'failed', attempt_count = 1 WHERE run_id = ?",
            ("run_retryable_failed",),
        )
        connection.commit()

    context = fetch_run_execution_context(cfg, "run_retryable_failed")

    assert context["retryEligibility"] == {
        "eligible": True,
        "eligibleNow": True,
        "remainingAttempts": 2,
        "nextAttemptAt": context["job"]["availableAt"],
        "reasonCode": "RUN_RETRYABLE_TERMINAL",
    }


def test_run_execution_context_previews_snakemake_resume_without_enabling_execution(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_workflow_revision(
        cfg,
        {
            "schemaVersion": "workflow-graph-snapshot.v1",
            "nodes": [{"id": "summarize", "kind": "rule"}],
            "edges": [],
        },
    )
    _create_run(
        cfg,
        "run_resume_failed",
        execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
        workflow_revision_id=revision["workflowRevisionId"],
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_resume",
        slot_id="slot-resume",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    work_dir = Path(str(claim["attempt"]["workDir"]))
    result_dir = Path(cfg.results_dir) / "resume-results"
    work_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    present_output = result_dir / "present.txt"
    present_output.write_text("ok\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present_output), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )
    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:03Z",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'failed',
                stage = 'execute',
                state_version = 2,
                result_dir = ?,
                finished_at = '2099-06-07T10:00:03Z',
                last_updated_at = '2099-06-07T10:00:03Z'
            WHERE run_id = ?
            """,
            (str(result_dir), "run_resume_failed"),
        )
        connection.commit()

    context = fetch_run_execution_context(cfg, "run_resume_failed")

    assert context["resumeSupported"] is False
    assert context["resumeEligibility"] == {
        "eligible": False,
        "eligibleNow": False,
        "reasonCode": "RUN_RESUME_PREVIEW_AVAILABLE",
        "message": context["resumePlan"]["message"],
    }
    assert context["resumePlan"]["schemaVersion"] == "run-resume-plan.v1"
    assert context["resumeActivationReadiness"] == context["resumePlan"]["activationReadiness"]
    assert context["resumeActivationReadiness"]["schemaVersion"] == "run-resume-activation-readiness.v1"
    assert context["resumeActivationReadiness"]["executionReady"] is False
    assert context["resumeActivationReadiness"]["reasonCode"] == "RUN_RESUME_EXECUTOR_ORCHESTRATION_PREVIEW_ONLY"
    assert context["workdirReusePolicy"] == context["resumePlan"]["workdirEvidence"]
    assert context["resumePlan"]["supported"] is False
    assert context["resumePlan"]["executionEnabled"] is False
    assert context["resumePlan"]["commandPreviewAvailable"] is True
    assert context["resumePlan"]["latestAttempt"]["attemptId"] == claim["attemptId"]
    assert context["resumePlan"]["latestAttempt"]["state"] == "failed"
    assert context["resumePlan"]["workdirEvidence"] == {
        "schemaVersion": "run-workdir-reuse-policy.v1",
        "available": True,
        "workDirReusable": True,
        "pathExposed": False,
        "managedRoot": True,
        "directoryPresent": True,
        "runConfigPresent": True,
        "snakemakeMetadataPresent": False,
        "latestAttempt": {
            "attemptId": claim["attemptId"],
            "attemptNumber": claim["attempt"]["attemptNumber"],
            "leaseGeneration": claim["leaseGeneration"],
            "state": "failed",
        },
        "reasonCode": "WORKDIR_REUSABLE",
        "blockedReasonCodes": [],
    }
    assert context["resumePlan"]["incompleteOutputAudit"]["schemaVersion"] == "run-output-audit.v1"
    assert context["resumePlan"]["incompleteOutputAudit"]["available"] is True
    assert context["resumePlan"]["incompleteOutputAudit"]["pathExposed"] is False
    assert context["resumePlan"]["incompleteOutputAudit"]["expectedOutputCount"] == 2
    assert context["resumePlan"]["incompleteOutputAudit"]["checkedOutputCount"] == 2
    assert context["resumePlan"]["incompleteOutputAudit"]["existingOutputCount"] == 1
    assert context["resumePlan"]["incompleteOutputAudit"]["missingOutputCount"] == 1
    assert context["resumePlan"]["incompleteOutputAudit"]["verifiedOutputCount"] == 2
    assert context["resumePlan"]["incompleteOutputAudit"]["checksumVerifiedOutputCount"] == 1
    assert context["resumePlan"]["incompleteOutputAudit"]["rerunRequiredOutputCount"] == 1
    assert context["resumePlan"]["incompleteOutputAudit"]["rerunRequired"] is True
    assert context["resumePlan"]["incompleteOutputAudit"]["unsafeOutputCount"] == 0
    assert context["resumePlan"]["incompleteOutputAudit"]["unverifiedOutputCount"] == 0
    assert context["resumePlan"]["incompleteOutputAudit"]["reasonCode"] == "OUTPUT_AUDIT_RERUN_REQUIRED"
    assert all("path" not in item for item in context["resumePlan"]["incompleteOutputAudit"]["outputs"])
    assert context["resumePlan"]["artifactAdoptionBoundary"]["reasonCode"] == (
        "RUN_RESUME_ARTIFACT_ADOPTION_BOUNDARY_VERIFIED"
    )
    assert context["resumePlan"]["artifactAdoptionBoundary"]["pathExposed"] is False
    assert context["resumePlan"]["executorOrchestration"]["contractReady"] is True
    assert context["resumePlan"]["executorOrchestration"]["executorReady"] is False
    assert context["resumePlan"]["executorOrchestration"]["queueMutationAllowed"] is False
    assert context["resumePlan"]["executorOrchestration"]["pathExposed"] is False
    assert context["resumePlan"]["snakemakeOptions"] == {
        "schemaVersion": "snakemake-run-resume-options.v1",
        "rerunIncomplete": True,
        "argsPreview": ["--rerun-incomplete"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }
    assert "RUN_RESUME_MUTATION_API_DISABLED" in context["resumePlan"]["blockedReasonCodes"]
    assert "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN" in context["resumePlan"]["blockedReasonCodes"]


def test_run_execution_context_reports_rule_retry_downstream_invalidation_plan(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_workflow_revision(
        cfg,
        {
            "schemaVersion": "workflow-graph-snapshot.v1",
            "runSpec": {
                "workflow": {
                    "nodes": [
                        {"id": "trim_reads", "toolRevisionId": "tool_trim"},
                        {"id": "align", "toolRevisionId": "tool_align"},
                        {"id": "report", "toolRevisionId": "tool_report"},
                    ],
                    "edges": [
                        {"from": {"nodeId": "trim_reads", "port": "reads"}, "to": {"nodeId": "align", "port": "reads"}},
                        {"from": {"nodeId": "align", "port": "bam"}, "to": {"nodeId": "report", "port": "bam"}},
                    ],
                }
            },
        },
    )
    _create_run(cfg, "run_rule_retry_cache_source", workflow_revision_id=revision["workflowRevisionId"])
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET status = 'completed', stage = 'complete' WHERE run_id = ?",
            ("run_rule_retry_cache_source",),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed' WHERE run_id = ?",
            ("run_rule_retry_cache_source",),
        )
        connection.commit()
    cached_artifact = persist_artifact(
        cfg,
        run_id="run_rule_retry_cache_source",
        kind="report",
        path=_managed_report(cfg, "run_rule_retry_cache_source", b"cached align output\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="align",
    )
    _create_run(cfg, "run_rule_retry_plan", workflow_revision_id=revision["workflowRevisionId"])
    stale_output = _managed_report(cfg, "run_rule_retry_plan", b"stale align output\n")
    stale_blob = record_artifact_blob_for_path(
        cfg,
        path=stale_output,
        media_type="text/plain",
        created_at="2099-06-07T09:59:00Z",
    )
    record_run_artifact_edge(
        cfg,
        run_id="run_rule_retry_plan",
        artifact_blob_id=stale_blob["artifactBlobId"],
        role="output",
        port_name="report",
        step_id="align",
        created_at="2099-06-07T09:59:01Z",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        slot_id="slot-rule-retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    work_dir = Path(str(claim["attempt"]["workDir"]))
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"report": str(stale_output)}}),
        encoding="utf-8",
    )
    for rule_name, status in (("trim_reads", "succeeded"), ("align", "failed"), ("report", "blocked")):
        upsert_run_rule_state(
            cfg,
            run_id="run_rule_retry_plan",
            rule_name=rule_name,
            step_id=rule_name,
            runtime_status_key=f"rule:{rule_name}",
            status=status,
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
            attempt_number=int(claim["attempt"]["attemptNumber"]),
            outputs=["report"] if rule_name == "align" else [],
        )

    context = fetch_run_execution_context(cfg, "run_rule_retry_plan")

    plan = context["ruleRetryPlan"]
    cache_restore_plan = context["ruleCacheRestorePlan"]
    output_invalidation_plan = context["ruleOutputInvalidationPlan"]
    execution_plan = context["ruleRetryExecutionPlan"]
    assert plan["schemaVersion"] == "rule-retry-plan.v1"
    assert plan["supported"] is False
    assert plan["eligible"] is False
    assert plan["eligibleNow"] is False
    assert plan["executionEnabled"] is False
    assert plan["executionReasonCode"] == "RULE_RETRY_EXECUTION_DISABLED"
    assert plan["selectionMode"] == "failed-rule-attempts"
    assert plan["selectedAttemptCount"] == 1
    assert plan["invalidationPlanAvailable"] is True
    assert plan["reasonCode"] == "PARTIAL_RULE_RETRY_UNSUPPORTED"
    assert plan["cacheAdoptionBoundary"]["enabled"] is False
    assert plan["cacheAdoptionBoundary"]["reasonCode"] == "CACHE_ADOPTION_UNPROVEN"
    assert plan["artifactAdoptionBoundary"]["reasonCode"] == "ARTIFACT_ADOPTION_UNPROVEN"
    assert plan["adoptedArtifacts"] == []
    assert plan["adoptedCacheEntries"] == []
    assert plan["failedRuleCount"] == 1
    assert [item["ruleName"] for item in plan["rules"]] == ["align"]
    assert [item["ruleName"] for item in plan["preservedRules"]] == ["trim_reads"]
    assert [item["ruleName"] for item in plan["invalidatedRules"]] == ["align", "report"]
    assert plan["rules"][0]["selectionReasonCode"] == "RULE_ATTEMPT_SELECTED_FOR_PLANNING"
    assert plan["rules"][0]["selectedAttempt"] == {
        "attemptId": claim["attemptId"],
        "attemptNumber": claim["attempt"]["attemptNumber"],
        "leaseGeneration": claim["leaseGeneration"],
        "status": "failed",
    }
    assert plan["rules"][0]["invalidatesOwnOutputs"] is True
    assert plan["rules"][0]["adoptionBoundary"]["cacheAdoptionAllowed"] is False
    assert plan["rules"][0]["adoptionBoundary"]["artifactAdoptionAllowed"] is False
    assert plan["rules"][0]["downstreamInvalidation"]["ruleCount"] == 1
    assert plan["rules"][0]["downstreamInvalidation"]["rules"][0]["ruleName"] == "report"
    assert [item["ruleName"] for item in plan["rules"][0]["rerunScope"]["rules"]] == ["align", "report"]
    assert execution_plan["schemaVersion"] == "rule-retry-execution-plan.v1"
    assert context["ruleRetryActivationReadiness"] == execution_plan["activationReadiness"]
    assert context["ruleRetryActivationReadiness"]["schemaVersion"] == "rule-retry-activation-readiness.v1"
    assert context["ruleRetryActivationReadiness"]["executionReady"] is False
    assert context["ruleRetryActivationReadiness"]["reasonCode"] == "DOWNSTREAM_OUTPUT_INVALIDATION_APPLY_REQUIRED"
    rule_retry_checks = {item["name"]: item for item in context["ruleRetryActivationReadiness"]["checks"]}
    assert rule_retry_checks["workdirReuse"]["ready"] is True
    assert execution_plan["sourcePlanSchemaVersion"] == "rule-retry-plan.v1"
    assert execution_plan["supported"] is False
    assert execution_plan["eligible"] is False
    assert execution_plan["eligibleNow"] is False
    assert execution_plan["executionEnabled"] is False
    assert execution_plan["executionReasonCode"] == "RULE_RETRY_EXECUTION_DISABLED"
    assert execution_plan["commandPreviewAvailable"] is True
    assert execution_plan["reasonCode"] == "PARTIAL_RULE_RETRY_UNSUPPORTED"
    assert execution_plan["partialRerunLifecycle"]["schemaVersion"] == "rule-partial-rerun-lifecycle.v1"
    assert execution_plan["partialRerunLifecycle"]["mode"] == "active-attempt-repair"
    assert execution_plan["partialRerunLifecycle"]["queueMutationAllowed"] is False
    assert execution_plan["partialRerunLifecycle"]["activeAttemptRepair"]["supported"] is False
    assert execution_plan["partialRerunLifecycle"]["sourceAttempt"]["leaseReleased"] is False
    assert execution_plan["partialRerunLifecycle"]["targetAttempt"]["creationMode"] == "next-worker-claim"
    assert execution_plan["partialRerunLifecycle"]["outputClosure"]["preservedOutputEdgesRequired"] is True
    assert execution_plan["partialRerunLifecycle"]["pathExposed"] is False
    partial_output_closure = execution_plan["partialRerunOutputClosure"]
    assert partial_output_closure["schemaVersion"] == "rule-partial-rerun-output-closure.v1"
    assert partial_output_closure["available"] is True
    assert partial_output_closure["edgeClosureReady"] is False
    assert partial_output_closure["closureReady"] is False
    assert partial_output_closure["scopedOutputCount"] == 1
    assert partial_output_closure["adoptedScopedOutputCount"] == 0
    assert partial_output_closure["pendingScopedOutputCount"] == 1
    assert partial_output_closure["preservedRuleCount"] == 1
    assert partial_output_closure["preservedOutputEdgeCount"] == 0
    assert partial_output_closure["missingPreservedOutputEdgeCount"] == 1
    assert partial_output_closure["unknownActiveOutputEdgeCount"] == 0
    assert "RULE_PARTIAL_RERUN_SCOPED_OUTPUT_ADOPTION_PENDING" in partial_output_closure["blockedReasonCodes"]
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING" in partial_output_closure["blockedReasonCodes"]
    assert partial_output_closure["pathExposed"] is False
    assert partial_output_closure["storageUriExposed"] is False
    assert [item["ruleName"] for item in execution_plan["selectedRules"]] == ["align"]
    assert [item["ruleName"] for item in execution_plan["rerunScope"]["rules"]] == ["align", "report"]
    assert execution_plan["snakemakeOptions"]["argsPreview"] == ["--rerun-incomplete", "--forcerun", "align"]
    assert execution_plan["snakemakeOptions"]["forcerunRules"] == ["align"]
    assert execution_plan["snakemakeOptions"]["targetOutputKeys"] == ["report"]
    assert "--forceall" in execution_plan["snakemakeOptions"]["unsafeFlagsProhibited"]
    assert "RULE_RETRY_MUTATION_API_DISABLED" in execution_plan["blockedReasonCodes"]
    assert "CACHE_ADOPTION_UNPROVEN" in execution_plan["blockedReasonCodes"]
    assert "STAGED_FILE_POLICY_UNREPRESENTED" in execution_plan["blockedReasonCodes"]
    assert "RESTORE_PIN_POLICY_UNREPRESENTED" in execution_plan["blockedReasonCodes"]
    assert execution_plan["cacheRestorePlan"] == cache_restore_plan
    assert cache_restore_plan["schemaVersion"] == "rule-cache-restore-plan.v1"
    assert len(cache_restore_plan["planHash"]) == 64
    assert cache_restore_plan["planHash"] == stable_plan_hash(cache_restore_plan)
    assert cache_restore_plan["sideEffectFree"] is True
    assert cache_restore_plan["restoreEnabled"] is False
    assert cache_restore_plan["redactionPolicy"] == {
        "cacheKeysExposed": False,
        "cacheKeyFingerprintsExposed": True,
        "keyPayloadsExposed": False,
        "storageUrisExposed": False,
        "pathsExposed": False,
    }
    assert cache_restore_plan["outputCount"] == 1
    assert cache_restore_plan["cacheHitCount"] == 1
    assert cache_restore_plan["cacheMissCount"] == 0
    assert cache_restore_plan["stagedFilePolicy"]["previewAvailable"] is False
    assert cache_restore_plan["stagedFilePolicy"]["reasonCode"] == "STAGED_FILE_POLICY_UNREPRESENTED"
    assert cache_restore_plan["stagedFilePolicy"]["targetCount"] == 1
    assert cache_restore_plan["stagedFilePolicy"]["cacheHitTargetCount"] == 1
    assert cache_restore_plan["stagedFilePolicy"]["overwriteAllowed"] is False
    assert cache_restore_plan["stagedFilePolicy"]["pathExposed"] is False
    assert cache_restore_plan["restorePinPolicy"]["previewAvailable"] is False
    assert cache_restore_plan["restorePinPolicy"]["reasonCode"] == "RESTORE_PIN_POLICY_UNREPRESENTED"
    assert cache_restore_plan["restorePinPolicy"]["candidatePinCount"] == 1
    assert cache_restore_plan["restorePinPolicy"]["requiredPinCount"] == 0
    assert cache_restore_plan["restorePinPolicy"]["createdPinCount"] == 0
    assert cache_restore_plan["restorePinPolicy"]["pinCreationAllowed"] is False
    assert cache_restore_plan["restorePinPolicy"]["ownerIdExposed"] is False
    restore_rule = cache_restore_plan["rules"][0]
    assert restore_rule["ruleName"] == "align"
    assert restore_rule["reasonCode"] == "PER_RULE_CACHE_RESTORE_UNPROVEN"
    assert restore_rule["outputs"][0]["cacheEntry"]["artifactId"] == cached_artifact["artifactId"]
    assert restore_rule["outputs"][0]["cacheKeyPresent"] is True
    assert restore_rule["outputs"][0]["cacheKeyFingerprint"].startswith("sha256:")
    assert restore_rule["outputs"][0]["restoreTarget"]["pathExposed"] is False
    assert restore_rule["outputs"][0]["restorePinPolicy"]["candidate"] is True
    assert restore_rule["outputs"][0]["restorePinPolicy"]["required"] is False
    assert restore_rule["outputs"][0]["restorePinPolicy"]["eligible"] is False
    assert restore_rule["outputs"][0]["restorePinPolicy"]["created"] is False
    assert restore_rule["outputs"][0]["restorePinPolicy"]["reasonCode"] == "RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED"
    serialized_cache_restore_plan = json.dumps(cache_restore_plan, sort_keys=True)
    assert '"cacheKey":' not in serialized_cache_restore_plan
    assert '"storageUri":' not in serialized_cache_restore_plan
    assert output_invalidation_plan["schemaVersion"] == "rule-output-invalidation-plan.v1"
    assert output_invalidation_plan["sideEffectFree"] is True
    assert output_invalidation_plan["invalidationEnabled"] is True
    assert output_invalidation_plan["pathExposed"] is False
    assert output_invalidation_plan["storageReferenceExposed"] is False
    assert output_invalidation_plan["mutationPolicy"]["tombstoneOutputEdges"] is True
    assert output_invalidation_plan["mutationPolicy"]["tombstoneLineageEdges"] is True
    assert output_invalidation_plan["mutationPolicy"]["deleteArtifactPayloads"] is False
    assert output_invalidation_plan["blockedReasonCodes"] == ["ARTIFACT_PAYLOAD_DELETION_DISABLED"]
    assert output_invalidation_plan["outputEdgeSummary"]["outputEdgeCount"] == 1
    assert output_invalidation_plan["outputEdgeSummary"]["invalidatedOutputEdgeCount"] == 1
    assert output_invalidation_plan["outputEdgeSummary"]["selectedOutputEdgeCount"] == 1
    assert output_invalidation_plan["outputEdgeSummary"]["preservedOutputEdgeCount"] == 0
    assert output_invalidation_plan["rules"][0]["ruleName"] == "align"
    assert output_invalidation_plan["rules"][0]["outputs"][0]["portName"] == "report"
    assert output_invalidation_plan["rules"][0]["outputs"][0]["wouldDeletePayload"] is False
    assert "storageUri" not in json.dumps(output_invalidation_plan, sort_keys=True)
    assert execution_plan["outputInvalidationPlan"] == output_invalidation_plan
    with get_connection(cfg) as connection:
        entry = connection.execute("SELECT hit_count FROM artifact_cache_entries WHERE artifact_id = ?", (cached_artifact["artifactId"],)).fetchone()
        lookup_events = connection.execute(
            "SELECT COUNT(*) AS total FROM evidence_events WHERE event_type = 'artifact.cache.lookup.v1'"
        ).fetchone()
    assert entry["hit_count"] == 0
    assert lookup_events["total"] == 0
    assert list_artifact_cache_pins(cfg)["items"] == []


def test_run_execution_context_blocks_rule_retry_plan_without_workflow_revision(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_rule_retry_no_revision")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        slot_id="slot-rule-retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    upsert_run_rule_state(
        cfg,
        run_id="run_rule_retry_no_revision",
        rule_name="align",
        step_id="align",
        runtime_status_key="rule:align",
        status="failed",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
    )

    context = fetch_run_execution_context(cfg, "run_rule_retry_no_revision")

    assert context["ruleRetryPlan"]["supported"] is False
    assert context["ruleRetryPlan"]["invalidationPlanAvailable"] is False
    assert context["ruleRetryPlan"]["reasonCode"] == "WORKFLOW_REVISION_MISSING"
    assert context["ruleRetryPlan"]["failedRuleCount"] == 1
    assert context["ruleRetryExecutionPlan"]["commandPreviewAvailable"] is False
    assert context["ruleRetryExecutionPlan"]["reasonCode"] == "WORKFLOW_REVISION_MISSING"
    assert context["ruleRetryExecutionPlan"]["snakemakeOptions"]["argsPreview"] == []


def test_run_execution_context_rule_retry_plan_uses_latest_rule_attempt(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_workflow_revision(
        cfg,
        {
            "schemaVersion": "workflow-graph-snapshot.v1",
            "nodes": [{"id": "align", "kind": "rule"}],
            "edges": [],
        },
    )
    _create_run(cfg, "run_rule_retry_latest_attempt", workflow_revision_id=revision["workflowRevisionId"])
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        slot_id="slot-rule-retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    upsert_run_rule_state(
        cfg,
        run_id="run_rule_retry_latest_attempt",
        rule_name="align",
        step_id="align",
        runtime_status_key="rule:align",
        status="failed",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO run_rules (
                run_rule_id, run_id, rule_name, step_id, runtime_status_key, status,
                attempt_id, lease_generation, attempt_number, started_at, finished_at,
                exit_code, message, command_summary, inputs_json, outputs_json,
                wildcards_json, logs_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rr_align_latest_success",
                "run_rule_retry_latest_attempt",
                "align",
                "align",
                "rule:align",
                "succeeded",
                "attempt_latest_success",
                2,
                2,
                None,
                None,
                0,
                "",
                "",
                "[]",
                "[]",
                "{}",
                "[]",
                "2099-06-07T10:05:00Z",
            ),
        )
        connection.commit()

    context = fetch_run_execution_context(cfg, "run_rule_retry_latest_attempt")

    assert context["ruleRetryPlan"]["reasonCode"] == "NO_FAILED_RULES"
    assert context["ruleRetryPlan"]["failedRuleCount"] == 0
    assert context["ruleRetryPlan"]["selectedAttemptCount"] == 0
    assert context["ruleRetryPlan"]["rules"] == []


def test_run_execution_context_rule_retry_plan_reports_missing_attempt_id(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_workflow_revision(
        cfg,
        {
            "schemaVersion": "workflow-graph-snapshot.v1",
            "nodes": [{"id": "align", "kind": "rule"}],
            "edges": [],
        },
    )
    _create_run(cfg, "run_rule_retry_missing_attempt", workflow_revision_id=revision["workflowRevisionId"])
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        slot_id="slot-rule-retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    upsert_run_rule_state(
        cfg,
        run_id="run_rule_retry_missing_attempt",
        rule_name="align",
        step_id="align",
        runtime_status_key="rule:align",
        status="failed",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_rules
            SET attempt_id = '', lease_generation = 0, attempt_number = NULL
            WHERE run_id = ? AND rule_name = ?
            """,
            ("run_rule_retry_missing_attempt", "align"),
        )
        connection.commit()

    context = fetch_run_execution_context(cfg, "run_rule_retry_missing_attempt")

    plan = context["ruleRetryPlan"]
    assert plan["supported"] is False
    assert plan["eligible"] is False
    assert plan["eligibleNow"] is False
    assert plan["executionEnabled"] is False
    assert plan["selectedAttemptCount"] == 0
    assert plan["rules"][0]["selectionReasonCode"] == "RULE_ATTEMPT_ID_MISSING"
    assert plan["rules"][0]["attemptSelection"]["selected"] is False
    assert plan["rules"][0]["selectedAttempt"]["attemptId"] == ""


def _create_workflow_revision(cfg, graph_snapshot: dict) -> dict:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_rule_retry",
        draft_revision=1,
        manifest={"schemaVersion": "workflow-revision-manifest.v1", "files": []},
        graph_snapshot=graph_snapshot,
        runtime_lock={"schemaVersion": "runtime-lock.v1"},
        compiler={"name": "test", "version": "1"},
    )
