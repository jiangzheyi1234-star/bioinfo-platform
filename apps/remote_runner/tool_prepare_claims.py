from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import secrets
import socket
from typing import Any
import uuid

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


TOOL_PREPARE_CLAIM_LOST = "TOOL_PREPARE_CLAIM_LOST"
_CLAIM_TOKEN_HASH_DOMAIN = b"h2ometa.tool-prepare.claim-token.v1"
_OPEN_ATTEMPT_STATES = ("active", "recovery_required")
_RELEASABLE_TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "waiting_resource",
    "exhausted",
}


class ToolPrepareClaimLostError(RuntimeError):
    """Raised when a worker can no longer prove ownership of a prepare attempt."""

    code = TOOL_PREPARE_CLAIM_LOST

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "claim proof rejected")
        super().__init__(f"{self.code}: {self.reason}")


@dataclass(frozen=True, slots=True)
class ToolPrepareWorkerIdentity:
    worker_id: str
    session_id: str
    process_instance_id: str
    process_pid: int
    hostname: str

    @classmethod
    def create(cls, worker_id: str) -> ToolPrepareWorkerIdentity:
        normalized_worker_id = _required_text(worker_id, "TOOL_PREPARE_WORKER_ID_REQUIRED")
        hostname = _required_text(socket.gethostname(), "TOOL_PREPARE_WORKER_HOSTNAME_REQUIRED")
        process_pid = os.getpid()
        if process_pid <= 0:
            raise ValueError("TOOL_PREPARE_WORKER_PID_INVALID")
        return cls(
            worker_id=normalized_worker_id,
            session_id=f"toolprep_session_{secrets.token_hex(16)}",
            process_instance_id=f"toolprep_process_{secrets.token_hex(16)}",
            process_pid=process_pid,
            hostname=hostname,
        )


@dataclass(frozen=True, slots=True)
class ToolPrepareAttemptProof:
    job_id: str
    attempt_id: str
    generation: int
    worker_id: str
    session_id: str
    process_instance_id: str
    process_pid: int
    hostname: str
    claim_owner: str
    claim_token: str = field(repr=False)


