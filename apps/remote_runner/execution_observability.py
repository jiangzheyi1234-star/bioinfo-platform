from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .execution_readiness import QUEUED_DEGRADED_SECONDS, RESOURCE_WAIT_DEGRADED_SECONDS


QUEUE_WAIT_WARNING_SECONDS = QUEUED_DEGRADED_SECONDS
RESOURCE_WAIT_WARNING_SECONDS = RESOURCE_WAIT_DEGRADED_SECONDS
ATTEMPT_RUNTIME_WARNING_SECONDS = 3600
SLOT_SATURATION_WARNING_RATIO = 1.0


def build_execution_observability(
    connection,
    *,
    now: str,
    queue_metrics: dict[str, Any],
    worker_health: dict[str, Any],
    sqlite_metrics: dict[str, Any],
    invariants: dict[str, Any],
) -> dict[str, Any]:
    latency = _latency_signal(connection, now=now, queue_metrics=queue_metrics)
    traffic = _traffic_signal(queue_metrics)
    errors = _error_signal(connection, queue_metrics=queue_metrics, sqlite_metrics=sqlite_metrics, invariants=invariants)
    saturation = _saturation_signal(queue_metrics=queue_metrics, worker_health=worker_health)
    golden_signals = {
        "latency": latency,
        "traffic": traffic,
        "errors": errors,
        "saturation": saturation,
    }
    alerts = _alerts(
        latency=latency,
        errors=errors,
        saturation=saturation,
        sqlite_metrics=sqlite_metrics,
        invariants=invariants,
    )
    slo = _slo_status(alerts)
    return {
        "schemaVersion": "execution-observability.v1",
        "generatedAt": now,
        "semanticConventions": {
            "style": "opentelemetry-inspired",
            "serviceName": "h2ometa-remote-runner",
            "signalGroups": ["latency", "traffic", "errors", "saturation"],
        },
        "thresholds": {
            "queueWaitWarningSeconds": QUEUE_WAIT_WARNING_SECONDS,
            "resourceWaitWarningSeconds": RESOURCE_WAIT_WARNING_SECONDS,
            "attemptRuntimeWarningSeconds": ATTEMPT_RUNTIME_WARNING_SECONDS,
            "slotSaturationWarningRatio": SLOT_SATURATION_WARNING_RATIO,
        },
        "goldenSignals": golden_signals,
        "alerts": alerts,
        "slo": slo,
    }


def _latency_signal(connection, *, now: str, queue_metrics: dict[str, Any]) -> dict[str, Any]:
    running = connection.execute(
        """
        SELECT MIN(started_at) AS oldest_started_at, COUNT(*) AS count
        FROM run_attempts
        WHERE state = 'running'
        """
    ).fetchone()
    resource_wait = connection.execute(
        """
        SELECT MIN(created_at) AS oldest_created_at, COUNT(*) AS count
        FROM run_jobs
        WHERE state = 'queued'
          AND dead_lettered_at IS NULL
          AND wait_reason_json IS NOT NULL
          AND wait_reason_json <> ''
          AND wait_reason_json <> '{}'
        """
    ).fetchone()
    return {
        "queueWaitSeconds": {
            "oldest": queue_metrics.get("oldestQueuedAgeSeconds"),
            "readyQueuedJobs": int(queue_metrics.get("queuedJobs") or 0),
            "totalQueuedJobs": int(queue_metrics.get("totalQueuedJobs") or 0),
        },
        "resourceWaitSeconds": {
            "oldest": _age_seconds(resource_wait["oldest_created_at"], now),
            "jobs": int(resource_wait["count"] or 0),
        },
        "attemptRuntimeSeconds": {
            "oldestRunning": _age_seconds(running["oldest_started_at"], now),
            "runningAttempts": int(running["count"] or 0),
        },
    }


