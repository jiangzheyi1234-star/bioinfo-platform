from __future__ import annotations

from typing import Any


RESOURCE_WAIT_DEGRADED_SECONDS = 900
QUEUED_DEGRADED_SECONDS = 1800
WORKER_HEARTBEAT_STALE_SECONDS = 90


def evaluate_execution_readiness(
    diagnostics: dict[str, Any],
    *,
    require_worker: bool = True,
) -> dict[str, Any]:
    queue = _dict(diagnostics.get("queueMetrics"))
    workers = _dict(diagnostics.get("workerHealth"))
    sqlite = _dict(diagnostics.get("sqlite"))
    invariants = _dict(diagnostics.get("invariants"))
    blocking: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []

    if not sqlite.get("walEnabled"):
        blocking.append(_reason("SQLITE_WAL_DISABLED", "SQLite WAL mode is not enabled."))
    if not sqlite.get("busyTimeoutOk"):
        blocking.append(_reason("SQLITE_BUSY_TIMEOUT_TOO_LOW", "SQLite busy timeout is too low."))
    for failure in _list(invariants.get("failures")):
        blocking.append(
            _reason(
                _invariant_code(str(_dict(failure).get("name") or "executionInvariantFailed")),
                "Execution control-plane invariant failed.",
                failure,
            )
        )

    worker_summary = _dict(workers.get("summary"))
    if require_worker and int(worker_summary.get("workerCount") or 0) <= 0:
        blocking.append(_reason("RUN_WORKER_UNAVAILABLE", "No run worker is registered."))
    worker_rows = _list(workers.get("workers"))
    if require_worker and _all_workers_unavailable(worker_rows):
        blocking.append(_reason("RUN_WORKER_UNAVAILABLE", "All run workers are stopped or draining."))
    stale_workers = _stale_workers(worker_rows)
    if require_worker and stale_workers and not _has_fresh_available_worker(worker_rows):
        blocking.append(
            _reason(
                "RUN_WORKER_HEARTBEAT_STALE",
                "All available run worker heartbeats are stale.",
                {"thresholdSeconds": WORKER_HEARTBEAT_STALE_SECONDS, "workers": stale_workers},
            )
        )
    elif stale_workers:
        degraded.append(
            _reason(
                "RUN_WORKER_HEARTBEAT_DEGRADED",
                "One or more run worker heartbeats are stale.",
                {"thresholdSeconds": WORKER_HEARTBEAT_STALE_SECONDS, "workers": stale_workers},
            )
        )

    oldest_queued_age = queue.get("oldestQueuedAgeSeconds")
    if isinstance(oldest_queued_age, int) and oldest_queued_age >= QUEUED_DEGRADED_SECONDS:
        degraded.append(
            _reason(
                "QUEUE_WAIT_DEGRADED",
                "Oldest queued job has waited longer than the degraded threshold.",
                {"oldestQueuedAgeSeconds": oldest_queued_age},
            )
        )
    resource_wait_jobs = int(queue.get("resourceWaitJobs") or 0)
    if resource_wait_jobs > 0 and isinstance(oldest_queued_age, int) and oldest_queued_age >= RESOURCE_WAIT_DEGRADED_SECONDS:
        degraded.append(
            _reason(
                "RESOURCE_WAIT_DEGRADED",
                "A resource-waiting job has waited longer than the degraded threshold.",
                {
                    "resourceWaitJobs": resource_wait_jobs,
                    "oldestQueuedAgeSeconds": oldest_queued_age,
                    "waitReasons": queue.get("waitReasons") or {},
                },
            )
        )

    status = "failed" if blocking else "degraded" if degraded else "ok"
    return {
        "schemaVersion": "execution-readiness-policy.v1",
        "ok": not blocking,
        "status": status,
        "reasonCode": str(blocking[0]["code"] if blocking else degraded[0]["code"] if degraded else ""),
        "blockingReasons": blocking,
        "degradedReasons": degraded,
        "checks": {
            "sqliteWal": bool(sqlite.get("walEnabled")),
            "sqliteBusyTimeout": bool(sqlite.get("busyTimeoutOk")),
            "executionInvariants": bool(invariants.get("ok")),
            "runWorkerAvailable": not any(reason["code"] == "RUN_WORKER_UNAVAILABLE" for reason in blocking),
            "workerHeartbeatFresh": not stale_workers,
            "queueWaitWithinThreshold": not any(reason["code"] == "QUEUE_WAIT_DEGRADED" for reason in degraded),
            "resourceWaitWithinThreshold": not any(reason["code"] == "RESOURCE_WAIT_DEGRADED" for reason in degraded),
        },
    }


def _all_workers_unavailable(workers: list[Any]) -> bool:
    if not workers:
        return False
    for raw in workers:
        worker = _dict(raw)
        if worker.get("state") != "stopped" and not worker.get("draining"):
            return False
    return True


def _has_fresh_available_worker(workers: list[Any]) -> bool:
    for raw in workers:
        worker = _dict(raw)
        if _worker_available(worker) and not _worker_stale(worker):
            return True
    return False


def _stale_workers(workers: list[Any]) -> list[dict[str, Any]]:
    stale: list[dict[str, Any]] = []
    for raw in workers:
        worker = _dict(raw)
        if not _worker_available(worker) or not _worker_stale(worker):
            continue
        stale.append(
            {
                "workerId": worker.get("workerId"),
                "sessionId": worker.get("sessionId"),
                "heartbeatAgeSeconds": worker.get("heartbeatAgeSeconds"),
            }
        )
    return stale


def _worker_available(worker: dict[str, Any]) -> bool:
    return worker.get("state") != "stopped" and not worker.get("draining")


def _worker_stale(worker: dict[str, Any]) -> bool:
    age = worker.get("heartbeatAgeSeconds")
    return isinstance(age, int) and age >= WORKER_HEARTBEAT_STALE_SECONDS


def _reason(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return payload


def _invariant_code(name: str) -> str:
    mapping = {
        "allocatedResourcesHaveActiveLeases": "ALLOCATED_RESOURCE_WITHOUT_ACTIVE_LEASE",
        "activeLeasesHaveRunningAttempts": "ACTIVE_LEASE_WITHOUT_RUNNING_ATTEMPT",
        "runningSlotsHaveRunningAttempts": "RUNNING_SLOT_WITHOUT_RUNNING_ATTEMPT",
        "claimedJobsHaveActiveLeases": "CLAIMED_JOB_WITHOUT_ACTIVE_LEASE",
        "sqliteWalAndBusyTimeout": "SQLITE_NOT_READY",
        "workerHealthMatchesQueueMetrics": "WORKER_HEALTH_QUEUE_MISMATCH",
    }
    return mapping.get(name, "EXECUTION_INVARIANT_FAILED")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
