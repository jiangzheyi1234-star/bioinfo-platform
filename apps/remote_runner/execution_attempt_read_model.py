from __future__ import annotations

from collections import Counter
from typing import Any

from .config import RemoteRunnerConfig
from .execution_policy import retry_policy_from_job, timeout_policy_from_job
from .execution_query_storage import require_run
from .storage_core import get_connection, now_iso


RUN_ATTEMPTS_SCHEMA_VERSION = "run-attempts.v1"


def fetch_run_attempts_read_model(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    run = require_run(cfg, run_id)
    generated_at = now_iso()
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        attempts = connection.execute(
            """
            SELECT *
            FROM run_attempts
            WHERE run_id = ?
            ORDER BY attempt_number ASC, lease_generation ASC, created_at ASC
            """,
            (run_id,),
        ).fetchall()
        lease = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()
        slots = connection.execute(
            """
            SELECT DISTINCT slots.*
            FROM run_worker_slots AS slots
            LEFT JOIN run_attempts AS attempts
              ON attempts.worker_id = slots.worker_id
             AND attempts.slot_id = slots.slot_id
            WHERE slots.current_attempt_id IN (SELECT attempt_id FROM run_attempts WHERE run_id = ?)
               OR attempts.run_id = ?
            ORDER BY slots.worker_id ASC, slots.slot_id ASC
            """,
            (run_id, run_id),
        ).fetchall()

    attempts_payload = [_attempt_projection(row) for row in attempts]
    current_lease = _lease_projection(lease) if lease is not None else None
    active_lease = current_lease if current_lease and current_lease["state"] == "active" else None
    slots_payload = [_slot_projection(row) for row in slots]
    return {
        "schemaVersion": RUN_ATTEMPTS_SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": generated_at,
        "run": _run_projection(run),
        "job": _job_projection(job) if job is not None else None,
        "attempts": attempts_payload,
        "currentLease": current_lease,
        "activeLease": active_lease,
        "slots": slots_payload,
        "summary": _summary(attempts_payload, active_lease=active_lease, slots=slots_payload),
        "redactionPolicy": {
            "workDirExposed": False,
            "processIdentifiersExposed": False,
            "commandPayloadExposed": False,
            "runSpecExposed": False,
            "slotErrorDetailsExposed": False,
        },
    }


def _run_projection(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": run.get("status"),
        "stage": run.get("stage"),
        "stateVersion": run.get("stateVersion"),
        "startedAt": run.get("startedAt"),
        "finishedAt": run.get("finishedAt"),
        "lastUpdatedAt": run.get("lastUpdatedAt"),
    }


def _job_projection(row: Any) -> dict[str, Any]:
    return {
        "jobId": row["job_id"],
        "runId": row["run_id"],
        "state": row["state"],
        "queueName": row["queue_name"],
        "priority": int(row["priority"]),
        "availableAt": row["available_at"],
        "waitReason": _wait_reason_projection(row["wait_reason_json"]),
        "attemptCount": int(row["attempt_count"]),
        "maxAttempts": int(row["max_attempts"]),
        "retryPolicy": retry_policy_from_job(row).as_dict(),
        "timeoutPolicy": timeout_policy_from_job(row).as_dict(),
        "deadLetteredAt": row["dead_lettered_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _attempt_projection(row: Any) -> dict[str, Any]:
    return {
        "attemptId": row["attempt_id"],
        "runId": row["run_id"],
        "jobId": row["job_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "attemptNumber": int(row["attempt_number"]),
        "state": row["state"],
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "slotId": row["slot_id"],
        "cancelRequestedAt": row["cancel_requested_at"],
        "killedAt": row["killed_at"],
        "outputAdoptionState": row["output_adoption_state"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "exitCode": row["exit_code"],
        "fencedReason": row["fenced_reason"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _lease_projection(row: Any) -> dict[str, Any]:
    return {
        "runId": row["run_id"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "slotId": row["slot_id"],
        "heartbeatAt": row["heartbeat_at"],
        "expiresAt": row["expires_at"],
        "state": row["state"],
        "updatedAt": row["updated_at"],
    }


def _slot_projection(row: Any) -> dict[str, Any]:
    return {
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "slotId": row["slot_id"],
        "state": row["state"],
        "currentAttemptId": row["current_attempt_id"],
        "heartbeatAt": row["heartbeat_at"],
        "startedAt": row["started_at"],
        "stoppedAt": row["stopped_at"],
        "updatedAt": row["updated_at"],
    }


def _wait_reason_projection(value: str | None) -> dict[str, Any]:
    reason = _json_object(value)
    if not reason:
        return {}
    projected: dict[str, Any] = {}
    for key in ("code", "slotId", "resource"):
        text = str(reason.get(key) or "").strip()
        if text:
            projected[key] = text
    for key in ("maxActiveSlots", "available", "requested"):
        if key in reason:
            projected[key] = _safe_int(reason.get(key))
    return projected


def _summary(
    attempts: list[dict[str, Any]],
    *,
    active_lease: dict[str, Any] | None,
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    by_state = Counter(str(item.get("state") or "unknown") for item in attempts)
    slot_states = Counter(str(item.get("state") or "unknown") for item in slots)
    latest = attempts[-1] if attempts else None
    return {
        "attemptCount": len(attempts),
        "attemptsByState": dict(sorted(by_state.items())),
        "slotCount": len(slots),
        "slotsByState": dict(sorted(slot_states.items())),
        "activeLeasePresent": active_lease is not None,
        "latestAttempt": _latest_attempt_summary(latest),
    }


def _latest_attempt_summary(attempt: dict[str, Any] | None) -> dict[str, Any] | None:
    if attempt is None:
        return None
    return {
        "attemptId": attempt["attemptId"],
        "attemptNumber": attempt["attemptNumber"],
        "leaseGeneration": attempt["leaseGeneration"],
        "state": attempt["state"],
        "startedAt": attempt["startedAt"],
        "finishedAt": attempt["finishedAt"],
        "exitCode": attempt["exitCode"],
    }


def _json_object(value: str | None) -> dict[str, Any]:
    import json

    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
