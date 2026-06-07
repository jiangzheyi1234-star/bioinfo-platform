from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def register_run_worker(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    session_id: str,
    pid: int,
    hostname: str,
    queue_name: str = "default",
    concurrency_limit: int = 1,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _optional_text(now) or now_iso()
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO run_workers (
                worker_id, session_id, pid, hostname, state, queue_name,
                concurrency_limit, current_attempt_id, heartbeat_at,
                last_error_json, drain_requested_at, started_at, stopped_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                session_id = excluded.session_id,
                pid = excluded.pid,
                hostname = excluded.hostname,
                state = excluded.state,
                queue_name = excluded.queue_name,
                concurrency_limit = excluded.concurrency_limit,
                current_attempt_id = excluded.current_attempt_id,
                heartbeat_at = excluded.heartbeat_at,
                last_error_json = excluded.last_error_json,
                started_at = excluded.started_at,
                stopped_at = excluded.stopped_at,
                updated_at = excluded.updated_at
            """,
            (
                normalized_worker_id,
                _required_text(session_id, "SESSION_ID_REQUIRED"),
                int(pid),
                _required_text(hostname, "HOSTNAME_REQUIRED"),
                "idle",
                _required_text(queue_name, "QUEUE_NAME_REQUIRED"),
                max(1, int(concurrency_limit)),
                None,
                timestamp,
                "{}",
                None,
                timestamp,
                None,
                timestamp,
            ),
        )
        connection.commit()
    return fetch_run_worker(cfg, normalized_worker_id)


def heartbeat_run_worker(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    session_id: str,
    state: str,
    current_attempt_id: str | None = None,
    last_error: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _optional_text(now) or now_iso()
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    normalized_session_id = _required_text(session_id, "SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM run_workers WHERE worker_id = ?",
            (normalized_worker_id,),
        ).fetchone()
        if row is None:
            raise KeyError(normalized_worker_id)
        connection.execute(
            """
            UPDATE run_workers
            SET session_id = ?, state = ?, current_attempt_id = ?, heartbeat_at = ?,
                last_error_json = ?, updated_at = ?
            WHERE worker_id = ?
            """,
            (
                normalized_session_id,
                _required_text(state, "WORKER_STATE_REQUIRED"),
                _optional_text(current_attempt_id),
                timestamp,
                _stable_json(last_error or {}),
                timestamp,
                normalized_worker_id,
            ),
        )
        connection.commit()
    return fetch_run_worker(cfg, normalized_worker_id)


def request_run_worker_drain(
    cfg: RemoteRunnerConfig,
    worker_id: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _optional_text(now) or now_iso()
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM run_workers WHERE worker_id = ?",
            (normalized_worker_id,),
        ).fetchone()
        if row is None:
            raise KeyError(normalized_worker_id)
        connection.execute(
            """
            UPDATE run_workers
            SET drain_requested_at = COALESCE(drain_requested_at, ?), updated_at = ?
            WHERE worker_id = ?
            """,
            (timestamp, timestamp, normalized_worker_id),
        )
        connection.commit()
    return fetch_run_worker(cfg, normalized_worker_id)


def run_worker_is_draining(cfg: RemoteRunnerConfig, worker_id: str) -> bool:
    worker = fetch_run_worker(cfg, worker_id)
    return bool(worker and worker["draining"])


def mark_run_worker_stopped(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    session_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _optional_text(now) or now_iso()
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_workers
            SET session_id = ?, state = ?, current_attempt_id = NULL,
                stopped_at = ?, updated_at = ?
            WHERE worker_id = ?
            """,
            (
                _required_text(session_id, "SESSION_ID_REQUIRED"),
                "stopped",
                timestamp,
                timestamp,
                normalized_worker_id,
            ),
        )
        connection.commit()
    return fetch_run_worker(cfg, normalized_worker_id)


def fetch_run_worker(cfg: RemoteRunnerConfig, worker_id: str) -> dict[str, Any] | None:
    normalized_worker_id = _required_text(worker_id, "WORKER_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM run_workers WHERE worker_id = ?",
            (normalized_worker_id,),
        ).fetchone()
    return _worker_row_to_dict(row, now_text=now_iso()) if row is not None else None


def build_run_worker_health(cfg: RemoteRunnerConfig, *, now: str | None = None) -> dict[str, Any]:
    timestamp = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        worker_rows = connection.execute(
            "SELECT * FROM run_workers ORDER BY worker_id ASC",
        ).fetchall()
        queue_depth = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM run_jobs
            WHERE state = 'queued'
              AND available_at <= ?
              AND dead_lettered_at IS NULL
            """,
            (timestamp,),
        ).fetchone()["count"]
        claimed_jobs = connection.execute(
            "SELECT COUNT(*) AS count FROM run_jobs WHERE state = 'claimed'",
        ).fetchone()["count"]
    return {
        "queueDepth": int(queue_depth),
        "claimedJobs": int(claimed_jobs),
        "workers": [_worker_row_to_dict(row, now_text=timestamp) for row in worker_rows],
    }


def _worker_row_to_dict(row, *, now_text: str) -> dict[str, Any]:
    return {
        "workerId": row["worker_id"],
        "sessionId": row["session_id"],
        "pid": int(row["pid"]),
        "hostname": row["hostname"],
        "state": row["state"],
        "queueName": row["queue_name"],
        "concurrencyLimit": int(row["concurrency_limit"]),
        "currentAttemptId": row["current_attempt_id"],
        "heartbeatAt": row["heartbeat_at"],
        "heartbeatAgeSeconds": _age_seconds(row["heartbeat_at"], now_text),
        "lastError": _json_object(row["last_error_json"]),
        "drainRequestedAt": row["drain_requested_at"],
        "draining": row["drain_requested_at"] is not None,
        "startedAt": row["started_at"],
        "stoppedAt": row["stopped_at"],
        "updatedAt": row["updated_at"],
    }


def _age_seconds(value: str, now_text: str) -> int | None:
    try:
        heartbeat = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.strptime(now_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, int((now - heartbeat).total_seconds()))


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_object(value: str | None) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _required_text(value: str | None, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
