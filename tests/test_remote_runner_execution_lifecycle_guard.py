from __future__ import annotations

import json
import threading

import pytest

from core.contracts.execution_activity import (
    EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
    EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION,
)
from apps.remote_runner.errors import RemoteRunnerOperationBlockedError, RemoteRunnerReadinessError
from apps.remote_runner.execution_lifecycle_guard import (
    EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES_REASON,
    EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON,
    EXECUTION_LIFECYCLE_GUARD_EXPIRED_REASON,
    EXECUTION_LIFECYCLE_GUARD_OWNER_MISMATCH_REASON,
    EXECUTION_MAINTENANCE_ACTIVE_REASON,
    ensure_execution_lifecycle_admission_open,
    read_execution_lifecycle_maintenance_for_connection,
    release_execution_lifecycle_guard,
    request_execution_lifecycle_guard,
)
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_worker_storage import (
    register_run_worker,
    register_run_worker_slot,
    request_run_worker_drain,
    run_worker_is_draining,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job
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
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
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
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
        now="2099-06-07T10:00:03Z",
    )

    assert release["released"] is True
    assert run_worker_is_draining(cfg, "worker-lifecycle") is False
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:04Z")


def test_lifecycle_guard_release_preserves_preexisting_manual_worker_drain(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-manual-drain",
        session_id="session-manual-drain",
        pid=123,
        hostname="host-manual-drain",
        now="2099-06-07T10:00:00Z",
    )
    register_run_worker(
        cfg,
        worker_id="worker-guard-drain",
        session_id="session-guard-drain",
        pid=124,
        hostname="host-guard-drain",
        now="2099-06-07T10:00:00Z",
    )
    request_run_worker_drain(cfg, "worker-manual-drain", now="2099-06-07T10:00:01Z")

    guard = request_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
        now="2099-06-07T10:00:02Z",
        ttl_seconds=600,
    )

    assert guard["activeWorkerCount"] == 2
    assert guard["drainRequestedWorkerCount"] == 1
    assert run_worker_is_draining(cfg, "worker-manual-drain") is True
    assert run_worker_is_draining(cfg, "worker-guard-drain") is True

    release_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
        now="2099-06-07T10:00:03Z",
    )

    assert run_worker_is_draining(cfg, "worker-manual-drain") is True
    assert run_worker_is_draining(cfg, "worker-guard-drain") is False


def test_lifecycle_guard_same_owner_reentry_retains_and_extends_drain_ownership(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-reentry-first",
        session_id="session-reentry-first",
        pid=123,
        hostname="host-reentry-first",
        now="2099-06-07T10:00:00Z",
    )

    first_guard = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )
    register_run_worker(
        cfg,
        worker_id="worker-reentry-second",
        session_id="session-reentry-second",
        pid=124,
        hostname="host-reentry-second",
        now="2099-06-07T10:00:02Z",
    )

    renewed_guard = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:03Z",
        ttl_seconds=600,
    )

    assert renewed_guard["requestedAt"] == first_guard["requestedAt"]
    assert renewed_guard["expiresAt"] > first_guard["expiresAt"]
    assert renewed_guard["drainRequestedWorkerCount"] == 2
    assert run_worker_is_draining(cfg, "worker-reentry-first") is True
    assert run_worker_is_draining(cfg, "worker-reentry-second") is True

    release = release_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:04Z",
    )

    assert release["previous"]["drainedWorkerIds"] == ["worker-reentry-first", "worker-reentry-second"]
    assert run_worker_is_draining(cfg, "worker-reentry-first") is False
    assert run_worker_is_draining(cfg, "worker-reentry-second") is False


