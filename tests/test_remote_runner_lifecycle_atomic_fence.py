from __future__ import annotations

from dataclasses import replace
import json

import pytest

from apps.remote_runner.errors import RemoteRunnerOperationBlockedError, RemoteRunnerReadinessError
from apps.remote_runner.execution_lifecycle_guard import (
    EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON,
    EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON,
    EXECUTION_MAINTENANCE_ACTIVE_REASON,
    ensure_execution_lifecycle_admission_open,
    read_execution_lifecycle_maintenance_for_connection,
    release_execution_lifecycle_guard,
    request_execution_lifecycle_guard,
)
from apps.remote_runner.execution_retry_storage import request_run_retry
from apps.remote_runner.run_execution_storage import (
    claim_next_run_job,
    complete_run_attempt,
    enqueue_run_job,
)
from apps.remote_runner.run_worker_storage import (
    register_run_worker,
    request_run_worker_drain,
    run_worker_is_draining,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
    fetch_tool_prepare_job,
)
from apps.remote_runner.workflow_run_storage import update_run_state
from core.contracts.execution_activity import (
    EXECUTION_ACTIVITY_ACTIVE_TOOL_PREPARE_CLAIMS_REASON,
    EXECUTION_ACTIVITY_QUEUED_TOOL_PREPARE_JOBS_REASON,
    EXECUTION_ACTIVITY_RUNNING_TOOL_PREPARE_JOBS_REASON,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
    EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION,
)
from tests.helpers.tool_prepare_identity import make_unverifiable_tool_prepare_worker_identity
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_create_is_atomically_rejected_during_lifecycle_maintenance(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _request_idle_guard(cfg, owner="srv_atomic:create:lifecycle")

    with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_MAINTENANCE_ACTIVE_REASON):
        _create_run(cfg, "run_atomic_blocked")

    with get_connection(cfg) as connection:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in ("runs", "run_jobs", "run_commands", "run_events", "idempotency")
        }

    assert counts == {
        "runs": 0,
        "run_jobs": 0,
        "run_commands": 0,
        "run_events": 0,
        "idempotency": 0,
    }


def test_public_run_enqueue_is_atomically_rejected_during_lifecycle_maintenance(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_enqueue_blocked")
    with get_connection(cfg) as connection:
        connection.execute("DELETE FROM run_jobs WHERE run_id = ?", ("run_enqueue_blocked",))
        connection.commit()
    _request_idle_guard(cfg, owner="srv_atomic:enqueue:lifecycle")

    with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_MAINTENANCE_ACTIVE_REASON):
        enqueue_run_job(
            cfg,
            "run_enqueue_blocked",
            available_at="2099-06-07T10:01:01Z",
        )

    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT job_id FROM run_jobs WHERE run_id = ?",
            ("run_enqueue_blocked",),
        ).fetchone()
    assert job is None


def test_inactive_maintenance_row_fails_closed_for_every_admission_path(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_failed_run(cfg, "run_invalid_retry")
    _create_run(cfg, "run_invalid_enqueue")
    with get_connection(cfg) as connection:
        connection.execute("DELETE FROM run_jobs WHERE run_id = ?", ("run_invalid_enqueue",))
        connection.execute(
            "INSERT INTO service_state (key, value) VALUES (?, ?)",
            (
                EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
                json.dumps(
                    {
                        "schemaVersion": EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION,
                        "active": False,
                    }
                ),
            ),
        )
        connection.commit()

    tool_identity = _tool_identity("tool-worker-invalid-maintenance")
    blocked_calls = (
        lambda: _create_run(cfg, "run_invalid_create"),
        lambda: request_run_retry(
            cfg,
            "run_invalid_retry",
            actor="invalid-maintenance-test",
            command_id="cmd_invalid_retry",
        ),
        lambda: enqueue_run_job(cfg, "run_invalid_enqueue"),
        lambda: claim_next_run_job(cfg, worker_id="worker-invalid-maintenance"),
        lambda: create_tool_prepare_job(cfg, {"id": "bioconda::invalid", "name": "invalid"}),
        lambda: claim_next_tool_prepare_job(cfg, identity=tool_identity),
    )
    for blocked_call in blocked_calls:
        with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON):
            blocked_call()
    with get_connection(cfg) as connection:
        attempt_count = int(connection.execute("SELECT COUNT(*) AS count FROM tool_prepare_attempts").fetchone()["count"])
    assert attempt_count == 0


