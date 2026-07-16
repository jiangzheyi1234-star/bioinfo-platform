from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from .tool_prepare_claims import release_tool_prepare_worker_claim
from .tool_prepare_process_marker import (
    LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
    UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    validate_persisted_tool_prepare_process_marker,
)


def tool_prepare_worker_activity(connection, *, now: str) -> dict[str, Any]:
    timestamp = _timestamp(now)
    job_rows = connection.execute(
        """
        SELECT job_id, status, stage, claimed_by, claimed_until, heartbeat_at, attempts
        FROM tool_prepare_jobs
        ORDER BY job_id
        """
    ).fetchall()
    attempt_rows = connection.execute(
        """
        SELECT
            attempts.attempt_id,
            attempts.job_id AS attempt_job_id,
            attempts.generation AS attempt_generation,
            attempts.state AS attempt_state,
            attempts.outcome_status,
            attempts.claim_owner AS attempt_claim_owner,
            attempts.process_instance_id,
            attempts.process_pid,
            attempts.hostname,
            attempts.process_marker_schema,
            attempts.process_marker_json,
            attempts.process_marker_fingerprint,
            attempts.heartbeat_at AS attempt_heartbeat_at,
            attempts.lease_expires_at AS attempt_lease_expires_at,
            jobs.job_id AS projected_job_id,
            jobs.status AS job_status,
            jobs.stage AS job_stage,
            jobs.claimed_by AS job_claim_owner,
            jobs.claimed_until AS job_claimed_until,
            jobs.heartbeat_at AS job_heartbeat_at,
            jobs.attempts AS job_generation
        FROM tool_prepare_attempts AS attempts
        LEFT JOIN tool_prepare_jobs AS jobs ON jobs.job_id = attempts.job_id
        WHERE attempts.state IN ('active', 'recovery_required')
        ORDER BY attempts.job_id, attempts.generation, attempts.attempt_id
        """
    ).fetchall()
    claim_event_rows = connection.execute(
        """
        SELECT events.details_json
        FROM tool_prepare_job_events AS events
        JOIN tool_prepare_attempts AS attempts ON attempts.job_id = events.job_id
        WHERE events.stage = 'claimed'
          AND attempts.state IN ('active', 'recovery_required')
        ORDER BY events.created_at, events.event_id
        """
    ).fetchall()
    claim_event_fingerprints = _claim_event_process_marker_fingerprints(claim_event_rows)

    counts = {"queued": 0, "running": 0}
    for row in job_rows:
        status = str(row["status"] or "")
        if status in counts:
            counts[status] += 1

    active_attempt_count = sum(
        str(row["attempt_state"] or "") == "active" for row in attempt_rows
    )
    recovery_required_attempt_count = sum(
        str(row["attempt_state"] or "") == "recovery_required"
        for row in attempt_rows
    )
    expired_active_attempt_count = sum(
        str(row["attempt_state"] or "") == "active"
        and str(row["attempt_lease_expires_at"] or "") < timestamp
        for row in attempt_rows
    )
    open_attempt_count = len(attempt_rows)
    job_claim_projection_count = sum(
        bool(str(row["claimed_by"] or "")) for row in job_rows
    )
    projection_violations = _projection_violations(
        job_rows=job_rows,
        attempt_rows=attempt_rows,
        claim_event_fingerprints=claim_event_fingerprints,
    )
    process_identity_profiles = [
        _process_identity_evidence_profile(row)
        for row in attempt_rows
    ]

    return {
        "schemaVersion": "tool-prepare-activity.v1",
        **counts,
        "active": counts["queued"] + counts["running"],
        "activeClaims": open_attempt_count,
        "activeAttemptCount": active_attempt_count,
        "recoveryRequiredAttemptCount": recovery_required_attempt_count,
        "expiredActiveAttemptCount": expired_active_attempt_count,
        "openAttemptCount": open_attempt_count,
        "jobClaimProjectionCount": job_claim_projection_count,
        "systemdProcessIdentityAttemptCount": process_identity_profiles.count(
            SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE
        ),
        "linuxProcessIdentityAttemptCount": process_identity_profiles.count(
            LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE
        ),
        "unsupportedProcessIdentityAttemptCount": process_identity_profiles.count(
            UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE
        ),
        "invalidProcessIdentityAttemptCount": process_identity_profiles.count(None),
        "projectionMismatchCount": len(projection_violations),
        "projectionViolations": projection_violations,
    }


