from __future__ import annotations

import json

from apps.remote_runner.execution_attempt_read_model import fetch_run_attempts_read_model
from apps.remote_runner.run_execution_storage import claim_next_run_job, record_run_attempt_process_group
from apps.remote_runner.run_worker_storage import register_run_worker, register_run_worker_slot
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_attempts_read_model_projects_attempt_lease_and_slot_without_sensitive_fields(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(
        cfg,
        "run_attempt_read_model",
        execution={"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 11}},
    )
    register_run_worker(
        cfg,
        worker_id="worker_attempt_read",
        session_id="session_attempt_read",
        pid=42001,
        hostname="attempt-host",
        now="2099-06-07T09:59:00Z",
    )
    register_run_worker_slot(
        cfg,
        worker_id="worker_attempt_read",
        session_id="session_attempt_read",
        slot_id="slot-attempt-read",
        now="2099-06-07T09:59:01Z",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_attempt_read",
        session_id="session_attempt_read",
        slot_id="slot-attempt-read",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    record_run_attempt_process_group(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        process_group_id="7777",
        now="2099-06-07T10:00:01Z",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET wait_reason_json = ?
            WHERE run_id = ?
            """,
            (
                json.dumps(
                    {
                        "code": "ADMISSION_RESOURCES_UNAVAILABLE",
                        "resource": "cpu",
                        "available": 0,
                        "requested": 2,
                        "path": str(cfg.work_dir),
                        "secretRef": "env://H2OMETA_TOKEN",
                    }
                ),
                "run_attempt_read_model",
            ),
        )
        connection.commit()

    attempts = fetch_run_attempts_read_model(cfg, "run_attempt_read_model")

    assert attempts["schemaVersion"] == "run-attempts.v1"
    assert attempts["runId"] == "run_attempt_read_model"
    assert attempts["run"]["status"] == "queued"
    assert attempts["job"]["attemptCount"] == 1
    assert attempts["job"]["maxAttempts"] == 3
    assert attempts["job"]["retryPolicy"]["backoffSeconds"] == 11
    assert attempts["job"]["waitReason"] == {
        "code": "ADMISSION_RESOURCES_UNAVAILABLE",
        "resource": "cpu",
        "available": 0,
        "requested": 2,
    }
    assert attempts["summary"] == {
        "attemptCount": 1,
        "attemptsByState": {"running": 1},
        "slotCount": 1,
        "slotsByState": {"running": 1},
        "activeLeasePresent": True,
        "latestAttempt": {
            "attemptId": claim["attemptId"],
            "attemptNumber": 1,
            "leaseGeneration": 1,
            "state": "running",
            "startedAt": "2099-06-07T10:00:00Z",
            "finishedAt": None,
            "exitCode": None,
        },
    }
    assert attempts["activeLease"] == {
        "runId": "run_attempt_read_model",
        "attemptId": claim["attemptId"],
        "leaseGeneration": 1,
        "workerId": "worker_attempt_read",
        "sessionId": "session_attempt_read",
        "slotId": "slot-attempt-read",
        "heartbeatAt": "2099-06-07T10:00:00Z",
        "expiresAt": "2099-06-07T10:00:30Z",
        "state": "active",
        "updatedAt": "2099-06-07T10:00:00Z",
    }
    assert attempts["slots"] == [
        {
            "workerId": "worker_attempt_read",
            "sessionId": "session_attempt_read",
            "slotId": "slot-attempt-read",
            "state": "running",
            "currentAttemptId": claim["attemptId"],
            "heartbeatAt": "2099-06-07T10:00:00Z",
            "startedAt": "2099-06-07T09:59:01Z",
            "stoppedAt": None,
            "updatedAt": "2099-06-07T10:00:00Z",
        }
    ]
    assert attempts["redactionPolicy"] == {
        "workDirExposed": False,
        "processIdentifiersExposed": False,
        "commandPayloadExposed": False,
        "runSpecExposed": False,
        "slotErrorDetailsExposed": False,
    }
    serialized = json.dumps(attempts, sort_keys=True)
    for forbidden in (
        '"workDir":',
        "processPid",
        "processGroupId",
        '"runSpec":',
        "executionOptions",
        "payload_json",
        "lastError",
        "last_error_json",
        "secretRef",
        "H2OMETA_TOKEN",
        str(cfg.work_dir),
        "7777",
    ):
        assert forbidden not in serialized


def _create_run(cfg, run_id: str, *, execution: dict | None = None):
    run_spec = {
        "runId": run_id,
        "projectId": "proj_attempt_read",
        "pipelineId": "pipeline_attempt_read",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }
    if execution:
        run_spec["execution"] = execution
    return create_run_record(
        cfg,
        server_id="srv_attempt_read",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
