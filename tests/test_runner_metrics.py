from __future__ import annotations

import sqlite3
import threading

import pytest

from apps.remote_runner.metrics import (
    RunnerMetrics,
    collect_disk_metrics,
    collect_queue_metrics,
    collect_sqlite_metrics,
    get_metrics,
    record_sqlite_busy_error,
    reset_metrics,
)
from apps.remote_runner.reconciler import run_active_reconciler_once
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.run_worker_storage import heartbeat_run_worker, register_run_worker
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_runner_metrics_snapshot():
    metrics = RunnerMetrics()
    metrics.queue_depth.set(5)
    metrics.active_runs.set(2)
    metrics.completed_runs.inc()
    metrics.completed_runs.inc()
    metrics.failed_runs.inc()
    metrics.lease_expiries.inc()
    metrics.run_duration_seconds.observe(10.5)
    metrics.run_duration_seconds.observe(20.3)
    metrics.queue_wait_seconds.observe(1.2)

    snapshot = metrics.snapshot()
    assert snapshot["queueDepth"] == 5
    assert snapshot["activeRuns"] == 2
    assert snapshot["completedRuns"] == 2
    assert snapshot["failedRuns"] == 1
    assert snapshot["leaseExpiries"] == 1
    assert snapshot["runDurationSeconds"]["count"] == 2
    assert snapshot["runDurationSeconds"]["min"] == 10.5
    assert snapshot["runDurationSeconds"]["max"] == 20.3
    assert snapshot["queueWaitSeconds"]["count"] == 1
    assert "uptimeSeconds" in snapshot
    assert "startedAt" in snapshot


def test_metrics_thread_safety():
    metrics = RunnerMetrics()
    errors: list[str] = []

    def worker():
        try:
            for _ in range(100):
                metrics.completed_runs.inc()
                metrics.run_duration_seconds.observe(1.0)
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    snapshot = metrics.snapshot()
    assert snapshot["completedRuns"] == 1000
    assert snapshot["runDurationSeconds"]["count"] == 1000


def test_histogram_average_stays_all_time_after_sample_trim():
    metrics = RunnerMetrics()
    metrics.run_duration_seconds.observe(0.0)
    for _ in range(1000):
        metrics.run_duration_seconds.observe(1.0)

    snapshot = metrics.snapshot()["runDurationSeconds"]
    assert snapshot["count"] == 1001
    assert snapshot["sum"] == 1000.0
    assert snapshot["min"] == 0.0
    assert snapshot["max"] == 1.0
    assert snapshot["avg"] == 0.999


def test_get_and_reset_metrics():
    reset_metrics()
    m1 = get_metrics()
    m2 = get_metrics()
    assert m1 is m2

    reset_metrics()
    m3 = get_metrics()
    assert m3 is not m1