@pytest.mark.parametrize(
    "raw_state",
    [
        json.dumps({"schemaVersion": EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION}),
        json.dumps({"schemaVersion": "h2ometa.execution-lifecycle-maintenance.unknown", "active": True}),
        "{invalid-json",
    ],
)
def test_malformed_maintenance_rows_fail_closed(tmp_path, raw_state: str) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute(
            "INSERT INTO service_state (key, value) VALUES (?, ?)",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY, raw_state),
        )
        connection.commit()

    with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON):
        ensure_execution_lifecycle_admission_open(cfg)


def test_run_retry_is_atomically_rejected_and_terminal_state_is_unchanged(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_failed_run(cfg, "run_retry_atomic")
    with get_connection(cfg) as connection:
        before = _run_retry_rows(connection, "run_retry_atomic")

    _request_idle_guard(cfg, owner="srv_atomic:retry:lifecycle")

    with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_MAINTENANCE_ACTIVE_REASON):
        request_run_retry(
            cfg,
            "run_retry_atomic",
            actor="atomic-fence-test",
            command_id="cmd_retry_atomic_blocked",
            now="2099-06-07T10:01:02Z",
        )

    with get_connection(cfg) as connection:
        after = _run_retry_rows(connection, "run_retry_atomic")
        blocked_command = connection.execute(
            "SELECT command_id FROM run_commands WHERE command_id = ?",
            ("cmd_retry_atomic_blocked",),
        ).fetchone()

    assert after == before
    assert after["run"]["status"] == "failed"
    assert after["job"]["state"] == "failed"
    assert blocked_command is None


def test_tool_prepare_create_and_claim_are_fenced_during_maintenance(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    existing = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::existing-tool", "name": "existing-tool"},
    )
    guard = _request_idle_guard(cfg, owner="srv_atomic:tool-prepare:lifecycle")
    assert guard["queuedToolPrepareJobCount"] == 1

    with pytest.raises(RemoteRunnerReadinessError, match=EXECUTION_MAINTENANCE_ACTIVE_REASON):
        create_tool_prepare_job(
            cfg,
            {"id": "bioconda::blocked-tool", "name": "blocked-tool"},
        )

    assert claim_next_tool_prepare_job(
        cfg,
        identity=_tool_identity("worker-maintenance-blocked"),
        now="2099-06-07T10:00:02Z",
        lease_seconds=30,
    ) is None
    with get_connection(cfg) as connection:
        jobs = connection.execute(
            "SELECT job_id, status, claimed_by, claimed_until FROM tool_prepare_jobs ORDER BY job_id",
        ).fetchall()
        event_count = int(
            connection.execute("SELECT COUNT(*) AS count FROM tool_prepare_job_events").fetchone()["count"]
        )
        attempt_count = int(
            connection.execute("SELECT COUNT(*) AS count FROM tool_prepare_attempts").fetchone()["count"]
        )

    assert [dict(row) for row in jobs] == [
        {
            "job_id": existing["jobId"],
            "status": "queued",
            "claimed_by": "",
            "claimed_until": None,
        }
    ]
    assert event_count == 1
    assert attempt_count == 0


