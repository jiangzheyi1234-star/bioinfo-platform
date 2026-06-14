from __future__ import annotations

import logging
import os
import signal
import sqlite3
import subprocess
import time
from typing import Any

from .event_contracts import append_run_event_v2
from .storage_core import now_iso


LOGGER = logging.getLogger(__name__)


def fence_expired_attempt(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    generation: int,
    reason: str,
    occurred_at: str,
    run: sqlite3.Row,
) -> dict[str, Any]:
    existing = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if existing is None:
        return {"fenced": False, "reason": "attempt_not_found"}
    if existing["state"] == "fenced":
        return {"fenced": False, "reason": "already_fenced"}
    connection.execute(
        """
        UPDATE run_attempts
        SET state = ?, fenced_reason = ?, finished_at = COALESCE(finished_at, ?), updated_at = ?
        WHERE attempt_id = ?
        """,
        ("fenced", reason, occurred_at, occurred_at, attempt_id),
    )
    connection.execute(
        "UPDATE run_leases SET state = ?, updated_at = ? WHERE attempt_id = ?",
        ("expired" if reason == "lease_expired" else "fenced", occurred_at, attempt_id),
    )
    connection.execute(
        """
        UPDATE run_resource_allocations
        SET state = 'released',
            released_at = COALESCE(released_at, ?),
            updated_at = ?
        WHERE attempt_id = ? AND state = 'allocated'
        """,
        (occurred_at, occurred_at, attempt_id),
    )
    append_run_event_v2(
        connection,
        run_id=str(existing["run_id"]),
        event_type="run_attempt_fenced",
        stage="fence",
        state_version=int(run["state_version"]),
        message="Run attempt fenced by active reconciler.",
        request_id=str(run["request_id"]),
        payload={"attemptId": attempt_id, "leaseGeneration": int(generation), "reason": reason},
        occurred_at=occurred_at,
    )
    return {"fenced": True, "attemptId": attempt_id, "reason": reason}


def terminate_process_group(
    process_group_id: str | int | None,
    *,
    terminate_timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.05,
) -> dict[str, Any]:
    if process_group_id is None:
        return {"terminated": False, "reason": "no_process_group"}
    try:
        pgid = int(process_group_id)
    except (TypeError, ValueError):
        return {"terminated": False, "reason": "invalid_process_group_id"}
    if pgid <= 0:
        return {"terminated": False, "reason": "invalid_process_group_id"}
    if _uses_windows_process_groups():
        return _terminate_windows_process_tree(pgid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return {"terminated": False, "reason": "process_group_not_found"}
    except PermissionError:
        return {"terminated": False, "reason": "permission_denied"}
    except OSError as exc:
        return {"terminated": False, "reason": f"os_error: {exc}"}
    if _wait_for_process_group_exit(
        pgid,
        timeout_seconds=max(0.0, float(terminate_timeout_seconds)),
        poll_interval_seconds=max(0.001, float(poll_interval_seconds)),
    ):
        return {"terminated": True, "confirmedStopped": True, "processGroupId": pgid, "signal": "SIGTERM"}
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return {"terminated": True, "confirmedStopped": True, "processGroupId": pgid, "signal": "SIGTERM"}
    except PermissionError:
        return {"terminated": False, "reason": "permission_denied"}
    except OSError as exc:
        return {"terminated": False, "reason": f"os_error: {exc}"}
    confirmed = _wait_for_process_group_exit(
        pgid,
        timeout_seconds=max(0.0, float(terminate_timeout_seconds)),
        poll_interval_seconds=max(0.001, float(poll_interval_seconds)),
    )
    return {
        "terminated": confirmed,
        "confirmedStopped": confirmed,
        "processGroupId": pgid,
        "signal": "SIGKILL",
        **({} if confirmed else {"reason": "process_group_still_running"}),
    }


def _wait_for_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval_seconds)


def _uses_windows_process_groups() -> bool:
    return os.name == "nt"


def _terminate_windows_process_tree(process_id: int) -> dict[str, Any]:
    result = subprocess.run(
        ["taskkill", "/PID", str(process_id), "/T"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return {"terminated": True, "processGroupId": process_id}
    detail = str(result.stderr or result.stdout or "").strip()
    return {
        "terminated": False,
        "reason": "process_group_not_found" if result.returncode == 128 else "taskkill_failed",
        **({"detail": detail} if detail else {}),
    }


def requeue_retryable_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    run_id: str,
    retry_delay_seconds: int = 5,
    requeued_at: str | None = None,
) -> dict[str, Any]:
    timestamp = requeued_at or now_iso()
    job = connection.execute(
        "SELECT * FROM run_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        return {"requeued": False, "reason": "job_not_found"}
    if job["state"] != "claimed":
        return {"requeued": False, "reason": f"unexpected_state: {job['state']}"}
    attempt_count = int(job["attempt_count"])
    max_attempts = int(job["max_attempts"])
    if attempt_count >= max_attempts:
        return {"requeued": False, "reason": "max_attempts_exceeded"}
    from datetime import datetime, timedelta, timezone
    available_at = (
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        + timedelta(seconds=retry_delay_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection.execute(
        """
        UPDATE run_jobs
        SET state = ?, available_at = ?, updated_at = ?
        WHERE job_id = ?
        """,
        ("queued", available_at, timestamp, job_id),
    )
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is not None:
        append_run_event_v2(
            connection,
            run_id=run_id,
            event_type="run_job_requeued",
            stage="requeue",
            state_version=int(run["state_version"]),
            message="Run job re-queued for retry.",
            request_id=str(run["request_id"]),
            payload={
                "jobId": job_id,
                "attemptCount": attempt_count,
                "maxAttempts": max_attempts,
                "availableAt": available_at,
            },
            occurred_at=timestamp,
        )
    return {"requeued": True, "jobId": job_id, "availableAt": available_at}


def dead_letter_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    run_id: str,
    reason: str,
    dead_lettered_at: str | None = None,
) -> dict[str, Any]:
    timestamp = dead_lettered_at or now_iso()
    job = connection.execute(
        "SELECT * FROM run_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        return {"deadLettered": False, "reason": "job_not_found"}
    if job["dead_lettered_at"] is not None:
        return {"deadLettered": False, "reason": "already_dead_lettered"}
    connection.execute(
        """
        UPDATE run_jobs
        SET state = ?, dead_lettered_at = ?, updated_at = ?
        WHERE job_id = ?
        """,
        ("failed", timestamp, timestamp, job_id),
    )
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is not None:
        next_state_version = int(run["state_version"]) + 1
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?, last_updated_at = ?
            WHERE run_id = ?
            """,
            ("failed", "dead_letter", next_state_version, "Job dead-lettered after max retries.", timestamp, run_id),
        )
        append_run_event_v2(
            connection,
            run_id=run_id,
            event_type="run_job_dead_lettered",
            stage="dead_letter",
            state_version=next_state_version,
            message="Run job dead-lettered after exhausting retries.",
            request_id=str(run["request_id"]),
            payload={
                "jobId": job_id,
                "attemptCount": int(job["attempt_count"]),
                "maxAttempts": int(job["max_attempts"]),
                "reason": reason,
            },
            occurred_at=timestamp,
        )
    return {"deadLettered": True, "jobId": job_id, "reason": reason}
