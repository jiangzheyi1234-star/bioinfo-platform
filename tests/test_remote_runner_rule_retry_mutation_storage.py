from __future__ import annotations

import json

import pytest

from apps.remote_runner.execution_plan_hash import attach_plan_hash
from apps.remote_runner.execution_retry_storage import request_rule_retry, request_run_retry
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.rule_execution_storage import upsert_run_rule_state
from apps.remote_runner.rule_retry_execution_plan import rule_retry_execution_options
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from apps.remote_runner.workflow_run_storage import update_run_state
from tests.helpers.reference_database import make_configured_remote_runner
from tests.helpers.rule_partial_rerun_options import bind_rule_partial_rerun_options


def test_request_rule_retry_refuses_current_disabled_execution_plan(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_failed_rule_run(cfg, "run_rule_retry_disabled")

    with pytest.raises(ValueError, match="RULE_RETRY_EXECUTION_DISABLED"):
        request_rule_retry(
            cfg,
            "run_rule_retry_disabled",
            actor="api-test",
            command_id="cmd_rule_retry_disabled",
            now="2099-06-07T10:01:00Z",
        )

    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage FROM runs WHERE run_id = ?",
            ("run_rule_retry_disabled",),
        ).fetchone()
        job = connection.execute(
            "SELECT state, execution_options_json FROM run_jobs WHERE run_id = ?",
            ("run_rule_retry_disabled",),
        ).fetchone()
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ? AND command_type = 'retry_run'",
            ("run_rule_retry_disabled",),
        ).fetchone()["count"]
        retry_event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND event_type = 'run_retry_requested'",
            ("run_rule_retry_disabled",),
        ).fetchone()["count"]
    assert dict(run) == {"status": "failed", "stage": "execute"}
    assert dict(job) == {"state": "failed", "execution_options_json": "{}"}
    assert command_count == 0
    assert retry_event_count == 0


def test_request_rule_retry_requeues_enabled_plan_with_rule_scope_and_options(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_failed_run(cfg, "run_rule_retry_enabled")
    plan = _enabled_rule_retry_execution_plan("run_rule_retry_enabled", claim["attemptId"], claim["leaseGeneration"])
    monkeypatch.setattr(
        "apps.remote_runner.execution_retry_storage._current_rule_retry_execution_plan",
        lambda _cfg, _run_id: plan,
    )

    result = request_rule_retry(
        cfg,
        "run_rule_retry_enabled",
        actor="api-test",
        reason="operator_rule_retry",
        command_id="cmd_rule_retry_enabled",
        execution_plan=plan,
        now="2099-06-07T10:01:00Z",
    )
    next_claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry_next",
        now="2099-06-07T10:01:00Z",
        lease_seconds=30,
    )

    expected_options = rule_retry_execution_options(plan)
    assert result["scope"] == "rule"
    assert result["executionOptions"] == expected_options
    assert expected_options["rulePartialRerunClaimBinding"]["schemaVersion"] == "rule-partial-rerun-claim-binding.v1"
    assert expected_options["rulePartialRerunClaimBinding"]["sourcePlanHash"] == plan["planHash"]
    assert expected_options["rulePartialRerunClaimBinding"]["pathExposed"] is False
    assert expected_options["rulePartialRerunClaimBinding"]["storageUriExposed"] is False
    assert [rule["ruleName"] for rule in result["selectedRules"]] == ["align"]
    assert next_claim is not None
    assert next_claim["runId"] == "run_rule_retry_enabled"
    assert next_claim["job"]["executionOptions"] == expected_options
    with get_connection(cfg) as connection:
        command = connection.execute(
            "SELECT command_type, actor, payload_json FROM run_commands WHERE command_id = ?",
            ("cmd_rule_retry_enabled",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_type, details_json FROM run_events WHERE event_type = 'run_retry_requested'",
        ).fetchone()
    command_payload = json.loads(command["payload_json"])
    event_payload = json.loads(event["details_json"])["payload"]
    assert dict(command) == {
        "command_type": "retry_run",
        "actor": "api-test",
        "payload_json": command["payload_json"],
    }
    assert command_payload["scope"] == "rule"
    assert command_payload["executionOptions"] == expected_options
    assert event["event_type"] == "run_retry_requested"
    assert event_payload["scope"] == "rule"
    assert event_payload["executionOptions"] == expected_options


def test_request_rule_retry_rejects_run_id_mismatch_before_mutation(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_failed_run(cfg, "run_rule_retry_mismatch")
    plan = _enabled_rule_retry_execution_plan("run_other", claim["attemptId"], claim["leaseGeneration"])

    with pytest.raises(ValueError, match="RULE_RETRY_RUN_ID_MISMATCH"):
        request_rule_retry(cfg, "run_rule_retry_mismatch", execution_plan=plan)

    with get_connection(cfg) as connection:
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ? AND command_type = 'retry_run'",
            ("run_rule_retry_mismatch",),
        ).fetchone()["count"]
    assert command_count == 0


def test_request_rule_retry_rejects_stale_supplied_plan_hash_before_mutation(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_failed_run(cfg, "run_rule_retry_stale_plan")
    plan = _enabled_rule_retry_execution_plan("run_rule_retry_stale_plan", claim["attemptId"], claim["leaseGeneration"])

    with pytest.raises(ValueError, match="RULE_RETRY_EXECUTION_PLAN_HASH_MISMATCH"):
        request_rule_retry(cfg, "run_rule_retry_stale_plan", execution_plan=plan)

    with get_connection(cfg) as connection:
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ? AND command_type = 'retry_run'",
            ("run_rule_retry_stale_plan",),
        ).fetchone()["count"]
    assert command_count == 0


def test_request_run_retry_rejects_self_consistent_stale_rule_options(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_failed_run(cfg, "run_rule_retry_stale_options")
    plan = _enabled_rule_retry_execution_plan(
        "run_rule_retry_stale_options",
        claim["attemptId"],
        claim["leaseGeneration"],
    )
    monkeypatch.setattr(
        "apps.remote_runner.execution_retry_storage._current_rule_retry_execution_plan",
        lambda _cfg, _run_id: plan,
    )
    stale_options = rule_retry_execution_options(plan)
    stale_options["snakemake"]["targetOutputKeys"] = ["other"]
    stale_options["outputAdoptionScope"] = {
        **stale_options["outputAdoptionScope"],
        "outputKeys": ["other"],
        "targetOutputKeys": ["other"],
        "outputs": [
            {
                "outputKey": "other",
                "stepId": "align",
                "outputOrdinal": 1,
                "invalidationRole": "selected",
                "cacheHit": True,
            }
        ],
    }
    bind_rule_partial_rerun_options(stale_options)

    with pytest.raises(ValueError, match="RULE_PARTIAL_RERUN_EXECUTION_OPTIONS_NOT_CURRENT"):
        request_run_retry(
            cfg,
            "run_rule_retry_stale_options",
            actor="api-test",
            reason="operator_rule_retry",
            execution_options=stale_options,
            scope="rule",
            now="2099-06-07T10:01:00Z",
        )

    with get_connection(cfg) as connection:
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ? AND command_type = 'retry_run'",
            ("run_rule_retry_stale_options",),
        ).fetchone()["count"]
    assert command_count == 0


def _create_failed_rule_run(cfg, run_id: str) -> dict:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"wfd_{run_id}",
        draft_revision=1,
        manifest={"schemaVersion": "workflow-revision-manifest.v1", "files": []},
        graph_snapshot={
            "workflow": {
                "nodes": [
                    {"id": "trim_reads", "label": "trim_reads"},
                    {"id": "align", "label": "align"},
                    {"id": "report", "label": "report"},
                ],
                "edges": [
                    {"from": {"nodeId": "trim_reads", "port": "reads"}, "to": {"nodeId": "align", "port": "reads"}},
                    {"from": {"nodeId": "align", "port": "bam"}, "to": {"nodeId": "report", "port": "bam"}},
                ],
            }
        },
        runtime_lock={"schemaVersion": "runtime-lock.v1"},
        compiler={"name": "test", "version": "1"},
    )
    create_run_record(
        cfg,
        server_id="srv_rule_retry",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id, workflow_revision_id=revision["workflowRevisionId"]),
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
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
    return claim


