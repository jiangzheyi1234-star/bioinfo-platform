from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


EXECUTION_ACTIVITY_DIAGNOSTICS_NOT_OK_REASON = "execution-diagnostics-not-ok"
EXECUTION_ACTIVITY_INVARIANTS_NOT_OK_REASON = "execution-invariants-not-ok"
EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON = "active-workflow-leases"
EXECUTION_ACTIVITY_ALLOCATED_RESOURCES_REASON = "allocated-resources"
EXECUTION_ACTIVITY_QUEUED_RESOURCE_WAITS_REASON = "queued-resource-waits"
EXECUTION_ACTIVITY_QUEUED_JOBS_REASON = "queued-jobs"
EXECUTION_ACTIVITY_CLAIMED_JOBS_REASON = "claimed-jobs"
EXECUTION_ACTIVITY_RUNNING_WORKER_SLOTS_REASON = "running-worker-slots"
EXECUTION_ACTIVITY_QUEUED_TOOL_PREPARE_JOBS_REASON = "queued-tool-prepare-jobs"
EXECUTION_ACTIVITY_RUNNING_TOOL_PREPARE_JOBS_REASON = "running-tool-prepare-jobs"
EXECUTION_ACTIVITY_ACTIVE_TOOL_PREPARE_CLAIMS_REASON = "active-tool-prepare-claims"
EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard.v1"
EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard-release.v1"
EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION = "h2ometa.execution-lifecycle-maintenance.v2"
EXECUTION_LIFECYCLE_MAINTENANCE_KEY = "execution_lifecycle_maintenance"
EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON = "EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE"
EXECUTION_LIFECYCLE_COVERAGE_INCOMPLETE_REASON = "EXECUTION_LIFECYCLE_QUIESCENCE_COVERAGE_INCOMPLETE"
EXECUTION_LIFECYCLE_REQUIRED_QUIESCENCE_COVERAGE = (
    "run-execution",
    "tool-preparation",
    "workflow-automation",
    "mutating-operations",
)
EXECUTION_LIFECYCLE_SUCCESS_COUNT_KEYS = (
    "activeWorkerCount",
    "drainRequestedWorkerCount",
    "activeLeaseCount",
    "allocatedResourceCount",
    "resourceWaitCount",
    "queuedJobCount",
    "claimedJobCount",
    "runningSlotCount",
    "queuedToolPrepareJobCount",
    "runningToolPrepareJobCount",
    "activeToolPrepareClaimCount",
)


def require_execution_lifecycle_quiescence_coverage(
    payload: dict[str, Any],
    *,
    make_error: type[Exception],
) -> tuple[str, ...]:
    raw = payload.get("quiescenceCoverage") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
        raise make_error("remote runner execution lifecycle guard quiescenceCoverage is invalid")
    coverage = tuple(dict.fromkeys(raw))
    missing = [item for item in EXECUTION_LIFECYCLE_REQUIRED_QUIESCENCE_COVERAGE if item not in coverage]
    if missing:
        raise make_error(
            "remote runner execution lifecycle guard quiescence coverage is incomplete: "
            + ", ".join(missing)
        )
    return coverage