def _traffic_signal(queue_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "queuedJobs": int(queue_metrics.get("queuedJobs") or 0),
        "scheduledQueuedJobs": int(queue_metrics.get("scheduledQueuedJobs") or 0),
        "claimedJobs": int(queue_metrics.get("claimedJobs") or 0),
        "runningAttempts": int(queue_metrics.get("runningAttempts") or 0),
        "completedJobs": int(queue_metrics.get("completedJobs") or 0),
        "failedJobs": int(queue_metrics.get("failedJobs") or 0),
        "deadLetteredJobs": int(queue_metrics.get("deadLetteredJobs") or 0),
        "activeLeases": int(queue_metrics.get("activeLeases") or 0),
        "jobsByState": _int_map(queue_metrics.get("jobsByState")),
        "attemptsByState": _int_map(queue_metrics.get("attemptsByState")),
        "leasesByState": _int_map(queue_metrics.get("leasesByState")),
    }


def _error_signal(
    connection,
    *,
    queue_metrics: dict[str, Any],
    sqlite_metrics: dict[str, Any],
    invariants: dict[str, Any],
) -> dict[str, Any]:
    return {
        "failedJobs": int(queue_metrics.get("failedJobs") or 0),
        "deadLetteredJobs": int(queue_metrics.get("deadLetteredJobs") or 0),
        "fencedAttempts": int(_recovery(queue_metrics, "fencedAttempts")),
        "requeuedJobs": int(_recovery(queue_metrics, "requeuedJobs")),
        "recoveryBlocked": int(_recovery(queue_metrics, "recoveryBlocked")),
        "controlPlaneRecoveries": int(_recovery(queue_metrics, "controlPlaneRecoveries")),
        "sqliteBusyErrors": int(sqlite_metrics.get("busyErrors") or 0),
        "invariantFailures": len(_list(invariants.get("failures"))),
        "fenceReasons": _count_fence_reasons(connection),
        "recoveryReasons": _count_recovery_reasons(connection),
    }


def _saturation_signal(queue_metrics: dict[str, Any], worker_health: dict[str, Any]) -> dict[str, Any]:
    summary = _dict(worker_health.get("summary"))
    total_slots = int(summary.get("totalSlots") or 0)
    running_slots = int(summary.get("runningSlots") or 0)
    idle_slots = int(summary.get("idleSlots") or 0)
    utilization = round(running_slots / total_slots, 3) if total_slots else 0.0
    allocations = _dict(queue_metrics.get("allocations"))
    allocated = _dict(allocations.get("allocatedResources"))
    return {
        "slots": {
            "total": total_slots,
            "running": running_slots,
            "idle": idle_slots,
            "utilization": utilization,
            "states": _int_map(summary.get("slotStates")),
        },
        "workers": {
            "total": int(summary.get("workerCount") or 0),
            "states": _int_map(summary.get("workerStates")),
        },
        "queueBackpressure": {
            "resourceWaitJobs": int(queue_metrics.get("resourceWaitJobs") or 0),
            "waitReasons": _int_map(queue_metrics.get("waitReasons")),
        },
        "resources": {
            "activeAllocations": int(allocations.get("active") or 0),
            "releasedAllocations": int(allocations.get("released") or 0),
            "allocated": {
                "cpu": int(allocated.get("cpu") or 0),
                "memoryMb": int(allocated.get("memoryMb") or 0),
                "diskMb": int(allocated.get("diskMb") or 0),
                "gpu": int(allocated.get("gpu") or 0),
            },
        },
    }