def test_run_lifecycle_records_live_metrics(tmp_path):
    reset_metrics()
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_live_metrics")
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET created_at = ?, available_at = ?
            WHERE run_id = ?
            """,
            ("2099-06-07T09:59:55Z", "2099-06-07T09:59:55Z", "run_live_metrics"),
        )
        connection.commit()

    claim = claim_next_run_job(
        cfg,
        worker_id="worker-live-metrics",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    claimed_snapshot = get_metrics().snapshot()

    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="succeeded",
        exit_code=0,
        now="2099-06-07T10:00:15Z",
    )
    completed_snapshot = get_metrics().snapshot()

    assert claimed_snapshot["activeRuns"] == 1
    assert claimed_snapshot["queueWaitSeconds"]["count"] == 1
    assert claimed_snapshot["queueWaitSeconds"]["max"] == 5.0
    assert completed_snapshot["activeRuns"] == 0
    assert completed_snapshot["completedRuns"] == 1
    assert completed_snapshot["failedRuns"] == 0
    assert completed_snapshot["runDurationSeconds"]["count"] == 1
    assert completed_snapshot["runDurationSeconds"]["max"] == 15.0


def test_reconciler_and_worker_heartbeat_record_live_metrics(tmp_path):
    reset_metrics()
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_expiry_metrics")
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-expiry-metrics",
        session_id="session-expiry-metrics",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claim is not None
    register_run_worker(
        cfg,
        worker_id="worker-expiry-metrics",
        session_id="session-expiry-metrics",
        pid=123,
        hostname="host-expiry-metrics",
        now="2099-06-07T10:00:00Z",
    )

    heartbeat_run_worker(
        cfg,
        worker_id="worker-expiry-metrics",
        session_id="session-expiry-metrics",
        state="running",
        current_attempt_id=claim["attemptId"],
        now="2099-06-07T10:00:05Z",
    )
    run_active_reconciler_once(
        cfg,
        now="2099-06-07T10:00:11Z",
        retry_delay_seconds=0,
    )
    snapshot = get_metrics().snapshot()

    assert snapshot["workerHeartbeats"] == 1
    assert snapshot["leaseExpiries"] == 1
    assert snapshot["activeRuns"] == 0


def test_collect_disk_metrics(tmp_path):
    result = collect_disk_metrics(str(tmp_path))
    assert result["path"] == str(tmp_path)
    assert "totalBytes" in result
    assert "freeBytes" in result
    assert "usagePercent" in result


def test_collect_disk_metrics_invalid_path():
    result = collect_disk_metrics("/nonexistent/path/that/does/not/exist")
    assert "error" in result


def test_collect_queue_metrics_reports_admission_wait_allocations_and_recovery(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_metrics_active")
    _create_run(cfg, "run_metrics_wait")

    claim = claim_next_run_job(
        cfg,
        worker_id="worker-metrics",
        session_id="session-metrics",
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
        worker_id="worker-metrics",
        session_id="session-metrics",
        slot_id="slot-1",
        resource_request=ResourceRequest(cpu=1),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now="2099-06-07T10:00:01Z",
        lease_seconds=30,
    )

    before_completion = collect_queue_metrics(cfg)
    complete_run_attempt(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        state="succeeded",
        exit_code=0,
        now="2099-06-07T10:00:05Z",
    )
    after_completion = collect_queue_metrics(cfg)

    assert blocked is None
    assert before_completion["claimedJobs"] == 1
    assert before_completion["runningAttempts"] == 1
    assert before_completion["resourceWaitJobs"] == 1
    assert before_completion["waitReasons"] == {"ADMISSION_SLOT_UNAVAILABLE": 1}
    assert before_completion["allocations"]["active"] == 1
    assert before_completion["allocations"]["allocatedResources"]["cpu"] == 1
    assert before_completion["leasesByState"] == {"active": 1}
    assert after_completion["completedJobs"] == 1
    assert after_completion["allocations"]["active"] == 0
    assert after_completion["allocations"]["released"] == 1


def test_collect_sqlite_metrics_reports_wal_busy_timeout_and_busy_counter(tmp_path):
    reset_metrics()
    cfg = make_configured_remote_runner(tmp_path)
    record_sqlite_busy_error()

    sqlite_metrics = collect_sqlite_metrics(cfg)

    assert sqlite_metrics["ok"] is True
    assert sqlite_metrics["journalMode"] == "wal"
    assert sqlite_metrics["walEnabled"] is True
    assert sqlite_metrics["busyTimeoutMs"] >= 5000
    assert sqlite_metrics["busyTimeoutOk"] is True
    assert sqlite_metrics["busyErrors"] == 1


def test_observed_sqlite_connection_records_busy_errors(tmp_path):
    from apps.remote_runner.storage_core import get_connection

    reset_metrics()
    cfg = make_configured_remote_runner(tmp_path)
    observed = get_connection(cfg)
    observed.execute("PRAGMA busy_timeout = 1")
    locker = sqlite3.connect(str(cfg.db_path), timeout=0)
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            observed.execute("BEGIN IMMEDIATE")
    finally:
        locker.rollback()
        locker.close()
        observed.close()

    assert get_metrics().snapshot()["sqliteBusyErrors"] == 1


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_metrics",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_metrics",
            "pipelineId": "pipeline_metrics",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