@pytest.mark.parametrize(
    ("case", "expected_reasons", "expected_counts"),
    [
        (
            "queued",
            [EXECUTION_ACTIVITY_QUEUED_TOOL_PREPARE_JOBS_REASON],
            {"queued": 1, "running": 0, "activeClaims": 0},
        ),
        (
            "running",
            [
                EXECUTION_ACTIVITY_RUNNING_TOOL_PREPARE_JOBS_REASON,
                EXECUTION_ACTIVITY_ACTIVE_TOOL_PREPARE_CLAIMS_REASON,
            ],
            {"queued": 0, "running": 1, "activeClaims": 1},
        ),
        (
            "cancelled-active-claim",
            [EXECUTION_ACTIVITY_ACTIVE_TOOL_PREPARE_CLAIMS_REASON],
            {"queued": 0, "running": 0, "activeClaims": 1},
        ),
    ],
)
def test_tool_prepare_activity_blocks_upgrade_guard(
    tmp_path,
    case: str,
    expected_reasons: list[str],
    expected_counts: dict[str, int],
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": f"bioconda::{case}", "name": case},
    )
    proof = None
    if case != "queued":
        proof = claim_next_tool_prepare_job(
            cfg,
            identity=_tool_identity("worker-tool-prepare", session=case),
            now="2099-06-07T10:00:00Z",
            lease_seconds=30,
        )
        assert proof is not None
        if case == "cancelled-active-claim":
            cancelled = cancel_tool_prepare_job(cfg, job["jobId"])
            assert cancelled["status"] == "cancelled"
            assert cancelled["lease"]["claimedBy"] == proof.claim_owner

    with pytest.raises(RemoteRunnerOperationBlockedError) as blocked:
        request_execution_lifecycle_guard(
            cfg,
            action="upgrade",
            owner=f"srv_atomic:{case}:lifecycle",
            now="2099-06-07T10:00:02Z",
            ttl_seconds=600,
        )

    payload = blocked.value.payload
    assert payload["reasonCode"] == EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON
    assert payload["blockReasons"] == expected_reasons
    assert {
        "queued": payload["queuedToolPrepareJobCount"],
        "running": payload["runningToolPrepareJobCount"],
        "activeClaims": payload["activeToolPrepareClaimCount"],
    } == expected_counts
    assert payload["maintenanceActive"] is False
    assert payload["maintenanceRelease"]["released"] is True
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:03Z")
    if proof is not None:
        if case == "running":
            cancelled = cancel_tool_prepare_job(cfg, proof.job_id)
            assert cancelled["status"] == "cancelled"
        assert release_tool_prepare_worker_claim(
            cfg,
            proof=proof,
            now="2099-06-07T10:00:04Z",
        ) is True
        released = fetch_tool_prepare_job(cfg, proof.job_id)
        assert released is not None
        assert released["lease"]["claimedBy"] == ""


def test_release_tool_prepare_worker_claim_clears_the_persisted_lease(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::worker-release", "name": "worker-release"},
    )
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_tool_identity("worker-owner"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert proof is not None
    claimed = fetch_tool_prepare_job(cfg, job["jobId"])
    assert claimed is not None
    assert claimed["lease"]["claimedBy"] == proof.claim_owner
    cancelled = cancel_tool_prepare_job(cfg, proof.job_id)
    assert cancelled["status"] == "cancelled"

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=replace(proof, session_id="worker-other-session"),
            now="2099-06-07T10:00:01Z",
        )
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:02Z",
    ) is True

    refreshed = fetch_tool_prepare_job(cfg, job["jobId"])
    assert refreshed is not None
    assert refreshed["lease"]["claimedBy"] == ""
    assert refreshed["lease"]["claimedUntil"] is None
    assert refreshed["lease"]["heartbeatAt"] is None
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT claimed_by, claimed_until, heartbeat_at FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status, released_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        database_dump = "\n".join(connection.iterdump())
    assert dict(row) == {"claimed_by": "", "claimed_until": None, "heartbeat_at": None}
    assert dict(attempt) == {
        "state": "released",
        "outcome_status": "cancelled",
        "released_at": "2099-06-07T10:00:02Z",
    }
    assert proof.claim_token not in database_dump