def require_execution_lifecycle_guard_success_contract(
    payload: dict[str, Any],
    *,
    expected_action: str,
    expected_owner: str,
    make_error: type[Exception],
) -> tuple[str, ...]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
        raise make_error("remote runner execution lifecycle guard schemaVersion is invalid")
    if payload.get("action") != expected_action or payload.get("owner") != expected_owner:
        raise make_error("remote runner execution lifecycle guard identity does not match the request")
    if payload.get("idle") is not True or payload.get("maintenanceActive") is not True:
        raise make_error("remote runner execution lifecycle guard did not attest active idle maintenance")
    if payload.get("expiryPolicy") != "fail-closed":
        raise make_error("remote runner execution lifecycle guard expiryPolicy is not fail-closed")
    requested_at = _strict_utc_timestamp(payload.get("requestedAt"), key="requestedAt", make_error=make_error)
    expires_at = _strict_utc_timestamp(payload.get("expiresAt"), key="expiresAt", make_error=make_error)
    if expires_at <= requested_at:
        raise make_error("remote runner execution lifecycle guard expiresAt must be after requestedAt")
    block_reasons = payload.get("blockReasons")
    if not isinstance(block_reasons, list) or block_reasons:
        raise make_error("remote runner execution lifecycle guard success blockReasons must be an empty list")
    for key in EXECUTION_LIFECYCLE_SUCCESS_COUNT_KEYS:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise make_error(f"remote runner execution lifecycle guard {key} is not a non-negative integer")
    return require_execution_lifecycle_quiescence_coverage(payload, make_error=make_error)


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
    tool_prepare_jobs = _optional_diagnostic_dict(
        diagnostics,
        "toolPrepareJobs",
        make_error=make_error,
    )
    queued_job_count = _queued_job_count(queue_metrics)
    claimed_job_count = _claimed_job_count(worker_health=worker_health, queue_metrics=queue_metrics)
    running_slot_count = _running_slot_count(worker_health)
    (
        queued_tool_prepare_job_count,
        running_tool_prepare_job_count,
        active_tool_prepare_claim_count,
    ) = _tool_prepare_activity_counts(
        tool_prepare_jobs,
        present="toolPrepareJobs" in diagnostics
        and diagnostics.get("toolPrepareJobs") is not None,
        make_error=make_error,
    )
    block_reasons = _diagnostic_block_reasons(
        diagnostics=diagnostics,
        active_leases=active_leases,
        allocated_resources=allocated_resources,
        resource_waits=resource_waits,
        queued_job_count=queued_job_count,
        claimed_job_count=claimed_job_count,
        running_slot_count=running_slot_count,
        queued_tool_prepare_job_count=queued_tool_prepare_job_count,
        running_tool_prepare_job_count=running_tool_prepare_job_count,
        active_tool_prepare_claim_count=active_tool_prepare_claim_count,
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
        "queuedToolPrepareJobCount": queued_tool_prepare_job_count,
        "runningToolPrepareJobCount": running_tool_prepare_job_count,
        "activeToolPrepareClaimCount": active_tool_prepare_claim_count,
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


def _optional_diagnostic_dict(
    diagnostics: dict[str, Any], key: str, *, make_error: type[Exception]
) -> dict[str, Any]:
    value = diagnostics.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise make_error(f"execution diagnostics {key} is not an object")
    return value


def _tool_prepare_activity_counts(
    activity: dict[str, Any],
    *,
    present: bool,
    make_error: type[Exception],
) -> tuple[int, int, int]:
    if not present:
        return 0, 0, 0
    schema_version = activity.get("schemaVersion")
    if schema_version is not None and schema_version != "tool-prepare-activity.v1":
        raise make_error("execution diagnostics toolPrepareJobs schemaVersion is invalid")
    required_counts = {
        key: _strict_non_negative_int(
            activity.get(key),
            key=f"toolPrepareJobs.{key}",
            make_error=make_error,
        )
        for key in ("queued", "running", "activeClaims")
    }
    ledger_keys = (
        "activeAttemptCount",
        "recoveryRequiredAttemptCount",
        "expiredActiveAttemptCount",
        "openAttemptCount",
        "jobClaimProjectionCount",
        "projectionMismatchCount",
    )
    ledger_values_present = [key in activity for key in ledger_keys]
    if any(ledger_values_present):
        if not all(ledger_values_present):
            raise make_error("execution diagnostics toolPrepareJobs ledger counts are incomplete")
        ledger_counts = {
            key: _strict_non_negative_int(
                activity.get(key),
                key=f"toolPrepareJobs.{key}",
                make_error=make_error,
            )
            for key in ledger_keys
        }
        if ledger_counts["openAttemptCount"] != (
            ledger_counts["activeAttemptCount"]
            + ledger_counts["recoveryRequiredAttemptCount"]
        ):
            raise make_error("execution diagnostics toolPrepareJobs open attempt counts are inconsistent")
        if required_counts["activeClaims"] != ledger_counts["openAttemptCount"]:
            raise make_error("execution diagnostics toolPrepareJobs activeClaims is not ledger-derived")
        if ledger_counts["expiredActiveAttemptCount"] > ledger_counts["activeAttemptCount"]:
            raise make_error("execution diagnostics toolPrepareJobs expired attempt count is invalid")
        violations = activity.get("projectionViolations")
        if not isinstance(violations, list) or len(violations) != ledger_counts["projectionMismatchCount"]:
            raise make_error("execution diagnostics toolPrepareJobs projection violations are inconsistent")
        identity_keys = (
            "systemdProcessIdentityAttemptCount",
            "linuxProcessIdentityAttemptCount",
            "unsupportedProcessIdentityAttemptCount",
            "invalidProcessIdentityAttemptCount",
        )
        identity_values_present = [key in activity for key in identity_keys]
        if not all(identity_values_present):
            raise make_error(
                "execution diagnostics toolPrepareJobs process identity counts are incomplete"
            )
        identity_counts = {
            key: _strict_non_negative_int(
                activity.get(key),
                key=f"toolPrepareJobs.{key}",
                make_error=make_error,
            )
            for key in identity_keys
        }
        if sum(identity_counts.values()) != ledger_counts["openAttemptCount"]:
            raise make_error(
                "execution diagnostics toolPrepareJobs process identity counts are inconsistent"
            )
        invalid_marker_violation_count = sum(
            isinstance(item, dict)
            and item.get("reason") == "OPEN_ATTEMPT_PROCESS_MARKER_INVALID"
            for item in violations
        )
        if (
            identity_counts["invalidProcessIdentityAttemptCount"]
            != invalid_marker_violation_count
        ):
            raise make_error(
                "execution diagnostics toolPrepareJobs invalid process identities are inconsistent"
            )
    return (
        required_counts["queued"],
        required_counts["running"],
        required_counts["activeClaims"],
    )


def _diagnostic_block_reasons(
    *,
    diagnostics: dict[str, Any],
    active_leases: list[Any],
    allocated_resources: list[Any],
    resource_waits: list[Any],
    queued_job_count: int,
    claimed_job_count: int,
    running_slot_count: int,
    queued_tool_prepare_job_count: int,
    running_tool_prepare_job_count: int,
    active_tool_prepare_claim_count: int,
    require_diagnostics_ok: bool,
    block_queued_jobs: bool,
) -> list[str]:
    reasons: list[str] = []
    if require_diagnostics_ok:
        if diagnostics.get("ok") is not True:
            reasons.append(EXECUTION_ACTIVITY_DIAGNOSTICS_NOT_OK_REASON)
    else:
        invariants = diagnostics.get("invariants") if isinstance(diagnostics.get("invariants"), dict) else {}
        if invariants.get("ok") is not True:
            reasons.append(EXECUTION_ACTIVITY_INVARIANTS_NOT_OK_REASON)
    if active_leases:
        reasons.append(EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON)
    if allocated_resources:
        reasons.append(EXECUTION_ACTIVITY_ALLOCATED_RESOURCES_REASON)
    if resource_waits:
        reasons.append(EXECUTION_ACTIVITY_QUEUED_RESOURCE_WAITS_REASON)
    if block_queued_jobs and queued_job_count > 0:
        reasons.append(EXECUTION_ACTIVITY_QUEUED_JOBS_REASON)
    if claimed_job_count > 0:
        reasons.append(EXECUTION_ACTIVITY_CLAIMED_JOBS_REASON)
    if running_slot_count > 0:
        reasons.append(EXECUTION_ACTIVITY_RUNNING_WORKER_SLOTS_REASON)
    if block_queued_jobs and queued_tool_prepare_job_count > 0:
        reasons.append(EXECUTION_ACTIVITY_QUEUED_TOOL_PREPARE_JOBS_REASON)
    if running_tool_prepare_job_count > 0:
        reasons.append(EXECUTION_ACTIVITY_RUNNING_TOOL_PREPARE_JOBS_REASON)
    if active_tool_prepare_claim_count > 0:
        reasons.append(EXECUTION_ACTIVITY_ACTIVE_TOOL_PREPARE_CLAIMS_REASON)
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


def _strict_non_negative_int(
    value: Any,
    *,
    key: str,
    make_error: type[Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise make_error(f"execution diagnostics {key} is not a non-negative integer")
    return value


def _strict_utc_timestamp(value: Any, *, key: str, make_error: type[Exception]) -> datetime:
    if not isinstance(value, str):
        raise make_error(f"remote runner execution lifecycle guard {key} is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise make_error(f"remote runner execution lifecycle guard {key} is invalid") from exc


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values