def _create_failed_run(cfg, run_id: str, *, workflow_revision_id: str | None = None) -> dict:
    create_run_record(
        cfg,
        server_id="srv_rule_retry",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id, workflow_revision_id=workflow_revision_id),
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rule_retry",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
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
    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    return claim


def _run_spec(run_id: str, *, workflow_revision_id: str | None = None) -> dict:
    spec = {
        "runId": run_id,
        "projectId": "proj_rule_retry",
        "pipelineId": "pipeline_rule_retry",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
        "execution": {"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
    }
    if workflow_revision_id:
        spec["workflowRevisionId"] = workflow_revision_id
    return spec


def _enabled_rule_retry_execution_plan(run_id: str, attempt_id: str, lease_generation: int) -> dict:
    selected_attempt = {
        "attemptId": attempt_id,
        "attemptNumber": 1,
        "leaseGeneration": lease_generation,
        "status": "failed",
    }
    selected_rule = {
        "runRuleId": "rr_align",
        "ruleName": "align",
        "stepId": "align",
        "runtimeStatusKey": "rule:align",
        "selectedAttempt": selected_attempt,
    }
    return attach_plan_hash({
        "schemaVersion": "rule-retry-execution-plan.v1",
        "runId": run_id,
        "workflowRevisionId": "wfrev_rule_retry",
        "supported": True,
        "eligible": True,
        "eligibleNow": True,
        "executionEnabled": True,
        "executionReasonCode": "RULE_RETRY_EXECUTION_ENABLED",
        "commandPreviewAvailable": True,
        "blockedReasonCodes": [],
        "requiresBeforeExecution": [],
        "selectedRules": [selected_rule],
        "rerunScope": {"ruleCount": 2, "rules": [selected_rule, {"ruleName": "report"}]},
        "snakemakeOptions": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["align"],
            "targetOutputKeys": ["bam"],
            "argsPreview": ["--rerun-incomplete", "--forcerun", "align"],
            "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
        },
        "cacheRestorePlan": {
            "schemaVersion": "rule-cache-restore-plan.v1",
            "outputCount": 1,
            "redactionPolicy": {
                "pathsExposed": False,
                "storageUrisExposed": False,
            },
            "rules": [
                {
                    "ruleName": "align",
                    "stepId": "align",
                    "invalidationRole": "selected",
                    "outputs": [
                        {
                            "artifactKey": "bam",
                            "stepId": "align",
                            "outputOrdinal": 1,
                            "cacheHit": True,
                        }
                    ],
                }
            ],
        },
        "executorOrchestration": {
            "launchPreflight": {
                "preflightReady": True,
                "pathExposed": False,
                "storageUriExposed": False,
            }
        },
    })
