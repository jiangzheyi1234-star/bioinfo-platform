from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_attempt_mutations import (
    mark_tool_prepare_job_worker_failure,
)
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
)
from apps.remote_runner.tool_prepare_worker_lease import tool_prepare_worker_activity
from tests.helpers.reference_database import make_configured_remote_runner


NOW = "2099-06-07T10:00:01Z"
SAFE_VIOLATION_FIELDS = {"jobId", "attemptId", "generation", "state", "reason"}


def test_activity_counts_active_attempt_from_ledger(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job, proof = _claimed_job(cfg, "active")

    activity = _activity(cfg, now=NOW)

    assert activity == {
        "schemaVersion": "tool-prepare-activity.v1",
        "queued": 0,
        "running": 1,
        "active": 1,
        "activeClaims": 1,
        "activeAttemptCount": 1,
        "recoveryRequiredAttemptCount": 0,
        "expiredActiveAttemptCount": 0,
        "openAttemptCount": 1,
        "jobClaimProjectionCount": 1,
        "projectionMismatchCount": 0,
        "projectionViolations": [],
    }
    assert job["jobId"] == proof.job_id


def test_expired_active_attempt_remains_an_open_claim(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _claimed_job(cfg, "expired", lease_seconds=30)

    activity = _activity(cfg, now="2099-06-07T10:00:31Z")

    assert activity["activeClaims"] == 1
    assert activity["activeAttemptCount"] == 1
    assert activity["expiredActiveAttemptCount"] == 1
    assert activity["openAttemptCount"] == 1
    assert activity["projectionMismatchCount"] == 0


def test_recovery_required_attempt_remains_open_without_counting_active(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, "recovery")

    with pytest.raises(
        ToolPrepareClaimLostError,
        match="job has no durable outcome; recovery required",
    ):
        release_tool_prepare_worker_claim(
            cfg,
            proof=proof,
            now="2099-06-07T10:00:01Z",
        )

    activity = _activity(cfg, now="2099-06-07T10:00:02Z")

    assert activity["activeClaims"] == 1
    assert activity["activeAttemptCount"] == 0
    assert activity["recoveryRequiredAttemptCount"] == 1
    assert activity["expiredActiveAttemptCount"] == 0
    assert activity["openAttemptCount"] == 1
    assert activity["projectionMismatchCount"] == 0


def test_released_attempt_is_not_open_even_when_history_remains(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, "released")
    cancel_tool_prepare_job(cfg, proof.job_id)
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:02Z",
    ) is True

    activity = _activity(cfg, now="2099-06-07T10:00:03Z")

    assert activity["active"] == 0
    assert activity["activeClaims"] == 0
    assert activity["activeAttemptCount"] == 0
    assert activity["recoveryRequiredAttemptCount"] == 0
    assert activity["openAttemptCount"] == 0
    assert activity["jobClaimProjectionCount"] == 0
    assert activity["projectionMismatchCount"] == 0


def test_orphan_open_attempt_is_counted_and_reported(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, "orphan")
    with get_connection(cfg) as connection:
        connection.execute(
            "DELETE FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        )
        connection.commit()

    activity = _activity(cfg, now=NOW)

    assert activity["activeClaims"] == 1
    assert activity["openAttemptCount"] == 1
    assert activity["jobClaimProjectionCount"] == 0
    _assert_single_violation(
        activity,
        reason="OPEN_ATTEMPT_JOB_MISSING",
        job_id=proof.job_id,
        attempt_id=proof.attempt_id,
    )


def test_phantom_job_claim_without_open_attempt_is_reported(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::phantom", "name": "phantom"},
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET claimed_by = 'phantom-owner',
                claimed_until = '2099-06-07T10:00:30Z',
                heartbeat_at = '2099-06-07T10:00:00Z',
                attempts = 1
            WHERE job_id = ?
            """,
            (job["jobId"],),
        )
        connection.commit()

    activity = _activity(cfg, now=NOW)

    assert activity["queued"] == 1
    assert activity["activeClaims"] == 0
    assert activity["openAttemptCount"] == 0
    assert activity["jobClaimProjectionCount"] == 1
    _assert_single_violation(
        activity,
        reason="JOB_CLAIM_WITHOUT_OPEN_ATTEMPT",
        job_id=job["jobId"],
        attempt_id=None,
    )


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("attempts", 2, "OPEN_ATTEMPT_GENERATION_MISMATCH"),
        ("claimed_by", "different-owner", "OPEN_ATTEMPT_OWNER_MISMATCH"),
        (
            "heartbeat_at",
            "2099-06-07T10:00:01Z",
            "OPEN_ATTEMPT_HEARTBEAT_MISMATCH",
        ),
        (
            "claimed_until",
            "2099-06-07T10:00:31Z",
            "OPEN_ATTEMPT_LEASE_MISMATCH",
        ),
    ],
)
def test_open_attempt_projection_mismatch_is_reported(
    tmp_path: Path,
    column: str,
    value: object,
    reason: str,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, f"projection-{column}")
    with get_connection(cfg) as connection:
        connection.execute(
            f"UPDATE tool_prepare_jobs SET {column} = ? WHERE job_id = ?",
            (value, proof.job_id),
        )
        connection.commit()

    activity = _activity(cfg, now=NOW)

    assert activity["activeClaims"] == 1
    assert activity["openAttemptCount"] == 1
    assert activity["jobClaimProjectionCount"] == 1
    _assert_single_violation(
        activity,
        reason=reason,
        job_id=proof.job_id,
        attempt_id=proof.attempt_id,
    )


@pytest.mark.parametrize("durable_state", ["terminal", "retry_wait"])
def test_durable_job_outcome_must_match_open_attempt(
    tmp_path: Path,
    durable_state: str,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, f"outcome-{durable_state}")
    if durable_state == "terminal":
        cancel_tool_prepare_job(cfg, proof.job_id)
    else:
        mark_tool_prepare_job_worker_failure(
            cfg,
            proof,
            code="WORKER_FAILED",
            message="worker failed",
            now="2099-06-07T10:00:01Z",
        )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE tool_prepare_attempts
            SET outcome_status = 'wrong-outcome'
            WHERE attempt_id = ?
            """,
            (proof.attempt_id,),
        )
        connection.commit()

    activity = _activity(cfg, now="2099-06-07T10:00:02Z")

    assert activity["activeClaims"] == 1
    _assert_single_violation(
        activity,
        reason="OPEN_ATTEMPT_OUTCOME_MISMATCH",
        job_id=proof.job_id,
        attempt_id=proof.attempt_id,
    )


def test_activity_never_exposes_claim_secrets_or_owner(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _job, proof = _claimed_job(cfg, "secret")
    with get_connection(cfg) as connection:
        claim_token_hash = str(
            connection.execute(
                """
                SELECT claim_token_hash
                FROM tool_prepare_attempts
                WHERE attempt_id = ?
                """,
                (proof.attempt_id,),
            ).fetchone()["claim_token_hash"]
        )
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET claimed_by = 'different-secret-owner'
            WHERE job_id = ?
            """,
            (proof.job_id,),
        )
        activity = tool_prepare_worker_activity(connection, now=NOW)

    serialized = json.dumps(activity, ensure_ascii=False, sort_keys=True)
    assert proof.claim_owner not in serialized
    assert proof.claim_token not in serialized
    assert claim_token_hash not in serialized
    assert "different-secret-owner" not in serialized
    assert "claim_owner" not in serialized
    assert "claimToken" not in serialized
    assert "claim_token" not in serialized
    for violation in activity["projectionViolations"]:
        assert set(violation) <= SAFE_VIOLATION_FIELDS


def _claimed_job(
    cfg,
    name: str,
    *,
    lease_seconds: int = 30,
) -> tuple[dict, ToolPrepareAttemptProof]:
    job = create_tool_prepare_job(
        cfg,
        {"id": f"bioconda::{name}", "name": name},
    )
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=ToolPrepareWorkerIdentity(
            worker_id=f"worker-{name}",
            session_id=f"session-{name}",
            process_instance_id=f"process-{name}",
            process_pid=os.getpid(),
            hostname="activity-test-runner",
        ),
        now="2099-06-07T10:00:00Z",
        lease_seconds=lease_seconds,
    )
    assert proof is not None
    assert proof.job_id == job["jobId"]
    return job, proof


def _activity(cfg, *, now: str) -> dict:
    with get_connection(cfg) as connection:
        return tool_prepare_worker_activity(connection, now=now)


def _assert_single_violation(
    activity: dict,
    *,
    reason: str,
    job_id: str,
    attempt_id: str | None,
) -> None:
    assert activity["projectionMismatchCount"] == 1
    assert len(activity["projectionViolations"]) == 1
    violation = activity["projectionViolations"][0]
    assert violation["reason"] == reason
    assert violation["jobId"] == job_id
    if attempt_id is None:
        assert "attemptId" not in violation
    else:
        assert violation["attemptId"] == attempt_id
    assert set(violation) <= SAFE_VIOLATION_FIELDS
