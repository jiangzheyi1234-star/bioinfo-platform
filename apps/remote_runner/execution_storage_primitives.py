from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any


def attempt_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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
        "workDir": row["work_dir"],
        "processPid": row["process_pid"],
        "processGroupId": row["process_group_id"],
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


def lease_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
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


def fetch_run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    return row


def fetch_attempt_row(connection: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise KeyError(attempt_id)
    return row


def required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def optional_positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
