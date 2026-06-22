from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
import sqlite3
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

    def dec_to_floor(self, amount: float = 1.0, floor: float = 0.0) -> None:
        with self._lock:
            self._value = max(floor, self._value - amount)


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
        self.sqlite_busy_errors = _MetricValue()
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
            "sqliteBusyErrors": int(self.sqlite_busy_errors.get()),
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


def record_run_attempt_claimed(*, queued_at: str | None, claimed_at: str) -> None:
    metrics = get_metrics()
    metrics.active_runs.inc()
    wait_seconds = _duration_seconds(queued_at, claimed_at)
    if wait_seconds is not None:
        metrics.queue_wait_seconds.observe(wait_seconds)


def record_run_attempt_completed(
    *,
    started_at: str | None,
    finished_at: str,
    terminal_state: str,
) -> None:
    metrics = get_metrics()
    metrics.active_runs.dec_to_floor()
    duration_seconds = _duration_seconds(started_at, finished_at)
    if duration_seconds is not None:
        metrics.run_duration_seconds.observe(duration_seconds)
    normalized_state = str(terminal_state or "").strip().lower()
    if normalized_state == "completed":
        metrics.completed_runs.inc()
    elif normalized_state == "failed":
        metrics.failed_runs.inc()


def record_run_attempt_fenced(*, reason: str) -> None:
    metrics = get_metrics()
    metrics.active_runs.dec_to_floor()
    if reason == "lease_expired":
        metrics.lease_expiries.inc()


def record_run_job_dead_lettered() -> None:
    metrics = get_metrics()
    metrics.dead_lettered_jobs.inc()
    metrics.failed_runs.inc()


def record_run_worker_heartbeat() -> None:
    get_metrics().worker_heartbeats.inc()


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
        jobs_by_state = _count_by_column(connection, "run_jobs", "state")
        attempts_by_state = _count_by_column(connection, "run_attempts", "state")
        leases_by_state = _count_by_column(connection, "run_leases", "state")
        queued = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE state = 'queued' AND available_at <= ? AND dead_lettered_at IS NULL",
            (now,),
        ).fetchone()["c"]
        total_queued = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE state = 'queued' AND dead_lettered_at IS NULL"
        ).fetchone()["c"]
        scheduled = connection.execute(
            "SELECT COUNT(*) AS c FROM run_jobs WHERE state = 'queued' AND available_at > ? AND dead_lettered_at IS NULL",
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
        wait_rows = connection.execute(
            """
            SELECT wait_reason_json
            FROM run_jobs
            WHERE state = 'queued'
              AND dead_lettered_at IS NULL
              AND wait_reason_json IS NOT NULL
              AND wait_reason_json <> ''
              AND wait_reason_json <> '{}'
            """
        ).fetchall()
        allocations = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN state = 'allocated' THEN 1 ELSE 0 END), 0) AS active_count,
                COALESCE(SUM(CASE WHEN state = 'released' THEN 1 ELSE 0 END), 0) AS released_count,
                COALESCE(SUM(CASE WHEN state = 'allocated' THEN cpu ELSE 0 END), 0) AS cpu,
                COALESCE(SUM(CASE WHEN state = 'allocated' THEN memory_mb ELSE 0 END), 0) AS memory_mb,
                COALESCE(SUM(CASE WHEN state = 'allocated' THEN disk_mb ELSE 0 END), 0) AS disk_mb,
                COALESCE(SUM(CASE WHEN state = 'allocated' THEN gpu ELSE 0 END), 0) AS gpu
            FROM run_resource_allocations
            """
        ).fetchone()
        recovery = _recovery_counts(connection)
        oldest_queued = connection.execute(
            """
            SELECT MIN(created_at) AS created_at
            FROM run_jobs
            WHERE state = 'queued' AND dead_lettered_at IS NULL
            """
        ).fetchone()["created_at"]
    wait_reasons = _wait_reason_counts(wait_rows)
    return {
        "queuedJobs": int(queued),
        "totalQueuedJobs": int(total_queued),
        "scheduledQueuedJobs": int(scheduled),
        "claimedJobs": int(claimed),
        "completedJobs": int(jobs_by_state.get("completed", 0)),
        "failedJobs": int(jobs_by_state.get("failed", 0)),
        "deadLetteredJobs": int(dead),
        "activeLeases": int(active_leases),
        "jobsByState": jobs_by_state,
        "attemptsByState": attempts_by_state,
        "leasesByState": leases_by_state,
        "runningAttempts": int(attempts_by_state.get("running", 0)),
        "resourceWaitJobs": sum(wait_reasons.values()),
        "waitReasons": wait_reasons,
        "oldestQueuedAgeSeconds": _age_seconds(oldest_queued, now),
        "allocations": {
            "active": int(allocations["active_count"]),
            "released": int(allocations["released_count"]),
            "allocatedResources": {
                "cpu": int(allocations["cpu"]),
                "memoryMb": int(allocations["memory_mb"]),
                "diskMb": int(allocations["disk_mb"]),
                "gpu": int(allocations["gpu"]),
            },
        },
        "recovery": recovery,
    }


def collect_sqlite_metrics(cfg: Any) -> dict[str, Any]:
    from .storage_core import get_connection

    try:
        with get_connection(cfg) as connection:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0] or "")
            busy_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0] or 0)
    except sqlite3.OperationalError as exc:
        if _sqlite_busy_error(exc):
            return {
                "ok": False,
                "error": "sqlite_busy",
                "busyErrors": int(get_metrics().sqlite_busy_errors.get()),
            }
        return {"ok": False, "error": "sqlite_metrics_failed", "message": str(exc)}
    return {
        "ok": journal_mode.lower() == "wal" and busy_timeout >= 5000,
        "journalMode": journal_mode.lower(),
        "walEnabled": journal_mode.lower() == "wal",
        "busyTimeoutMs": busy_timeout,
        "busyTimeoutOk": busy_timeout >= 5000,
        "busyErrors": int(get_metrics().sqlite_busy_errors.get()),
    }


def record_sqlite_busy_error() -> None:
    get_metrics().sqlite_busy_errors.inc()


def _count_by_column(connection: sqlite3.Connection, table_name: str, column_name: str) -> dict[str, int]:
    rows = connection.execute(
        f"SELECT {column_name} AS value, COUNT(*) AS count FROM {table_name} GROUP BY {column_name}"
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def _wait_reason_counts(rows: list[sqlite3.Row]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = _json_object(row["wait_reason_json"])
        code = str(reason.get("code") or "UNKNOWN_WAIT_REASON").strip() or "UNKNOWN_WAIT_REASON"
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _recovery_counts(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM run_events
        WHERE event_type IN (
            'run_attempt_fenced',
            'run_job_requeued',
            'run_job_dead_lettered',
            'run_attempt_recovery_blocked',
            'run_control_plane_recovered'
        )
        GROUP BY event_type
        """
    ).fetchall()
    raw = {str(row["event_type"]): int(row["count"]) for row in rows}
    return {
        "fencedAttempts": raw.get("run_attempt_fenced", 0),
        "requeuedJobs": raw.get("run_job_requeued", 0),
        "deadLetteredJobs": raw.get("run_job_dead_lettered", 0),
        "recoveryBlocked": raw.get("run_attempt_recovery_blocked", 0),
        "controlPlaneRecoveries": raw.get("run_control_plane_recovered", 0),
    }


def _age_seconds(value: str | None, now_text: str) -> int | None:
    if not value:
        return None
    try:
        started = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.strptime(now_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((now - started).total_seconds()))


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        finished = datetime.strptime(finished_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sqlite_busy_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message or "busy" in message