def test_lifecycle_guard_snapshot_failure_rolls_back_new_maintenance(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.remote_runner import execution_lifecycle_guard

    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-snapshot-fault",
        session_id="session-snapshot-fault",
        pid=125,
        hostname="host-snapshot-fault",
        now="2099-06-07T10:00:00Z",
    )

    def fail_snapshot(connection, **_kwargs):
        assert connection.in_transaction is True
        raise RuntimeError("snapshot fault")

    monkeypatch.setattr(
        execution_lifecycle_guard,
        "build_execution_diagnostics_for_connection",
        fail_snapshot,
    )

    with pytest.raises(RuntimeError, match="snapshot fault"):
        request_execution_lifecycle_guard(
            cfg,
            action="stop",
            owner="srv_lifecycle:snapshot-fault:lifecycle",
            now="2099-06-07T10:00:01Z",
        )

    with get_connection(cfg) as connection:
        maintenance = connection.execute(
            "SELECT value FROM service_state WHERE key = ?",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
        ).fetchone()
    assert maintenance is None
    assert run_worker_is_draining(cfg, "worker-snapshot-fault") is False


def test_lifecycle_guard_reentry_snapshot_failure_restores_previous_guard(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.remote_runner import execution_lifecycle_guard

    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-reentry-stable",
        session_id="session-reentry-stable",
        pid=126,
        hostname="host-reentry-stable",
        now="2099-06-07T10:00:00Z",
    )
    request_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:reentry-fault:lifecycle",
        now="2099-06-07T10:00:01Z",
    )
    with get_connection(cfg) as connection:
        before = str(
            connection.execute(
                "SELECT value FROM service_state WHERE key = ?",
                (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
            ).fetchone()["value"]
        )
    register_run_worker(
        cfg,
        worker_id="worker-reentry-new",
        session_id="session-reentry-new",
        pid=127,
        hostname="host-reentry-new",
        now="2099-06-07T10:00:02Z",
    )

    def fail_snapshot(_connection, **_kwargs):
        raise RuntimeError("reentry snapshot fault")

    monkeypatch.setattr(
        execution_lifecycle_guard,
        "build_execution_diagnostics_for_connection",
        fail_snapshot,
    )
    with pytest.raises(RuntimeError, match="reentry snapshot fault"):
        request_execution_lifecycle_guard(
            cfg,
            action="stop",
            owner="srv_lifecycle:reentry-fault:lifecycle",
            now="2099-06-07T10:00:03Z",
        )

    with get_connection(cfg) as connection:
        after = str(
            connection.execute(
                "SELECT value FROM service_state WHERE key = ?",
                (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
            ).fetchone()["value"]
        )
    assert after == before
    assert run_worker_is_draining(cfg, "worker-reentry-stable") is True
    assert run_worker_is_draining(cfg, "worker-reentry-new") is False


def test_lifecycle_guard_blocks_interleaved_tool_admission_until_guard_commit(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.remote_runner import execution_lifecycle_guard

    cfg = make_configured_remote_runner(tmp_path)
    original_snapshot = execution_lifecycle_guard.build_execution_diagnostics_for_connection
    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_errors: list[BaseException] = []
    writer_thread: threading.Thread | None = None

    def attempt_admission() -> None:
        writer_started.set()
        try:
            create_tool_prepare_job(
                cfg,
                {"id": "bioconda::guard-interleave", "name": "guard-interleave"},
            )
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def snapshot_with_waiting_writer(connection, **kwargs):
        nonlocal writer_thread
        writer_thread = threading.Thread(target=attempt_admission, daemon=True)
        writer_thread.start()
        assert writer_started.wait(1)
        assert writer_finished.wait(0.1) is False
        return original_snapshot(connection, **kwargs)

    monkeypatch.setattr(
        execution_lifecycle_guard,
        "build_execution_diagnostics_for_connection",
        snapshot_with_waiting_writer,
    )
    guard = request_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:interleave:lifecycle",
        now="2099-06-07T10:00:01Z",
    )
    assert writer_thread is not None
    writer_thread.join(timeout=2)

    assert guard["maintenanceActive"] is True
    assert writer_thread.is_alive() is False
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], RemoteRunnerReadinessError)
    with get_connection(cfg) as connection:
        count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM tool_prepare_jobs",
            ).fetchone()["count"]
        )
    assert count == 0
    release_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:interleave:lifecycle",
        now="2099-06-07T10:00:02Z",
    )


