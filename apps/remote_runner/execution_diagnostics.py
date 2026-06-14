from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import verify_run_event_hash_chain
from .execution_readiness import evaluate_execution_readiness
from .metrics import collect_queue_metrics, collect_sqlite_metrics
from .run_worker_storage import build_run_worker_health
from .storage_core import get_connection, now_iso


def build_execution_diagnostics(
    cfg: RemoteRunnerConfig,
    *,
    run_ids: list[str] | None = None,
    event_limit: int = 25,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or now_iso()
    normalized_run_ids = _normalize_run_ids(run_ids)
    queue_metrics = collect_queue_metrics(cfg)
    worker_health = build_run_worker_health(cfg, now=timestamp)
    sqlite_metrics = collect_sqlite_metrics(cfg)
    with get_connection(cfg) as connection:
        active_leases = _active_leases(connection)
        allocated_resources = _allocated_resources(connection)
        resource_waits = _resource_waits(connection)
        recent_events = _recent_events(connection, run_ids=normalized_run_ids, limit=event_limit)
        recovery_evidence = _recovery_evidence(connection, run_ids=normalized_run_ids, limit=event_limit)
        event_chains = {
            run_id: verify_run_event_hash_chain(connection, run_id)
            for run_id in normalized_run_ids
        }
        invariants = _invariants(
            connection,
            queue_metrics=queue_metrics,
            worker_health=worker_health,
            sqlite_metrics=sqlite_metrics,
        )
    payload = {
        "schemaVersion": "execution-diagnostics.v1",
        "generatedAt": timestamp,
        "ok": invariants["ok"],
        "queueMetrics": queue_metrics,
        "workerHealth": worker_health,
        "sqlite": sqlite_metrics,
        "invariants": invariants,
        "activeLeases": active_leases,
        "allocatedResources": allocated_resources,
        "resourceWaits": resource_waits,
        "recoveryEvidence": recovery_evidence,
        "recentEvents": recent_events,
        "eventHashChains": event_chains,
    }
    payload = _redact_sensitive(payload)
    payload["readiness"] = evaluate_execution_readiness(payload)
    payload["ok"] = bool(invariants["ok"]) and bool(payload["readiness"]["ok"])
    return payload


def _normalize_run_ids(run_ids: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in run_ids or []:
        run_id = str(value or "").strip()
        if run_id and run_id not in seen:
            seen.add(run_id)
            normalized.append(run_id)
    return normalized


def _active_leases(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT leases.run_id, leases.attempt_id, leases.lease_generation,
               leases.worker_id, leases.session_id, leases.slot_id,
               leases.heartbeat_at, leases.expires_at,
               attempts.state AS attempt_state,
               attempts.process_pid,
               attempts.process_group_id
        FROM run_leases AS leases
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = leases.attempt_id
        WHERE leases.state = 'active'
        ORDER BY leases.expires_at ASC, leases.run_id ASC
        """
    ).fetchall()
    return [
        {
            "runId": row["run_id"],
            "attemptId": row["attempt_id"],
            "leaseGeneration": int(row["lease_generation"]),
            "workerId": row["worker_id"],
            "sessionId": row["session_id"],
            "slotId": row["slot_id"],
            "heartbeatAt": row["heartbeat_at"],
            "expiresAt": row["expires_at"],
            "attemptState": row["attempt_state"],
            "processPid": row["process_pid"],
            "processGroupId": row["process_group_id"],
        }
        for row in rows
    ]


def _allocated_resources(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT allocations.run_id, allocations.attempt_id, allocations.worker_id,
               allocations.session_id, allocations.slot_id, allocations.cpu,
               allocations.memory_mb, allocations.disk_mb, allocations.gpu,
               allocations.created_at, leases.state AS lease_state,
               attempts.state AS attempt_state
        FROM run_resource_allocations AS allocations
        LEFT JOIN run_leases AS leases ON leases.attempt_id = allocations.attempt_id
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = allocations.attempt_id
        WHERE allocations.state = 'allocated'
        ORDER BY allocations.created_at ASC
        """
    ).fetchall()
    return [
        {
            "runId": row["run_id"],
            "attemptId": row["attempt_id"],
            "workerId": row["worker_id"],
            "sessionId": row["session_id"],
            "slotId": row["slot_id"],
            "cpu": int(row["cpu"]),
            "memoryMb": int(row["memory_mb"]),
            "diskMb": int(row["disk_mb"]),
            "gpu": int(row["gpu"]),
            "createdAt": row["created_at"],
            "leaseState": row["lease_state"],
            "attemptState": row["attempt_state"],
        }
        for row in rows
    ]


def _resource_waits(connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT job_id, run_id, queue_name, priority, wait_reason_json, attempt_count, updated_at
        FROM run_jobs
        WHERE state = 'queued'
          AND dead_lettered_at IS NULL
          AND wait_reason_json IS NOT NULL
          AND wait_reason_json <> ''
          AND wait_reason_json <> '{}'
        ORDER BY updated_at ASC, priority DESC
        """
    ).fetchall()
    return [
        {
            "jobId": row["job_id"],
            "runId": row["run_id"],
            "queueName": row["queue_name"],
            "priority": int(row["priority"]),
            "waitReason": _json_object(row["wait_reason_json"]),
            "attemptCount": int(row["attempt_count"]),
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def _recent_events(connection, *, run_ids: list[str], limit: int) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    params: list[Any] = []
    where = ""
    if run_ids:
        marks = ",".join("?" for _ in run_ids)
        where = f"WHERE run_id IN ({marks})"
        params.extend(run_ids)
    params.append(safe_limit)
    rows = connection.execute(
        f"""
        SELECT run_id, event_type, seq, schema_version, command_id, correlation_id,
               actor, payload_hash, event_hash, prev_event_hash, created_at
        FROM run_events
        {where}
        ORDER BY created_at DESC, seq DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "runId": row["run_id"],
            "eventType": row["event_type"],
            "sequence": int(row["seq"]),
            "schemaVersion": row["schema_version"],
            "commandId": row["command_id"],
            "correlationId": row["correlation_id"],
            "actor": row["actor"],
            "payloadHash": row["payload_hash"],
            "eventHash": row["event_hash"],
            "prevEventHash": row["prev_event_hash"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def _recovery_evidence(connection, *, run_ids: list[str], limit: int) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    params: list[Any] = []
    where = """
        WHERE event_type IN (
            'run_attempt_fenced',
            'run_job_requeued',
            'run_job_dead_lettered',
            'run_attempt_recovery_blocked',
            'run_control_plane_recovered'
        )
    """
    if run_ids:
        marks = ",".join("?" for _ in run_ids)
        where += f" AND run_id IN ({marks})"
        params.extend(run_ids)
    params.append(safe_limit)
    rows = connection.execute(
        f"""
        SELECT run_id, event_type, seq, stage, state_version, created_at, details_json
        FROM run_events
        {where}
        ORDER BY created_at DESC, seq DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "runId": row["run_id"],
            "eventType": row["event_type"],
            "sequence": int(row["seq"]),
            "stage": row["stage"],
            "stateVersion": int(row["state_version"]),
            "createdAt": row["created_at"],
            "payload": _event_payload(row["details_json"]),
        }
        for row in rows
    ]


def _invariants(
    connection,
    *,
    queue_metrics: dict[str, Any],
    worker_health: dict[str, Any],
    sqlite_metrics: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        _check_sqlite(sqlite_metrics),
        _check_allocations_have_active_leases(connection),
        _check_active_leases_have_running_attempts(connection),
        _check_running_slots_have_running_attempts(connection),
        _check_claimed_jobs_have_active_leases(connection),
        _check_worker_summary_matches_queue_metrics(queue_metrics, worker_health),
    ]
    failures = [check for check in checks if not check["ok"]]
    return {
        "ok": not failures,
        "failures": failures,
        "checks": checks,
    }


def _check_sqlite(sqlite_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "sqliteWalAndBusyTimeout",
        "ok": bool(sqlite_metrics.get("ok")),
        "details": {
            "journalMode": sqlite_metrics.get("journalMode"),
            "busyTimeoutMs": sqlite_metrics.get("busyTimeoutMs"),
        },
    }


def _check_allocations_have_active_leases(connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT allocations.run_id, allocations.attempt_id, allocations.slot_id,
               leases.state AS lease_state
        FROM run_resource_allocations AS allocations
        LEFT JOIN run_leases AS leases ON leases.attempt_id = allocations.attempt_id
        WHERE allocations.state = 'allocated'
          AND COALESCE(leases.state, '') <> 'active'
        ORDER BY allocations.created_at ASC
        """
    ).fetchall()
    return {
        "name": "allocatedResourcesHaveActiveLeases",
        "ok": not rows,
        "details": {"violations": [_row_identity(row) for row in rows]},
    }


def _check_active_leases_have_running_attempts(connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT leases.run_id, leases.attempt_id, leases.slot_id,
               attempts.state AS attempt_state
        FROM run_leases AS leases
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = leases.attempt_id
        WHERE leases.state = 'active'
          AND COALESCE(attempts.state, '') <> 'running'
        ORDER BY leases.expires_at ASC
        """
    ).fetchall()
    return {
        "name": "activeLeasesHaveRunningAttempts",
        "ok": not rows,
        "details": {"violations": [_row_identity(row) for row in rows]},
    }


def _check_running_slots_have_running_attempts(connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT slots.worker_id, slots.session_id, slots.slot_id, slots.current_attempt_id,
               attempts.run_id, attempts.state AS attempt_state
        FROM run_worker_slots AS slots
        LEFT JOIN run_attempts AS attempts ON attempts.attempt_id = slots.current_attempt_id
        WHERE slots.state = 'running'
          AND (slots.current_attempt_id IS NULL OR COALESCE(attempts.state, '') <> 'running')
        ORDER BY slots.worker_id ASC, slots.slot_id ASC
        """
    ).fetchall()
    return {
        "name": "runningSlotsHaveRunningAttempts",
        "ok": not rows,
        "details": {"violations": [_row_identity(row) for row in rows]},
    }


def _check_claimed_jobs_have_active_leases(connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT jobs.run_id, jobs.job_id, leases.attempt_id, leases.state AS lease_state
        FROM run_jobs AS jobs
        LEFT JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        WHERE jobs.state = 'claimed'
          AND COALESCE(leases.state, '') <> 'active'
        ORDER BY jobs.updated_at ASC
        """
    ).fetchall()
    return {
        "name": "claimedJobsHaveActiveLeases",
        "ok": not rows,
        "details": {"violations": [_row_identity(row) for row in rows]},
    }


def _check_worker_summary_matches_queue_metrics(
    queue_metrics: dict[str, Any],
    worker_health: dict[str, Any],
) -> dict[str, Any]:
    worker_claimed = int(worker_health.get("claimedJobs") or 0)
    metric_claimed = int(queue_metrics.get("claimedJobs") or 0)
    return {
        "name": "workerHealthMatchesQueueMetrics",
        "ok": worker_claimed == metric_claimed,
        "details": {
            "workerHealthClaimedJobs": worker_claimed,
            "queueMetricsClaimedJobs": metric_claimed,
        },
    }


def _row_identity(row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in row.keys()
        if row[key] is not None
    }


def _event_payload(value: str | None) -> dict[str, Any]:
    details = _json_object(value)
    payload = details.get("payload") if isinstance(details, dict) else None
    return payload if isinstance(payload, dict) else {}


def _json_object(value: str | None) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {"code": "INVALID_WAIT_REASON_JSON"}
    return parsed if isinstance(parsed, dict) else {"code": "INVALID_WAIT_REASON_JSON"}


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _sensitive_key(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str) and _sensitive_text(value):
        return "[REDACTED]"
    return value


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "")
    return any(
        marker in normalized
        for marker in (
            "authorization",
            "password",
            "privatekey",
            "secret",
            "token",
            "identityref",
            "keyfile",
        )
    )


def _sensitive_text(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("bearer ") or "authorization:" in lowered or "-----begin " in lowered