def _projection_violations(
    *,
    job_rows,
    attempt_rows,
    claim_event_fingerprints: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    open_job_ids = {
        str(row["attempt_job_id"] or "")
        for row in attempt_rows
    }
    for row in attempt_rows:
        attempt_id = str(row["attempt_id"] or "")
        if _process_identity_evidence_profile(row) is None:
            violations.append(_attempt_violation(row, "OPEN_ATTEMPT_PROCESS_MARKER_INVALID"))
        if claim_event_fingerprints.get(attempt_id) != (
            str(row["process_marker_fingerprint"] or ""),
        ):
            violations.append(
                _attempt_violation(row, "OPEN_ATTEMPT_PROCESS_MARKER_EVENT_MISMATCH")
            )
        if row["projected_job_id"] is None:
            violations.append(_attempt_violation(row, "OPEN_ATTEMPT_JOB_MISSING"))
            continue
        if int(row["attempt_generation"] or 0) != int(row["job_generation"] or 0):
            violations.append(
                _attempt_violation(row, "OPEN_ATTEMPT_GENERATION_MISMATCH")
            )
        if str(row["attempt_claim_owner"] or "") != str(row["job_claim_owner"] or ""):
            violations.append(_attempt_violation(row, "OPEN_ATTEMPT_OWNER_MISMATCH"))
        if row["attempt_heartbeat_at"] != row["job_heartbeat_at"]:
            violations.append(
                _attempt_violation(row, "OPEN_ATTEMPT_HEARTBEAT_MISMATCH")
            )
        if row["attempt_lease_expires_at"] != row["job_claimed_until"]:
            violations.append(_attempt_violation(row, "OPEN_ATTEMPT_LEASE_MISMATCH"))
        expected_outcome = _durable_job_outcome(row)
        if expected_outcome is not None and str(row["outcome_status"] or "") != expected_outcome:
            violations.append(_attempt_violation(row, "OPEN_ATTEMPT_OUTCOME_MISMATCH"))

    for row in job_rows:
        job_id = str(row["job_id"] or "")
        if str(row["claimed_by"] or "") and job_id not in open_job_ids:
            violations.append(
                {
                    "jobId": job_id,
                    "generation": int(row["attempts"] or 0),
                    "state": str(row["status"] or ""),
                    "reason": "JOB_CLAIM_WITHOUT_OPEN_ATTEMPT",
                }
            )
    return violations


def _claim_event_process_marker_fingerprints(rows) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for row in rows:
        try:
            details = json.loads(str(row["details_json"] or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(details, dict):
            continue
        attempt_id = str(details.get("attemptId") or "").strip()
        fingerprint = str(details.get("processMarkerFingerprint") or "").strip()
        if attempt_id:
            values.setdefault(attempt_id, []).append(fingerprint)
    return {attempt_id: tuple(fingerprints) for attempt_id, fingerprints in values.items()}


def _process_identity_evidence_profile(row) -> str | None:
    if str(row["process_marker_schema"] or "") != TOOL_PREPARE_PROCESS_MARKER_SCHEMA:
        return None
    try:
        marker = validate_persisted_tool_prepare_process_marker(
            marker_json=str(row["process_marker_json"] or ""),
            marker_fingerprint=str(row["process_marker_fingerprint"] or ""),
            expected_process_instance_id=str(row["process_instance_id"] or ""),
            expected_process_pid=int(row["process_pid"] or 0),
            expected_hostname=str(row["hostname"] or ""),
        )
    except (TypeError, ValueError):
        return None
    return marker.identity_evidence_profile


def _attempt_violation(row, reason: str) -> dict[str, Any]:
    return {
        "jobId": str(row["attempt_job_id"] or ""),
        "attemptId": str(row["attempt_id"] or ""),
        "generation": int(row["attempt_generation"] or 0),
        "state": str(row["attempt_state"] or ""),
        "reason": reason,
    }


def _durable_job_outcome(row) -> str | None:
    status = str(row["job_status"] or "")
    if status in {"succeeded", "failed", "cancelled", "waiting_resource", "exhausted"}:
        return status
    if status == "queued" and str(row["job_stage"] or "") == "retry_wait":
        return "retry_wait"
    return None


def _timestamp(value: str) -> str:
    timestamp = str(value or "").strip()
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("TOOL_PREPARE_ACTIVITY_TIMESTAMP_INVALID") from exc
    return timestamp


__all__ = ["release_tool_prepare_worker_claim", "tool_prepare_worker_activity"]
