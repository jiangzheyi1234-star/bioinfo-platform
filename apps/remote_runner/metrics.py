from __future__ import annotations

import shutil
import threading
import time
from typing import Any


class _MetricValue:
    __slots__ = ("_value", "_lock")

    def __init__(self, initial: float = 0.0) -> None:
        self._value = initial
        self._lock = threading.Lock()

    def get(self) -> float:
        with self._lock:
            return self._value

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount


class _Histogram:
    __slots__ = ("_values", "_lock", "_count", "_sum", "_min", "_max")

    def __init__(self) -> None:
        self._values: list[float] = []
        self._lock = threading.Lock()
        self._count = 0
        self._sum = 0.0
        self._min: float | None = None
        self._max: float | None = None

    def observe(self, value: float) -> None:
        with self._lock:
            self._values.append(value)
            self._count += 1
            self._sum += value
            self._min = value if self._min is None else min(self._min, value)
            self._max = value if self._max is None else max(self._max, value)
            if len(self._values) > 1000:
                self._values = self._values[-500:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._count == 0:
                return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0}
            return {
                "count": self._count,
                "sum": round(self._sum, 3),
                "min": round(self._min or 0.0, 3),
                "max": round(self._max or 0.0, 3),
                "avg": round(self._sum / self._count, 3),
            }


class RunnerMetrics:
    def __init__(self) -> None:
        self.queue_depth = _MetricValue()
        self.active_runs = _MetricValue()
        self.completed_runs = _MetricValue()
        self.failed_runs = _MetricValue()
        self.lease_expiries = _MetricValue()
        self.dead_lettered_jobs = _MetricValue()
        self.worker_heartbeats = _MetricValue()
        self.run_duration_seconds = _Histogram()
        self.queue_wait_seconds = _Histogram()
        self._started_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "startedAt": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._started_at)
            ),
            "uptimeSeconds": round(time.time() - self._started_at, 1),
            "queueDepth": int(self.queue_depth.get()),
            "activeRuns": int(self.active_runs.get()),
            "completedRuns": int(self.completed_runs.get()),
            "failedRuns": int(self.failed_runs.get()),
            "leaseExpiries": int(self.lease_expiries.get()),
            "deadLetteredJobs": int(self.dead_lettered_jobs.get()),
            "workerHeartbeats": int(self.worker_heartbeats.get()),
            "runDurationSeconds": self.run_duration_seconds.snapshot(),
            "queueWaitSeconds": self.queue_wait_seconds.snapshot(),
        }


_METRICS: RunnerMetrics | None = None
_METRICS_LOCK = threading.Lock()


def get_metrics() -> RunnerMetrics:
    global _METRICS
    with _METRICS_LOCK:
        if _METRICS is None:
            _METRICS = RunnerMetrics()
        return _METRICS


def reset_metrics() -> None:
    global _METRICS
    with _METRICS_LOCK:
        _METRICS = None


def collect_disk_metrics(path: str) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "totalBytes": usage.total,
            "usedBytes": usage.used,
            "freeBytes": usage.free,
            "usagePercent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        }
    except OSError:
        return {"path": path, "error": "disk_stat_failed"}


def collect_queue_metrics(cfg: Any) -> dict[str, Any]:
    from .storage_core import get_connection, now_iso

    now = now_iso()
    with get_connection(cfg) as connection:
        queued = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE state = 'queued' AND available_at <= ? AND dead_lettered_at IS NULL",
            (now,),
        ).fetchone()["c"]
        claimed = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE state = 'claimed'"
        ).fetchone()["c"]
        dead = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE dead_lettered_at IS NOT NULL"
        ).fetchone()["c"]
        active_leases = connection.execute(
            "SELECT COUNT(*) AS c FROM run_leases WHERE state = 'active'"
        ).fetchone()["c"]
    return {
        "queuedJobs": int(queued),
        "claimedJobs": int(claimed),
        "deadLetteredJobs": int(dead),
        "activeLeases": int(active_leases),
    }