def claim_next_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    *,
    identity: ToolPrepareWorkerIdentity,
    now: str | None = None,
    lease_seconds: int = 300,
) -> ToolPrepareAttemptProof | None:
    # Lazy import avoids the diagnostics -> worker lease -> claims -> lifecycle guard cycle.
    from .execution_lifecycle_guard import read_execution_lifecycle_maintenance_for_connection

    claimed_at = _timestamp(now)
    claimed_until = _add_seconds(claimed_at, lease_seconds)
    normalized_identity = _require_identity(identity)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if read_execution_lifecycle_maintenance_for_connection(connection, now=claimed_at) is not None:
                connection.commit()
                return None
            row = connection.execute(
                """
                SELECT jobs.*
                FROM tool_prepare_jobs AS jobs
                WHERE jobs.status = 'queued'
                  AND COALESCE(jobs.next_attempt_at, jobs.created_at) <= ?
                  AND jobs.attempts < jobs.max_attempts
                  AND COALESCE(jobs.claimed_by, '') = ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tool_prepare_attempts AS attempts
                      WHERE attempts.job_id = jobs.job_id
                        AND attempts.state IN ('active', 'recovery_required')
                  )
                ORDER BY jobs.created_at ASC, jobs.job_id ASC
                LIMIT 1
                """,
                (claimed_at,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            proof = _new_attempt_proof(
                job_id=str(row["job_id"]),
                generation=int(row["attempts"] or 0) + 1,
                identity=normalized_identity,
            )
            updated = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET status = 'running',
                    stage = 'claimed',
                    message = 'Prepare job claimed by worker.',
                    claimed_by = ?,
                    claimed_until = ?,
                    heartbeat_at = ?,
                    attempts = ?,
                    next_attempt_at = NULL,
                    exhausted_at = NULL,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE job_id = ?
                  AND status = 'queued'
                  AND attempts = ?
                  AND attempts < max_attempts
                  AND COALESCE(claimed_by, '') = ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tool_prepare_attempts
                      WHERE job_id = ?
                        AND state IN ('active', 'recovery_required')
                  )
                """,
                (
                    proof.claim_owner,
                    claimed_until,
                    claimed_at,
                    proof.generation,
                    claimed_at,
                    claimed_at,
                    proof.job_id,
                    proof.generation - 1,
                    proof.job_id,
                ),
            )
            if updated.rowcount != 1:
                raise ToolPrepareClaimLostError("claim compare-and-set failed")
            connection.execute(
                """
                INSERT INTO tool_prepare_attempts (
                    attempt_id, job_id, generation, state, outcome_status,
                    worker_id, session_id, process_pid, hostname, process_instance_id,
                    claim_owner, claim_token_hash, claimed_at, heartbeat_at,
                    lease_expires_at, released_at, created_at, updated_at,
                    last_error_json, recovery_evidence_json
                ) VALUES (?, ?, ?, 'active', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, '{}', '{}')
                """,
                (
                    proof.attempt_id,
                    proof.job_id,
                    proof.generation,
                    proof.worker_id,
                    proof.session_id,
                    proof.process_pid,
                    proof.hostname,
                    proof.process_instance_id,
                    proof.claim_owner,
                    _claim_token_hash(proof.claim_token),
                    claimed_at,
                    claimed_at,
                    claimed_until,
                    claimed_at,
                    claimed_at,
                ),
            )
            _insert_claim_event(connection, proof=proof, claimed_at=claimed_at, claimed_until=claimed_until)
            connection.commit()
            return proof
        except Exception:
            connection.rollback()
            raise


def heartbeat_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    *,
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    heartbeat_at = _timestamp(now)
    claimed_until = _add_seconds(heartbeat_at, lease_seconds)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            require_active_tool_prepare_claim_for_connection(connection, proof)
            attempt_update = connection.execute(
                """
                UPDATE tool_prepare_attempts
                SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE attempt_id = ?
                  AND job_id = ?
                  AND generation = ?
                  AND state = 'active'
                  AND worker_id = ?
                  AND session_id = ?
                  AND process_instance_id = ?
                  AND process_pid = ?
                  AND hostname = ?
                  AND claim_owner = ?
                  AND claim_token_hash = ?
                """,
                (
                    heartbeat_at,
                    claimed_until,
                    heartbeat_at,
                    proof.attempt_id,
                    proof.job_id,
                    proof.generation,
                    proof.worker_id,
                    proof.session_id,
                    proof.process_instance_id,
                    proof.process_pid,
                    proof.hostname,
                    proof.claim_owner,
                    _claim_token_hash(proof.claim_token),
                ),
            )
            job_update = connection.execute(
                """
                UPDATE tool_prepare_jobs
                SET heartbeat_at = ?, claimed_until = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running' AND claimed_by = ? AND attempts = ?
                """,
                (
                    heartbeat_at,
                    claimed_until,
                    heartbeat_at,
                    proof.job_id,
                    proof.claim_owner,
                    proof.generation,
                ),
            )
            if attempt_update.rowcount != 1 or job_update.rowcount != 1:
                raise ToolPrepareClaimLostError("heartbeat compare-and-set failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "accepted": True,
        "attemptId": proof.attempt_id,
        "generation": proof.generation,
        "claimedUntil": claimed_until,
    }


def release_tool_prepare_worker_claim(
    cfg: RemoteRunnerConfig,
    *,
    proof: ToolPrepareAttemptProof,
    now: str | None = None,
) -> bool:
    released_at = _timestamp(now)
    release_error: ToolPrepareClaimLostError | None = None
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            attempt = _require_exact_attempt(connection, proof)
            attempt_state = str(attempt["state"])
            if attempt_state == "released":
                released_job = connection.execute(
                    """
                    SELECT attempts, claimed_by, claimed_until, heartbeat_at
                    FROM tool_prepare_jobs
                    WHERE job_id = ?
                    """,
                    (proof.job_id,),
                ).fetchone()
                if (
                    released_job is None
                    or int(released_job["attempts"] or 0) != proof.generation
                    or str(released_job["claimed_by"] or "") != ""
                    or released_job["claimed_until"] is not None
                    or released_job["heartbeat_at"] is not None
                ):
                    raise ToolPrepareClaimLostError("released proof is no longer current")
                connection.commit()
                return True
            if attempt_state != "active":
                raise ToolPrepareClaimLostError("attempt is not releasable")

            job = connection.execute(
                "SELECT status, stage, claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
                (proof.job_id,),
            ).fetchone()
            if job is None:
                raise ToolPrepareClaimLostError("prepare job is missing")
            status = str(job["status"] or "")
            stage = str(job["stage"] or "")
            projection_matches = (
                str(job["claimed_by"] or "") == proof.claim_owner
                and int(job["attempts"] or 0) == proof.generation
            )
            releasable = status in _RELEASABLE_TERMINAL_STATUSES or (
                status == "queued" and stage == "retry_wait"
            )
            if not projection_matches or not releasable:
                reason = "claim projection mismatch" if not projection_matches else "job has no durable outcome"
                _mark_attempt_recovery_required(
                    connection,
                    proof=proof,
                    detected_at=released_at,
                    reason=reason,
                    job_status=status,
                    job_stage=stage,
                )
                connection.commit()
                release_error = ToolPrepareClaimLostError(f"{reason}; recovery required")
            else:
                outcome_status = stage if status == "queued" else status
                attempt_update = connection.execute(
                    """
                    UPDATE tool_prepare_attempts
                    SET state = 'released', outcome_status = ?, released_at = ?, updated_at = ?
                    WHERE attempt_id = ?
                      AND job_id = ?
                      AND generation = ?
                      AND state = 'active'
                      AND worker_id = ?
                      AND session_id = ?
                      AND process_instance_id = ?
                      AND process_pid = ?
                      AND hostname = ?
                      AND claim_owner = ?
                      AND claim_token_hash = ?
                    """,
                    (
                        outcome_status,
                        released_at,
                        released_at,
                        proof.attempt_id,
                        proof.job_id,
                        proof.generation,
                        proof.worker_id,
                        proof.session_id,
                        proof.process_instance_id,
                        proof.process_pid,
                        proof.hostname,
                        proof.claim_owner,
                        _claim_token_hash(proof.claim_token),
                    ),
                )
                job_update = connection.execute(
                    """
                    UPDATE tool_prepare_jobs
                    SET claimed_by = '', claimed_until = NULL, heartbeat_at = NULL, updated_at = ?
                    WHERE job_id = ? AND claimed_by = ? AND attempts = ?
                    """,
                    (released_at, proof.job_id, proof.claim_owner, proof.generation),
                )
                if attempt_update.rowcount != 1 or job_update.rowcount != 1:
                    raise ToolPrepareClaimLostError("release compare-and-set failed")
                connection.commit()
        except Exception:
            connection.rollback()
            raise
    if release_error is not None:
        raise release_error
    return True


def require_active_tool_prepare_claim_for_connection(
    connection,
    proof: ToolPrepareAttemptProof,
    *,
    required_status: str = "running",
) -> dict[str, Any]:
    """Validate an attempt proof inside the caller's current database transaction."""

    attempt = _require_exact_attempt(connection, proof)
    if str(attempt["state"]) != "active":
        raise ToolPrepareClaimLostError("attempt is not active")
    job = _require_current_job_projection(
        connection,
        proof,
        required_status=required_status,
    )
    return {"attempt": attempt, "job": job}


def _new_attempt_proof(
    *,
    job_id: str,
    generation: int,
    identity: ToolPrepareWorkerIdentity,
) -> ToolPrepareAttemptProof:
    return ToolPrepareAttemptProof(
        job_id=job_id,
        attempt_id=f"toolprep_attempt_{uuid.uuid4().hex}",
        generation=generation,
        worker_id=identity.worker_id,
        session_id=identity.session_id,
        process_instance_id=identity.process_instance_id,
        process_pid=identity.process_pid,
        hostname=identity.hostname,
        claim_owner=f"toolprep_owner_{secrets.token_hex(16)}",
        claim_token=secrets.token_hex(32),
    )


def _require_exact_attempt(connection, proof: ToolPrepareAttemptProof):
    if not isinstance(proof, ToolPrepareAttemptProof):
        raise ToolPrepareClaimLostError("attempt proof is required")
    row = connection.execute(
        "SELECT * FROM tool_prepare_attempts WHERE attempt_id = ?",
        (proof.attempt_id,),
    ).fetchone()
    if row is None:
        raise ToolPrepareClaimLostError("attempt proof rejected")
    expected_values = {
        "job_id": proof.job_id,
        "generation": proof.generation,
        "worker_id": proof.worker_id,
        "session_id": proof.session_id,
        "process_instance_id": proof.process_instance_id,
        "process_pid": proof.process_pid,
        "hostname": proof.hostname,
        "claim_owner": proof.claim_owner,
    }
    for column, expected in expected_values.items():
        actual = int(row[column]) if column in {"generation", "process_pid"} else str(row[column])
        if actual != expected:
            raise ToolPrepareClaimLostError("attempt proof rejected")
    if not hmac.compare_digest(str(row["claim_token_hash"]), _claim_token_hash(proof.claim_token)):
        raise ToolPrepareClaimLostError("attempt proof rejected")
    return row


def _require_current_job_projection(
    connection,
    proof: ToolPrepareAttemptProof,
    *,
    required_status: str,
):
    row = connection.execute(
        "SELECT status, claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
        (proof.job_id,),
    ).fetchone()
    if (
        row is None
        or str(row["status"] or "") != required_status
        or str(row["claimed_by"] or "") != proof.claim_owner
        or int(row["attempts"] or 0) != proof.generation
    ):
        raise ToolPrepareClaimLostError("prepare job claim projection rejected")
    return row


def _mark_attempt_recovery_required(
    connection,
    *,
    proof: ToolPrepareAttemptProof,
    detected_at: str,
    reason: str,
    job_status: str,
    job_stage: str,
) -> None:
    evidence = {
        "detectedAt": detected_at,
        "jobStage": job_stage,
        "jobStatus": job_status,
        "reason": reason,
    }
    updated = connection.execute(
        """
        UPDATE tool_prepare_attempts
        SET state = 'recovery_required', recovery_evidence_json = ?, updated_at = ?
        WHERE attempt_id = ?
          AND job_id = ?
          AND generation = ?
          AND state = 'active'
          AND worker_id = ?
          AND session_id = ?
          AND process_instance_id = ?
          AND process_pid = ?
          AND hostname = ?
          AND claim_owner = ?
          AND claim_token_hash = ?
        """,
        (
            json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            detected_at,
            proof.attempt_id,
            proof.job_id,
            proof.generation,
            proof.worker_id,
            proof.session_id,
            proof.process_instance_id,
            proof.process_pid,
            proof.hostname,
            proof.claim_owner,
            _claim_token_hash(proof.claim_token),
        ),
    )
    if updated.rowcount != 1:
        raise ToolPrepareClaimLostError("recovery transition compare-and-set failed")


def _insert_claim_event(
    connection,
    *,
    proof: ToolPrepareAttemptProof,
    claimed_at: str,
    claimed_until: str,
) -> None:
    details = {
        "attemptId": proof.attempt_id,
        "claimedUntil": claimed_until,
        "generation": proof.generation,
        "processInstanceId": proof.process_instance_id,
        "sessionId": proof.session_id,
        "workerId": proof.worker_id,
    }
    connection.execute(
        """
        INSERT INTO tool_prepare_job_events (
            event_id, job_id, stage, level, message, details_json, created_at
        ) VALUES (?, ?, 'claimed', 'info', 'Prepare job claimed by worker.', ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            proof.job_id,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            claimed_at,
        ),
    )


def _claim_token_hash(claim_token: str) -> str:
    token = _required_text(claim_token, "TOOL_PREPARE_CLAIM_TOKEN_REQUIRED")
    digest = hashlib.sha256(_CLAIM_TOKEN_HASH_DOMAIN + b"\x00" + token.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _require_identity(identity: ToolPrepareWorkerIdentity) -> ToolPrepareWorkerIdentity:
    if not isinstance(identity, ToolPrepareWorkerIdentity):
        raise ValueError("TOOL_PREPARE_WORKER_IDENTITY_REQUIRED")
    _required_text(identity.worker_id, "TOOL_PREPARE_WORKER_ID_REQUIRED")
    _required_text(identity.session_id, "TOOL_PREPARE_WORKER_SESSION_REQUIRED")
    _required_text(identity.process_instance_id, "TOOL_PREPARE_PROCESS_INSTANCE_REQUIRED")
    _required_text(identity.hostname, "TOOL_PREPARE_WORKER_HOSTNAME_REQUIRED")
    if identity.process_pid <= 0:
        raise ValueError("TOOL_PREPARE_WORKER_PID_INVALID")
    return identity


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _timestamp(value: str | None) -> str:
    timestamp = str(value or now_iso()).strip()
    try:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("TOOL_PREPARE_CLAIM_TIMESTAMP_INVALID") from exc
    return timestamp


def _add_seconds(value: str, seconds: int) -> str:
    try:
        safe_seconds = int(seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("TOOL_PREPARE_CLAIM_LEASE_INVALID") from exc
    if safe_seconds <= 0:
        raise ValueError("TOOL_PREPARE_CLAIM_LEASE_INVALID")
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (instant + timedelta(seconds=safe_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "TOOL_PREPARE_CLAIM_LOST",
    "ToolPrepareAttemptProof",
    "ToolPrepareClaimLostError",
    "ToolPrepareWorkerIdentity",
    "claim_next_tool_prepare_job",
    "heartbeat_tool_prepare_job",
    "require_active_tool_prepare_claim_for_connection",
    "release_tool_prepare_worker_claim",
]
