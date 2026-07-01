from __future__ import annotations

import json

import pytest

from apps.remote_runner.errors import RemoteRunnerOperationBlockedError, RemoteRunnerReadinessError
from apps.remote_runner.execution_lifecycle_guard import (
    EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES_REASON,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
    EXECUTION_MAINTENANCE_ACTIVE_REASON,
    ensure_execution_lifecycle_admission_open,
    release_execution_lifecycle_guard,
    request_execution_lifecycle_guard,
)
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_worker_storage import register_run_worker, register_run_worker_slot, run_worker_is_draining
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_lifecycle_guard_marks_workers_draining_and_blocks_new_admission(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-lifecycle",
        session_id="session-lifecycle",
        pid=123,
        hostname="host-lifecycle",
        now="2099-06-07T10:00:00Z",
    )

    guard = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )

    assert guard["schemaVersion"] == EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION
    assert guard["idle"] is True
    assert guard["drainRequestedWorkerCount"] == 1
    assert guard["maintenanceActive"] is True
    assert run_worker_is_draining(cfg, "worker-lifecycle") is True

    with pytest.raises(RemoteRunnerReadinessError) as blocked:
        ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:02Z")
    assert str(blocked.value).startswith(f"{EXECUTION_MAINTENANCE_ACTIVE_REASON}:")

    release = release_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:03Z",
    )

    assert release["released"] is True
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:04Z")


def test_lifecycle_guard_blocks_active_lease_and_keeps_maintenance_active(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_lifecycle_active")
    register_run_worker(
        cfg,
        worker_id="worker-active",
        session_id="session-active",
        pid=123,
        hostname="host-active",
        now="2099-06-07T10:00:00Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id="worker-active",
        session_id="session-active",
        slot_id="slot-0",
        now="2099-06-07T10:00:00Z",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-active",
        session_id="session-active",
        slot_id="slot-0",
        resource_request=ResourceRequest(cpu=1),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now="2099-06-07T10:00:01Z",
        lease_seconds=30,
    )
    assert claim is not None

    with pytest.raises(RemoteRunnerOperationBlockedError) as blocked:
        request_execution_lifecycle_guard(
            cfg,
            action="stop",
            owner="srv_lifecycle:stop:lifecycle",
            now="2099-06-07T10:00:02Z",
            ttl_seconds=600,
        )

    payload = blocked.value.payload
    assert payload["reasonCode"] == EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES_REASON
    assert payload["activeLeaseCount"] == 1
    assert "active-workflow-leases" in payload["blockReasons"]
    assert "allocated-resources" in payload["blockReasons"]
    assert "claimed-jobs" in payload["blockReasons"]
    assert payload["activeLeases"][0]["runId"] == "run_lifecycle_active"

    with pytest.raises(RemoteRunnerReadinessError):
        ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:03Z")


def test_lifecycle_guard_reports_durable_queued_jobs_without_blocking(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_lifecycle_queued")
    register_run_worker(
        cfg,
        worker_id="worker-queued",
        session_id="session-queued",
        pid=123,
        hostname="host-queued",
        now="2099-06-07T10:00:00Z",
    )

    guard = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )

    assert guard["idle"] is True
    assert guard["queuedJobCount"] == 1
    assert guard["blockReasons"] == []
    assert run_worker_is_draining(cfg, "worker-queued") is True


def test_expired_lifecycle_guard_is_cleared_on_admission_check(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute(
            "INSERT INTO service_state (key, value) VALUES (?, ?)",
            (
                EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
                json.dumps(
                    {
                        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
                        "active": True,
                        "reasonCode": EXECUTION_MAINTENANCE_ACTIVE_REASON,
                        "action": "upgrade",
                        "owner": "srv_lifecycle:upgrade:lifecycle",
                        "requestedAt": "2099-06-07T10:00:00Z",
                        "expiresAt": "2099-06-07T10:00:01Z",
                        "ttlSeconds": 600,
                    }
                ),
            ),
        )
        connection.commit()

    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:02Z")

    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT value FROM service_state WHERE key = ?",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
        ).fetchone()
    assert row is None


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_lifecycle",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_lifecycle",
            "pipelineId": "pipeline_lifecycle",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
