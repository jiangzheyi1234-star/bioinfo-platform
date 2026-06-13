from __future__ import annotations

import threading

from apps.remote_runner.metrics import (
    RunnerMetrics,
    collect_disk_metrics,
    get_metrics,
    reset_metrics,
)


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


def test_collect_disk_metrics(tmp_path):
    result = collect_disk_metrics(str(tmp_path))
    assert result["path"] == str(tmp_path)
    assert "totalBytes" in result
    assert "freeBytes" in result
    assert "usagePercent" in result


def test_collect_disk_metrics_invalid_path():
    result = collect_disk_metrics("/nonexistent/path/that/does/not/exist")
    assert "error" in result
