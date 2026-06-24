from __future__ import annotations

from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.rule_execution_storage import upsert_run_rule_state
from apps.remote_runner.storage import create_run_record
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
    assert context["resumeEligibility"]["reasonCode"] == "RESUME_UNSUPPORTED"
    assert context["job"]["attemptCount"] == 1
    assert context["job"]["maxAttempts"] == 4
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
    _create_run(cfg, "run_rule_retry_plan", workflow_revision_id=revision["workflowRevisionId"])
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        slot_id="slot-rule-retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
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
        )

    context = fetch_run_execution_context(cfg, "run_rule_retry_plan")

    plan = context["ruleRetryPlan"]
    assert plan["schemaVersion"] == "rule-retry-plan.v1"
    assert plan["supported"] is False
    assert plan["invalidationPlanAvailable"] is True
    assert plan["reasonCode"] == "PARTIAL_RULE_RETRY_UNSUPPORTED"
    assert plan["failedRuleCount"] == 1
    assert [item["ruleName"] for item in plan["rules"]] == ["align"]
    assert plan["rules"][0]["downstreamInvalidation"]["ruleCount"] == 1
    assert plan["rules"][0]["downstreamInvalidation"]["rules"][0]["ruleName"] == "report"
    assert [item["ruleName"] for item in plan["rules"][0]["rerunScope"]["rules"]] == ["align", "report"]


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