def _alerts(
    *,
    latency: dict[str, Any],
    errors: dict[str, Any],
    saturation: dict[str, Any],
    sqlite_metrics: dict[str, Any],
    invariants: dict[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if not sqlite_metrics.get("ok"):
        alerts.append(_alert("SQLITE_NOT_READY", "critical", "errors", "SQLite is not ready for runner writes."))
    for failure in _list(invariants.get("failures")):
        alerts.append(
            _alert(
                "EXECUTION_INVARIANT_FAILED",
                "critical",
                "errors",
                "Execution control-plane invariant failed.",
                {"invariant": _dict(failure).get("name")},
            )
        )
    queue_wait = _dict(latency.get("queueWaitSeconds")).get("oldest")
    if isinstance(queue_wait, int) and queue_wait >= QUEUE_WAIT_WARNING_SECONDS:
        alerts.append(_alert("QUEUE_WAIT_DEGRADED", "warning", "latency", "Oldest queued job has waited too long."))
    resource_wait = _dict(latency.get("resourceWaitSeconds")).get("oldest")
    if isinstance(resource_wait, int) and resource_wait >= RESOURCE_WAIT_WARNING_SECONDS:
        alerts.append(
            _alert("RESOURCE_WAIT_DEGRADED", "warning", "latency", "Oldest resource-wait job has waited too long.")
        )
    attempt_runtime = _dict(latency.get("attemptRuntimeSeconds")).get("oldestRunning")
    if isinstance(attempt_runtime, int) and attempt_runtime >= ATTEMPT_RUNTIME_WARNING_SECONDS:
        alerts.append(_alert("ATTEMPT_RUNTIME_DEGRADED", "warning", "latency", "A running attempt is unusually old."))
    slots = _dict(saturation.get("slots"))
    backpressure = _dict(saturation.get("queueBackpressure"))
    if (
        int(slots.get("total") or 0) > 0
        and float(slots.get("utilization") or 0.0) >= SLOT_SATURATION_WARNING_RATIO
        and int(backpressure.get("resourceWaitJobs") or 0) > 0
    ):
        alerts.append(_alert("SLOT_SATURATION", "warning", "saturation", "All slots are busy while jobs wait."))
    if int(errors.get("recoveryBlocked") or 0) > 0:
        alerts.append(_alert("RECOVERY_BLOCKED", "critical", "errors", "Control-plane recovery is blocked."))
    if int(errors.get("deadLetteredJobs") or 0) > 0:
        alerts.append(_alert("DEAD_LETTERED_JOBS", "warning", "errors", "One or more jobs are dead-lettered."))
    return alerts


def _slo_status(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [alert for alert in alerts if alert.get("severity") == "critical"]
    degraded = [alert for alert in alerts if alert.get("severity") == "warning"]
    status = "failed" if failed else "degraded" if degraded else "ok"
    return {
        "schemaVersion": "execution-slo-policy.v1",
        "ok": not failed,
        "status": status,
        "alertCount": len(alerts),
        "criticalAlertCount": len(failed),
        "warningAlertCount": len(degraded),
        "objectives": {
            "queueWaitWithinThreshold": not any(alert["code"] == "QUEUE_WAIT_DEGRADED" for alert in alerts),
            "resourceWaitWithinThreshold": not any(alert["code"] == "RESOURCE_WAIT_DEGRADED" for alert in alerts),
            "attemptRuntimeWithinThreshold": not any(alert["code"] == "ATTEMPT_RUNTIME_DEGRADED" for alert in alerts),
            "recoveryNotBlocked": not any(alert["code"] == "RECOVERY_BLOCKED" for alert in alerts),
            "controlPlaneInvariantsHealthy": not any(
                alert["code"] == "EXECUTION_INVARIANT_FAILED" for alert in alerts
            ),
            "sqliteReady": not any(alert["code"] == "SQLITE_NOT_READY" for alert in alerts),
            "slotsNotSaturatedWithBackpressure": not any(alert["code"] == "SLOT_SATURATION" for alert in alerts),
        },
    }


def _count_fence_reasons(connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT COALESCE(fenced_reason, 'unknown') AS reason, COUNT(*) AS count
        FROM run_attempts
        WHERE state = 'fenced'
        GROUP BY COALESCE(fenced_reason, 'unknown')
        """
    ).fetchall()
    return {str(row["reason"]): int(row["count"]) for row in rows}


def _count_recovery_reasons(connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT details_json
        FROM run_events
        WHERE event_type = 'run_control_plane_recovered'
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        payload = _event_payload(row["details_json"])
        reason = str(payload.get("reasonCode") or "UNKNOWN_RECOVERY_REASON")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _event_payload(value: str | None) -> dict[str, Any]:
    import json

    try:
        details = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    payload = details.get("payload") if isinstance(details, dict) else None
    return payload if isinstance(payload, dict) else {}


def _alert(
    code: str,
    severity: str,
    signal: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "signal": signal,
        "message": message,
    }
    if details:
        payload["details"] = details
    return payload


def _recovery(queue_metrics: dict[str, Any], key: str) -> int:
    return int(_dict(queue_metrics.get("recovery")).get(key) or 0)


def _age_seconds(value: str | None, now_text: str) -> int | None:
    if not value:
        return None
    try:
        started = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.strptime(now_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((now - started).total_seconds()))


def _int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int(raw or 0) for key, raw in sorted(value.items())}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
