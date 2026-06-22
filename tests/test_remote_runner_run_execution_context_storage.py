from __future__ import annotations

from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str, *, execution: dict | None = None) -> dict:
    spec = {
        "runId": run_id,
        "projectId": "proj_execution_context",
        "pipelineId": "pipeline_execution_context",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }
    if execution:
        spec["execution"] = execution
    return spec


def _create_run(cfg, run_id: str, *, execution: dict | None = None):
    return create_run_record(
        cfg,
        server_id="srv_execution_context",
        request_id=f"req_{run_id}",
        run_spec=_run_spec(run_id, execution=execution),
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