def test_legacy_guard_infers_owned_drains_and_preserves_other_manual_drain(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    requested_at = "2099-06-07T10:00:01Z"
    _register_worker(cfg, "worker-legacy-owned")
    _register_worker(cfg, "worker-manual-other-time")
    request_run_worker_drain(cfg, "worker-legacy-owned", now=requested_at)
    request_run_worker_drain(cfg, "worker-manual-other-time", now="2099-06-07T10:00:00Z")
    legacy = {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
        "active": True,
        "reasonCode": EXECUTION_MAINTENANCE_ACTIVE_REASON,
        "action": "upgrade",
        "owner": "srv_legacy:upgrade:lifecycle",
        "requestedAt": requested_at,
        "expiresAt": "2099-06-07T10:10:01Z",
        "ttlSeconds": 600,
    }
    with get_connection(cfg) as connection:
        connection.execute(
            "INSERT INTO service_state (key, value) VALUES (?, ?)",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY, json.dumps(legacy, sort_keys=True)),
        )
        connection.commit()

    with get_connection(cfg) as connection:
        normalized = read_execution_lifecycle_maintenance_for_connection(
            connection,
            now="2099-06-07T10:00:02Z",
        )
    assert normalized is not None
    assert normalized["expiryPolicy"] == "fail-closed"
    assert normalized["drainedWorkerIds"] == ["worker-legacy-owned"]
    assert normalized["drainOwnershipInference"] == "legacy-requested-at"

    released = release_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_legacy:upgrade:lifecycle",
        now="2099-06-07T10:00:03Z",
    )

    assert released["released"] is True
    assert released["previous"]["drainedWorkerIds"] == ["worker-legacy-owned"]
    assert run_worker_is_draining(cfg, "worker-legacy-owned") is False
    assert run_worker_is_draining(cfg, "worker-manual-other-time") is True
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:04Z")


def _create_run(cfg, run_id: str):
    return create_run_record(
        cfg,
        server_id="srv_atomic",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_atomic",
            "pipelineId": "pipeline_atomic",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


def _create_failed_run(cfg, run_id: str) -> None:
    _create_run(cfg, run_id)
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-retry-atomic",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage="execute",
        message="Atomic retry fixture failed.",
        request_id=f"req_{run_id}",
        last_error={"code": "ATOMIC_TEST_FAILURE", "message": "fixture failure"},
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    )
    completion = complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:01Z",
    )
    assert completion == {"accepted": True, "state": "failed"}


def _request_idle_guard(cfg, *, owner: str) -> dict:
    guard = request_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner=owner,
        now="2099-06-07T10:01:00Z",
        ttl_seconds=600,
    )
    assert guard["idle"] is True
    assert guard["maintenanceActive"] is True
    return guard


def _run_retry_rows(connection, run_id: str) -> dict[str, dict]:
    run = connection.execute(
        "SELECT status, stage, state_version, message, started_at, finished_at, last_error_json FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    job = connection.execute(
        "SELECT state, available_at, attempt_count, wait_reason_json, updated_at FROM run_jobs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert run is not None
    assert job is not None
    return {"run": dict(run), "job": dict(job)}


def _register_worker(cfg, worker_id: str) -> None:
    register_run_worker(
        cfg,
        worker_id=worker_id,
        session_id=f"session-{worker_id}",
        pid=123,
        hostname="host-atomic",
        now="2099-06-07T09:59:59Z",
    )


def _tool_identity(worker_id: str, *, session: str = "session-1") -> ToolPrepareWorkerIdentity:
    return make_unverifiable_tool_prepare_worker_identity(
        worker_id=worker_id,
        session_id=session,
        process_instance_id=f"process-{session}",
        hostname="lifecycle-test-runner",
    )
