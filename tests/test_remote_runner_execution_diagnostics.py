from __future__ import annotations

from apps.remote_runner.execution_diagnostics import build_execution_diagnostics
from apps.remote_runner.health_service import ensure_execution_admission_ready
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_worker_storage import (
    heartbeat_run_worker,
    register_run_worker,
    register_run_worker_slot,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_execution_diagnostics_reports_control_plane_snapshot(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_diag_active")
    _create_run(cfg, "run_diag_wait")
    register_run_worker(
        cfg,
        worker_id="worker-diag",
        session_id="session-diag",
        pid=123,
        hostname="host-diag",
        now="2099-06-07T09:59:59Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id="worker-diag",
        session_id="session-diag",
        slot_id="slot-0",
        now="2099-06-07T09:59:59Z",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-diag",
        session_id="session-diag",
        slot_id="slot-0",
        resource_request=ResourceRequest(cpu=1),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    blocked = claim_next_run_job(
        cfg,
        worker_id="worker-diag",
        session_id="session-diag",
        slot_id="slot-1",
        resource_request=ResourceRequest(cpu=1),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now="2099-06-07T10:00:01Z",
        lease_seconds=30,
    )

    diagnostics = build_execution_diagnostics(
        cfg,
        run_ids=["run_diag_active", "run_diag_wait"],
        now="2099-06-07T10:00:02Z",
    )

    assert blocked is None
    assert diagnostics["schemaVersion"] == "execution-diagnostics.v1"
    assert diagnostics["ok"] is True
    observability = diagnostics["executionObservability"]
    assert observability["schemaVersion"] == "execution-observability.v1"
    assert observability["semanticConventions"]["signalGroups"] == [
        "latency",
        "traffic",
        "errors",
        "saturation",
    ]
    assert observability["goldenSignals"]["traffic"]["claimedJobs"] == 1
    assert observability["goldenSignals"]["traffic"]["runningAttempts"] == 1
    assert observability["goldenSignals"]["saturation"]["slots"]["utilization"] == 1.0
    assert observability["goldenSignals"]["saturation"]["queueBackpressure"]["resourceWaitJobs"] == 1
    assert observability["executionPolicy"]["jobsWithRetryPolicy"] == 2
    assert observability["executionPolicy"]["jobsWithRetryBackoff"] == 2
    assert observability["executionPolicy"]["policyRecoveryReasons"] == {
        "ATTEMPT_TIMEOUT": 0,
        "LEASE_EXPIRED": 0,
        "QUEUE_TTL_EXCEEDED": 0,
    }
    assert {"RESOURCE_WAIT_DEGRADED", "SLOT_SATURATION"}.issubset(
        {alert["code"] for alert in observability["alerts"]}
    )
    assert observability["slo"]["status"] == "degraded"
    assert diagnostics["readiness"]["ok"] is True
    assert diagnostics["queueMetrics"]["claimedJobs"] == 1
    assert diagnostics["queueMetrics"]["resourceWaitJobs"] == 1
    assert diagnostics["activeLeases"][0]["attemptId"] == claim["attemptId"]
    assert diagnostics["allocatedResources"][0]["leaseState"] == "active"
    assert diagnostics["resourceWaits"][0]["waitReason"]["code"] == "ADMISSION_SLOT_UNAVAILABLE"
    assert diagnostics["eventHashChains"]["run_diag_active"]["valid"] is True
    assert diagnostics["eventHashChains"]["run_diag_wait"]["valid"] is True
    assert all("token" not in str(item).lower() for item in diagnostics["recentEvents"])


def test_execution_diagnostics_flags_allocated_resource_without_active_lease(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_diag_leak")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-diag-leak",
        session_id="session-diag-leak",
        slot_id="slot-0",
        resource_request=ResourceRequest(cpu=1),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_leases SET state = 'completed' WHERE attempt_id = ?",
            (claim["attemptId"],),
        )
        connection.commit()

    diagnostics = build_execution_diagnostics(cfg, run_ids=["run_diag_leak"])
    failures = {failure["name"] for failure in diagnostics["invariants"]["failures"]}

    assert diagnostics["ok"] is False
    assert "allocatedResourcesHaveActiveLeases" in failures
    assert "claimedJobsHaveActiveLeases" in failures
    assert diagnostics["executionObservability"]["slo"]["status"] == "failed"
    assert "EXECUTION_INVARIANT_FAILED" in {
        alert["code"] for alert in diagnostics["executionObservability"]["alerts"]
    }


def test_execution_admission_ready_rejects_when_no_worker_is_available(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    try:
        ensure_execution_admission_ready(cfg)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("execution admission must reject a runner with no available worker")

    assert message.startswith("RUN_WORKER_UNAVAILABLE:")


def test_execution_diagnostics_redacts_sensitive_worker_errors(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-secret",
        session_id="session-secret",
        pid=123,
        hostname="host-secret",
        now="2099-06-07T09:59:59Z",
    )
    heartbeat_run_worker(
        cfg,
        worker_id="worker-secret",
        session_id="session-secret",
        state="idle",
        last_error={
            "token": "SECRET_TOKEN_CANARY",
            "authorization": "Bearer SECRET_AUTH_CANARY",
            "keyFile": "C:/Users/Administrator/.ssh/SECRET_KEY_CANARY",
        },
        now="2099-06-07T10:00:00Z",
    )

    diagnostics = build_execution_diagnostics(cfg)
    serialized = str(diagnostics)

    assert "SECRET_TOKEN_CANARY" not in serialized
    assert "SECRET_AUTH_CANARY" not in serialized
    assert "SECRET_KEY_CANARY" not in serialized
    assert "[REDACTED]" in serialized


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_diag",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_diag",
            "pipelineId": "pipeline_diag",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
