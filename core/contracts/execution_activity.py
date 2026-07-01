from __future__ import annotations

from typing import Any


def summarize_execution_activity(
    diagnostics: dict[str, Any],
    *,
    make_error: type[Exception],
    require_diagnostics_ok: bool = True,
    block_queued_jobs: bool = True,
) -> dict[str, Any]:
    if not isinstance(diagnostics, dict):
        raise make_error("execution diagnostics payload is not an object")
    if diagnostics.get("schemaVersion") != "execution-diagnostics.v1":
        raise make_error("execution diagnostics response must use execution-diagnostics.v1")
    active_leases = _diagnostic_list(diagnostics, "activeLeases", make_error=make_error)
    allocated_resources = _diagnostic_list(diagnostics, "allocatedResources", make_error=make_error)
    resource_waits = _diagnostic_list(diagnostics, "resourceWaits", make_error=make_error)
    worker_health = _diagnostic_dict(diagnostics, "workerHealth", make_error=make_error)
    queue_metrics = _diagnostic_dict(diagnostics, "queueMetrics", make_error=make_error)
    queued_job_count = _queued_job_count(queue_metrics)
    claimed_job_count = _claimed_job_count(worker_health=worker_health, queue_metrics=queue_metrics)
    running_slot_count = _running_slot_count(worker_health)
    block_reasons = _diagnostic_block_reasons(
        diagnostics=diagnostics,
        active_leases=active_leases,
        allocated_resources=allocated_resources,
        resource_waits=resource_waits,
        queued_job_count=queued_job_count,
        claimed_job_count=claimed_job_count,
        running_slot_count=running_slot_count,
        require_diagnostics_ok=require_diagnostics_ok,
        block_queued_jobs=block_queued_jobs,
    )
    return {
        "activeLeases": active_leases,
        "allocatedResources": allocated_resources,
        "resourceWaits": resource_waits,
        "workerHealth": worker_health,
        "queueMetrics": queue_metrics,
        "activeLeaseCount": len(active_leases),
        "allocatedResourceCount": len(allocated_resources),
        "resourceWaitCount": len(resource_waits),
        "queuedJobCount": queued_job_count,
        "claimedJobCount": claimed_job_count,
        "runningSlotCount": running_slot_count,
        "blockReasons": block_reasons,
    }


def _diagnostic_list(diagnostics: dict[str, Any], key: str, *, make_error: type[Exception]) -> list[Any]:
    value = diagnostics.get(key)
    if not isinstance(value, list):
        raise make_error(f"execution diagnostics {key} is not a list")
    return value


def _diagnostic_dict(diagnostics: dict[str, Any], key: str, *, make_error: type[Exception]) -> dict[str, Any]:
    value = diagnostics.get(key)
    if not isinstance(value, dict):
        raise make_error(f"execution diagnostics {key} is not an object")
    return value


def _diagnostic_block_reasons(
    *,
    diagnostics: dict[str, Any],
    active_leases: list[Any],
    allocated_resources: list[Any],
    resource_waits: list[Any],
    queued_job_count: int,
    claimed_job_count: int,
    running_slot_count: int,
    require_diagnostics_ok: bool,
    block_queued_jobs: bool,
) -> list[str]:
    reasons: list[str] = []
    if require_diagnostics_ok:
        if diagnostics.get("ok") is not True:
            reasons.append("execution-diagnostics-not-ok")
    else:
        invariants = diagnostics.get("invariants") if isinstance(diagnostics.get("invariants"), dict) else {}
        if invariants.get("ok") is not True:
            reasons.append("execution-invariants-not-ok")
    if active_leases:
        reasons.append("active-workflow-leases")
    if allocated_resources:
        reasons.append("allocated-resources")
    if resource_waits:
        reasons.append("queued-resource-waits")
    if block_queued_jobs and queued_job_count > 0:
        reasons.append("queued-jobs")
    if claimed_job_count > 0:
        reasons.append("claimed-jobs")
    if running_slot_count > 0:
        reasons.append("running-worker-slots")
    return _unique(reasons)


def _queued_job_count(queue_metrics: dict[str, Any]) -> int:
    return max(
        _non_negative_int(queue_metrics.get("queuedJobs")),
        _non_negative_int(queue_metrics.get("queueDepth")),
    )


def _claimed_job_count(*, worker_health: dict[str, Any], queue_metrics: dict[str, Any]) -> int:
    return max(_non_negative_int(worker_health.get("claimedJobs")), _non_negative_int(queue_metrics.get("claimedJobs")))


def _running_slot_count(worker_health: dict[str, Any]) -> int:
    summary = worker_health.get("summary")
    if isinstance(summary, dict):
        summary_count = _non_negative_int(summary.get("runningSlots"))
        if summary_count > 0:
            return summary_count
    slots = 0
    workers = worker_health.get("workers")
    if not isinstance(workers, list):
        return slots
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        if str(worker.get("state") or "") == "running" and str(worker.get("currentAttemptId") or ""):
            slots += 1
        for slot in worker.get("slots") or []:
            if isinstance(slot, dict) and str(slot.get("state") or "") == "running":
                slots += 1
    return slots


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values
