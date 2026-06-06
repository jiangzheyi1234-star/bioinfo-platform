from __future__ import annotations

from typing import Any


def queued_job_observation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "run_job_claimable_observed",
        "runId": row["run_id"],
        "jobId": row["job_id"],
    }


def expired_lease_observation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "run_lease_expired_observed",
        "runId": row["run_id"],
        "jobId": row["job_id"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "expiresAt": row["expires_at"],
    }


def clock_jump_observation(*, expired_lease_count: int, threshold: int) -> dict[str, Any] | None:
    if expired_lease_count < threshold:
        return None
    return {
        "type": "clock_jump_suspected",
        "expiredLeaseCount": expired_lease_count,
        "threshold": threshold,
    }