def test_lifecycle_guard_blocks_active_lease_and_releases_new_maintenance(tmp_path) -> None:
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
    assert EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON in payload["blockReasons"]
    assert "allocated-resources" in payload["blockReasons"]
    assert "claimed-jobs" in payload["blockReasons"]
    assert payload["activeLeases"][0]["runId"] == "run_lifecycle_active"
    assert payload["maintenanceActive"] is False
    assert payload["maintenanceRelease"]["released"] is True
    assert run_worker_is_draining(cfg, "worker-active") is False

    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:03Z")


def test_lifecycle_guard_reports_durable_queued_jobs_without_blocking_non_upgrade(tmp_path) -> None:
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
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )

    assert guard["idle"] is True
    assert guard["queuedJobCount"] == 1
    assert guard["blockReasons"] == []
    assert run_worker_is_draining(cfg, "worker-queued") is True


def test_lifecycle_guard_blocks_upgrade_when_only_queued_jobs_exist(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_lifecycle_queued_upgrade")
    register_run_worker(
        cfg,
        worker_id="worker-queued-upgrade",
        session_id="session-queued-upgrade",
        pid=123,
        hostname="host-queued-upgrade",
        now="2099-06-07T10:00:00Z",
    )

    with pytest.raises(RemoteRunnerOperationBlockedError) as blocked:
        request_execution_lifecycle_guard(
            cfg,
            action="upgrade",
            owner="srv_lifecycle:upgrade:lifecycle",
            now="2099-06-07T10:00:01Z",
            ttl_seconds=600,
        )

    payload = blocked.value.payload
    assert payload["reasonCode"] == EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON
    assert payload["queuedJobCount"] == 1
    assert payload["blockReasons"] == ["queued-jobs"]
    assert payload["maintenanceActive"] is False
    assert payload["maintenanceRelease"]["released"] is True
    assert run_worker_is_draining(cfg, "worker-queued-upgrade") is False
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:02Z")

    claim = claim_next_run_job(
        cfg,
        worker_id="worker-queued-upgrade",
        now="2099-06-07T10:00:03Z",
        lease_seconds=30,
    )

    assert claim is not None
    assert claim["runId"] == "run_lifecycle_queued_upgrade"


def test_lifecycle_guard_blocker_cleanup_failure_rolls_back_every_change(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.remote_runner import execution_lifecycle_guard

    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_lifecycle_cleanup_fault")
    register_run_worker(
        cfg,
        worker_id="worker-cleanup-fault",
        session_id="session-cleanup-fault",
        pid=128,
        hostname="host-cleanup-fault",
        now="2099-06-07T10:00:00Z",
    )
    original_release = execution_lifecycle_guard._release_owned_maintenance_for_connection

    def release_then_fail(connection, maintenance, *, updated_at: str) -> None:
        original_release(
            connection,
            maintenance,
            updated_at=updated_at,
        )
        raise RuntimeError("cleanup fault")

    monkeypatch.setattr(
        execution_lifecycle_guard,
        "_release_owned_maintenance_for_connection",
        release_then_fail,
    )
    with pytest.raises(RuntimeError, match="cleanup fault"):
        request_execution_lifecycle_guard(
            cfg,
            action="upgrade",
            owner="srv_lifecycle:cleanup-fault:lifecycle",
            now="2099-06-07T10:00:01Z",
        )

    with get_connection(cfg) as connection:
        maintenance = connection.execute(
            "SELECT value FROM service_state WHERE key = ?",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
        ).fetchone()
    assert maintenance is None
    assert run_worker_is_draining(cfg, "worker-cleanup-fault") is False
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:02Z")


def test_claim_next_run_job_respects_lifecycle_maintenance(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_lifecycle_claim_blocked")

    guard = request_execution_lifecycle_guard(
        cfg,
        action="stop",
        owner="srv_lifecycle:stop:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )
    assert guard["idle"] is True
    assert guard["queuedJobCount"] == 1

    claim = claim_next_run_job(
        cfg,
        worker_id="worker-maintenance-blocked",
        now="2099-06-07T10:00:02Z",
        lease_seconds=30,
    )

    assert claim is None
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT state FROM run_jobs WHERE run_id = ?",
            ("run_lifecycle_claim_blocked",),
        ).fetchone()
        lease = connection.execute(
            "SELECT state FROM run_leases WHERE run_id = ?",
            ("run_lifecycle_claim_blocked",),
        ).fetchone()
    assert job["state"] == "queued"
    assert lease is None


def test_lifecycle_guard_allows_token_rotation_action(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-token-rotation",
        session_id="session-token-rotation",
        pid=123,
        hostname="host-token-rotation",
        now="2099-06-07T10:00:00Z",
    )

    guard = request_execution_lifecycle_guard(
        cfg,
        action="token-rotation",
        owner="srv_lifecycle:token-rotation:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=600,
    )

    assert guard["action"] == "token-rotation"
    assert guard["idle"] is True
    assert guard["maintenanceActive"] is True
    assert guard["drainRequestedWorkerCount"] == 1
    assert run_worker_is_draining(cfg, "worker-token-rotation") is True

    release = release_execution_lifecycle_guard(
        cfg,
        action="token-rotation",
        owner="srv_lifecycle:token-rotation:lifecycle",
        now="2099-06-07T10:00:02Z",
    )

    assert release["action"] == "token-rotation"
    assert release["released"] is True


def test_expired_lifecycle_guard_stays_fail_closed_until_same_owner_recovers(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    register_run_worker(
        cfg,
        worker_id="worker-expired-guard",
        session_id="session-expired-guard",
        pid=123,
        hostname="host-expired-guard",
        now="2099-06-07T10:00:00Z",
    )
    guard = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:01Z",
        ttl_seconds=30,
    )
    assert guard["expiresAt"] == "2099-06-07T10:00:31Z"

    with pytest.raises(RemoteRunnerReadinessError) as expired:
        ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:32Z")
    assert str(expired.value).startswith(f"{EXECUTION_LIFECYCLE_GUARD_EXPIRED_REASON}:")
    assert run_worker_is_draining(cfg, "worker-expired-guard") is True

    with get_connection(cfg) as connection:
        expired_maintenance = read_execution_lifecycle_maintenance_for_connection(
            connection,
            now="2099-06-07T10:00:32Z",
        )
        row = connection.execute(
            "SELECT value FROM service_state WHERE key = ?",
            (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
        ).fetchone()
    assert expired_maintenance is not None
    assert expired_maintenance["expired"] is True
    assert expired_maintenance["reasonCode"] == EXECUTION_LIFECYCLE_GUARD_EXPIRED_REASON
    assert row is not None
    maintenance = json.loads(str(row["value"]))
    assert maintenance["schemaVersion"] == EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION
    assert maintenance["active"] is True
    assert maintenance["expiryPolicy"] == "fail-closed"
    assert maintenance["drainedWorkerIds"] == ["worker-expired-guard"]

    with pytest.raises(RemoteRunnerOperationBlockedError) as mismatched:
        release_execution_lifecycle_guard(
            cfg,
            action="upgrade",
            owner="srv_other:upgrade:lifecycle",
            now="2099-06-07T10:00:33Z",
        )
    assert str(mismatched.value) == EXECUTION_LIFECYCLE_GUARD_OWNER_MISMATCH_REASON
    assert mismatched.value.payload["activeMaintenance"]["owner"] == "srv_lifecycle:upgrade:lifecycle"
    assert run_worker_is_draining(cfg, "worker-expired-guard") is True

    renewed = request_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:34Z",
        ttl_seconds=30,
    )
    assert renewed["requestedAt"] == guard["requestedAt"]
    assert renewed["expiresAt"] == "2099-06-07T10:01:04Z"
    assert run_worker_is_draining(cfg, "worker-expired-guard") is True

    release_execution_lifecycle_guard(
        cfg,
        action="upgrade",
        owner="srv_lifecycle:upgrade:lifecycle",
        now="2099-06-07T10:00:35Z",
    )
    assert run_worker_is_draining(cfg, "worker-expired-guard") is False
    ensure_execution_lifecycle_admission_open(cfg, now="2099-06-07T10:00:36Z")


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
