from __future__ import annotations

import json

import pytest

from apps.remote_runner.execution_retry_storage import request_run_retry
from apps.remote_runner.run_execution_storage import (
    claim_next_run_job,
    complete_run_attempt,
    request_run_cancel,
    run_attempt_cancel_requested,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError, update_run_state
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict:
    return {
        "runId": run_id,
        "projectId": "proj_jobs",
        "pipelineId": "pipeline_jobs",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def _create_run(cfg, run_id: str = "run_jobs", *, execution: dict | None = None):
    run_spec = _run_spec(run_id)
    if execution is not None:
        run_spec["execution"] = execution
    return create_run_record(
        cfg,
        server_id="srv_jobs",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def test_request_run_cancel_records_command_event_and_marks_active_attempt(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_cancel")
    claim = claim_next_run_job(cfg, worker_id="worker_cancel", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None

    result = request_run_cancel(
        cfg,
        "run_cancel",
        actor="api-test",
        command_id="cmd_cancel_run",
        now="2099-06-07T10:00:05Z",
    )

    assert result == {
        "runId": "run_cancel",
        "status": "canceling",
        "stage": "cancel",
        "commandId": "cmd_cancel_run",
        "attemptId": claim["attemptId"],
        "cancelRequestedAt": "2099-06-07T10:00:05Z",
    }
    assert run_attempt_cancel_requested(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    ) is True
    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage, state_version FROM runs WHERE run_id = ?",
            ("run_cancel",),
        ).fetchone()
        attempt = connection.execute(
            "SELECT cancel_requested_at FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        command = connection.execute(
            "SELECT command_type, actor FROM run_commands WHERE command_id = ?",
            ("cmd_cancel_run",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_type, command_id FROM run_events WHERE event_type = ?",
            ("run_cancel_requested",),
        ).fetchone()
    assert dict(run) == {"status": "canceling", "stage": "cancel", "state_version": 2}
    assert attempt["cancel_requested_at"] == "2099-06-07T10:00:05Z"
    assert dict(command) == {"command_type": "cancel_run", "actor": "api-test"}
    assert dict(event) == {"event_type": "run_cancel_requested", "command_id": "cmd_cancel_run"}


def test_request_run_retry_requeues_failed_run_for_next_attempt(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_retry",
        execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
    )
    first = claim_next_run_job(cfg, worker_id="worker_retry_a", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert first is not None
    update_run_state(
        cfg,
        run_id="run_retry",
        status="failed",
        stage="execute",
        message="First attempt failed.",
        request_id="req_run_retry",
        last_error={"code": "TEST_FAILURE", "message": "boom"},
        attempt_id=first["attemptId"],
        lease_generation=first["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )

    result = request_run_retry(
        cfg,
        "run_retry",
        actor="api-test",
        reason="operator_retry",
        command_id="cmd_retry_run",
        now="2099-06-07T10:01:00Z",
    )

    assert result == {
        "runId": "run_retry",
        "status": "queued",
        "stage": "retry",
        "commandId": "cmd_retry_run",
        "jobId": first["jobId"],
        "attemptCount": 1,
        "maxAttempts": 3,
        "remainingAttempts": 2,
        "availableAt": "2099-06-07T10:01:00Z",
        "retryRequestedAt": "2099-06-07T10:01:00Z",
    }
    with get_connection(cfg) as connection:
        run = connection.execute(
            """
            SELECT status, stage, state_version, started_at, finished_at, last_error_json
            FROM runs
            WHERE run_id = ?
            """,
            ("run_retry",),
        ).fetchone()
        job = connection.execute(
            "SELECT state, attempt_count, available_at FROM run_jobs WHERE run_id = ?",
            ("run_retry",),
        ).fetchone()
        command = connection.execute(
            "SELECT command_type, actor FROM run_commands WHERE command_id = ?",
            ("cmd_retry_run",),
        ).fetchone()
        event = connection.execute(
            "SELECT event_type, command_id FROM run_events WHERE event_type = ?",
            ("run_retry_requested",),
        ).fetchone()
    assert dict(run) == {
        "status": "queued",
        "stage": "retry",
        "state_version": 3,
        "started_at": None,
        "finished_at": None,
        "last_error_json": None,
    }
    assert dict(job) == {
        "state": "queued",
        "attempt_count": 1,
        "available_at": "2099-06-07T10:01:00Z",
    }
    assert dict(command) == {"command_type": "retry_run", "actor": "api-test"}
    assert dict(event) == {"event_type": "run_retry_requested", "command_id": "cmd_retry_run"}

    second = claim_next_run_job(cfg, worker_id="worker_retry_b", now="2099-06-07T10:01:00Z", lease_seconds=30)
    assert second is not None
    assert second["runId"] == "run_retry"
    assert second["attempt"]["attemptNumber"] == 2
    assert second["leaseGeneration"] == 2
    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        update_run_state(
            cfg,
            run_id="run_retry",
            status="completed",
            stage="finalize",
            message="Old attempt must not publish after retry.",
            request_id="req_run_retry",
            attempt_id=first["attemptId"],
            lease_generation=first["leaseGeneration"],
        )
    stale_completion = complete_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        state="succeeded",
        exit_code=0,
        now="2099-06-07T10:01:01Z",
    )
    assert stale_completion == {"accepted": False, "reason": "stale_generation"}


def test_request_run_retry_persists_next_attempt_execution_options(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_rule_options_retry",
        execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
    )
    first = claim_next_run_job(cfg, worker_id="worker_rule_options_a", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert first is not None
    update_run_state(
        cfg,
        run_id="run_rule_options_retry",
        status="failed",
        stage="execute",
        message="First attempt failed.",
        request_id="req_run_rule_options_retry",
        attempt_id=first["attemptId"],
        lease_generation=first["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    execution_options = {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": ["align"],
        },
        "outputAdoptionScope": {
            "schemaVersion": "rule-output-adoption-scope.v1",
            "mode": "rule-partial-rerun",
            "outputCount": 1,
            "outputKeys": ["summary"],
            "pathExposed": False,
            "storageUriExposed": False,
        },
    }

    result = request_run_retry(
        cfg,
        "run_rule_options_retry",
        actor="api-test",
        reason="operator_rule_retry",
        execution_options=execution_options,
        now="2099-06-07T10:01:00Z",
    )
    second = claim_next_run_job(cfg, worker_id="worker_rule_options_b", now="2099-06-07T10:01:00Z", lease_seconds=30)

    assert result["executionOptions"] == execution_options
    assert second is not None
    assert second["job"]["executionOptions"] == execution_options
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT execution_options_json FROM run_jobs WHERE run_id = ?",
            ("run_rule_options_retry",),
        ).fetchone()
        command = connection.execute(
            "SELECT payload_json FROM run_commands WHERE command_type = 'retry_run'",
        ).fetchone()
        event = connection.execute(
            "SELECT details_json FROM run_events WHERE event_type = 'run_retry_requested'",
        ).fetchone()
    assert json.loads(job["execution_options_json"]) == execution_options
    assert json.loads(command["payload_json"])["executionOptions"] == execution_options
    assert json.loads(event["details_json"])["payload"]["executionOptions"] == execution_options


def test_request_run_retry_rejects_non_retryable_and_exhausted_runs(tmp_path):
    cfg = make_configured_remote_runner(tmp_path / "queued")
    _create_run(cfg, "run_retry_queued")
    with pytest.raises(ValueError, match="RUN_RETRY_STATUS_NOT_RETRYABLE: queued"):
        request_run_retry(cfg, "run_retry_queued")

    cfg = make_configured_remote_runner(tmp_path / "exhausted")
    _create_run(
        cfg,
        "run_retry_exhausted",
        execution={"retryPolicy": {"maxAttempts": 1, "backoffSeconds": 0}},
    )
    first = claim_next_run_job(cfg, worker_id="worker_retry_exhausted", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert first is not None
    update_run_state(
        cfg,
        run_id="run_retry_exhausted",
        status="failed",
        stage="execute",
        message="Attempt failed.",
        request_id="req_run_retry_exhausted",
        attempt_id=first["attemptId"],
        lease_generation=first["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        first["attemptId"],
        lease_generation=first["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    with pytest.raises(ValueError, match="RUN_RETRY_MAX_ATTEMPTS_EXHAUSTED"):
        request_run_retry(cfg, "run_retry_exhausted")
