from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    heartbeat_tool_prepare_job,
    release_tool_prepare_worker_claim,
    require_active_tool_prepare_claim_for_connection,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
    fetch_tool_prepare_job,
)
from apps.remote_runner.tool_prepare_worker_lease import tool_prepare_worker_activity
from tests.helpers.reference_database import make_configured_remote_runner


CLAIM_TOKEN_HASH_DOMAIN = b"h2ometa.tool-prepare.claim-token.v1"


def test_worker_identity_is_immutable_and_unique_per_process_session() -> None:
    first = ToolPrepareWorkerIdentity.create("tool-worker")
    second = ToolPrepareWorkerIdentity.create("tool-worker")

    assert first.worker_id == second.worker_id == "tool-worker"
    assert first.process_pid == second.process_pid == os.getpid()
    assert first.hostname
    assert second.hostname
    assert first.session_id != second.session_id
    assert first.process_instance_id != second.process_instance_id
    with pytest.raises(FrozenInstanceError):
        first.session_id = "replacement"  # type: ignore[misc]


def test_claim_persists_only_domain_separated_token_hash(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    proof = _claim_proof(cfg, worker_id="worker-secret")

    expected_hash = "sha256:" + hashlib.sha256(
        CLAIM_TOKEN_HASH_DOMAIN + b"\x00" + proof.claim_token.encode("utf-8")
    ).hexdigest()
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT * FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        persisted_job = connection.execute(
            "SELECT claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
        event = connection.execute(
            "SELECT details_json FROM tool_prepare_job_events WHERE job_id = ? AND stage = 'claimed'",
            (job["jobId"],),
        ).fetchone()
        database_dump = "\n".join(connection.iterdump())

    assert attempt is not None
    assert attempt["claim_token_hash"] == expected_hash
    assert attempt["claim_token_hash"] != proof.claim_token
    assert persisted_job["claimed_by"] == proof.claim_owner
    assert persisted_job["attempts"] == proof.generation == 1
    assert proof.claim_token not in repr(proof)
    assert proof.claim_token not in database_dump
    assert len(proof.claim_token) == 64
    int(proof.claim_token, 16)
    event_details = json.loads(event["details_json"])
    assert event_details == {
        "attemptId": proof.attempt_id,
        "claimedUntil": "2099-06-07T10:00:30Z",
        "generation": 1,
        "processInstanceId": proof.process_instance_id,
        "sessionId": proof.session_id,
        "workerId": proof.worker_id,
    }
    assert proof.claim_owner not in event["details_json"]
    assert "claimToken" not in event["details_json"]
    assert "claim_token_hash" not in event["details_json"]


def test_same_worker_restart_cannot_adopt_open_attempt(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::seqkit", "name": "seqkit"})
    original_identity = ToolPrepareWorkerIdentity.create("same-logical-worker")
    restarted_identity = ToolPrepareWorkerIdentity.create("same-logical-worker")
    proof = _claim_proof(cfg, identity=original_identity, lease_seconds=10)

    replacement = claim_next_tool_prepare_job(
        cfg,
        identity=restarted_identity,
        now="2099-06-07T10:00:11Z",
        lease_seconds=10,
    )
    forged = replace(
        proof,
        session_id=restarted_identity.session_id,
        process_instance_id=restarted_identity.process_instance_id,
    )

    assert replacement is None
    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        heartbeat_tool_prepare_job(
            cfg,
            forged,
            now="2099-06-07T10:00:12Z",
            lease_seconds=10,
        )
    _assert_attempt_state(cfg, proof, state="active", heartbeat_at="2099-06-07T10:00:00Z")


def test_expired_open_attempt_is_not_reclaimed(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::multiqc", "name": "multiqc"})
    proof = _claim_proof(cfg, worker_id="worker-original", lease_seconds=10)

    reclaimed = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-replacement", session="replacement"),
        now="2099-06-07T10:00:11Z",
        lease_seconds=10,
    )

    assert reclaimed is None
    with get_connection(cfg) as connection:
        attempts = connection.execute(
            "SELECT attempt_id, generation, state FROM tool_prepare_attempts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchall()
        row = connection.execute(
            "SELECT status, attempts, claimed_by FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
    assert [dict(attempt) for attempt in attempts] == [
        {"attempt_id": proof.attempt_id, "generation": 1, "state": "active"}
    ]
    assert dict(row) == {"status": "running", "attempts": 1, "claimed_by": proof.claim_owner}


def test_exact_owner_can_heartbeat_after_ttl_without_new_generation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastp", "name": "fastp"})
    proof = _claim_proof(cfg, lease_seconds=10)

    result = heartbeat_tool_prepare_job(
        cfg,
        proof,
        now="2099-06-07T10:00:11Z",
        lease_seconds=10,
    )

    assert result == {
        "accepted": True,
        "attemptId": proof.attempt_id,
        "generation": 1,
        "claimedUntil": "2099-06-07T10:00:21Z",
    }
    _assert_attempt_state(cfg, proof, state="active", heartbeat_at="2099-06-07T10:00:11Z")


def test_connection_verifier_returns_exact_active_attempt_and_job(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::connection-proof", "name": "connection-proof"})
    proof = _claim_proof(cfg)

    with get_connection(cfg) as connection:
        verified = require_active_tool_prepare_claim_for_connection(connection, proof)
        with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
            require_active_tool_prepare_claim_for_connection(
                connection,
                replace(proof, claim_token="e" * 64),
            )

    assert verified["attempt"]["attempt_id"] == proof.attempt_id
    assert verified["attempt"]["generation"] == proof.generation
    assert verified["job"]["status"] == "running"
    assert verified["job"]["claimed_by"] == proof.claim_owner


@pytest.mark.parametrize(
    "forge",
    [
        lambda proof: replace(proof, claim_token="0" * 64),
        lambda proof: replace(proof, session_id="wrong-session"),
        lambda proof: replace(proof, process_instance_id="wrong-process"),
        lambda proof: replace(proof, generation=proof.generation + 1),
    ],
    ids=("wrong-token", "wrong-session", "wrong-process", "wrong-generation"),
)
def test_wrong_proof_cannot_heartbeat(
    tmp_path: Path,
    forge,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::wrong-proof", "name": "wrong-proof"})
    proof = _claim_proof(cfg, lease_seconds=30)

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        heartbeat_tool_prepare_job(
            cfg,
            forge(proof),
            now="2099-06-07T10:00:05Z",
            lease_seconds=30,
        )

    _assert_attempt_state(cfg, proof, state="active", heartbeat_at="2099-06-07T10:00:00Z")
    refreshed = fetch_tool_prepare_job(cfg, proof.job_id)
    assert refreshed is not None
    assert refreshed["lease"]["heartbeatAt"] == "2099-06-07T10:00:00Z"
    assert refreshed["lease"]["claimedUntil"] == "2099-06-07T10:00:30Z"


def test_cancelled_job_retains_open_attempt_until_exact_release(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::cancelled", "name": "cancelled"})
    proof = _claim_proof(cfg, worker_id="worker-cancel")

    cancelled = cancel_tool_prepare_job(cfg, proof.job_id)
    with get_connection(cfg) as connection:
        before_release = tool_prepare_worker_activity(connection, now="2099-06-07T10:00:01Z")
        attempt_before = connection.execute(
            "SELECT state, released_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()

    assert cancelled["status"] == "cancelled"
    assert cancelled["lease"]["claimedBy"] == proof.claim_owner
    assert before_release["activeClaims"] == 1
    assert dict(attempt_before) == {"state": "active", "released_at": None}
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:02Z",
    ) is True
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:03Z",
    ) is True

    with get_connection(cfg) as connection:
        after_release = tool_prepare_worker_activity(connection, now="2099-06-07T10:00:03Z")
        attempt_after = connection.execute(
            "SELECT state, outcome_status, released_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        job_after = connection.execute(
            "SELECT status, claimed_by, claimed_until, heartbeat_at FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
    assert after_release["activeClaims"] == 0
    assert dict(attempt_after) == {
        "state": "released",
        "outcome_status": "cancelled",
        "released_at": "2099-06-07T10:00:02Z",
    }
    assert dict(job_after) == {
        "status": "cancelled",
        "claimed_by": "",
        "claimed_until": None,
        "heartbeat_at": None,
    }


def test_wrong_proof_cannot_release_cancelled_attempt(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::release-proof", "name": "release-proof"})
    proof = _claim_proof(cfg)
    cancel_tool_prepare_job(cfg, proof.job_id)

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=replace(proof, claim_token="f" * 64),
            now="2099-06-07T10:00:02Z",
        )

    _assert_attempt_state(cfg, proof, state="active", heartbeat_at="2099-06-07T10:00:00Z")
    refreshed = fetch_tool_prepare_job(cfg, proof.job_id)
    assert refreshed is not None
    assert refreshed["lease"]["claimedBy"] == proof.claim_owner


def test_released_old_proof_is_fenced_after_next_generation_claim(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(
        cfg,
        {"id": "bioconda::next-generation", "name": "next-generation", "maxAttempts": 2},
    )
    first = _claim_proof(cfg, worker_id="worker-generation-1")
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET status = 'queued', stage = 'retry_wait', next_attempt_at = '2099-06-07T10:00:01Z'
            WHERE job_id = ?
            """,
            (first.job_id,),
        )
        connection.commit()
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=first,
        now="2099-06-07T10:00:01Z",
    ) is True
    second = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-generation-2", session="generation-2"),
        now="2099-06-07T10:00:02Z",
        lease_seconds=30,
    )
    assert second is not None
    assert second.generation == 2

    with pytest.raises(ToolPrepareClaimLostError, match="released proof is no longer current"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=first,
            now="2099-06-07T10:00:03Z",
        )

    _assert_attempt_state(cfg, second, state="active", heartbeat_at="2099-06-07T10:00:02Z")
    refreshed = fetch_tool_prepare_job(cfg, second.job_id)
    assert refreshed is not None
    assert refreshed["lease"]["claimedBy"] == second.claim_owner
    assert refreshed["lease"]["attempts"] == 2


def test_release_while_job_running_marks_recovery_required(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::running-release", "name": "running-release"})
    proof = _claim_proof(cfg, worker_id="worker-running")

    with pytest.raises(ToolPrepareClaimLostError, match="job has no durable outcome; recovery required"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=proof,
            now="2099-06-07T10:00:01Z",
        )

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, released_at, recovery_evidence_json FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        job = connection.execute(
            "SELECT status, claimed_by, claimed_until, heartbeat_at FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
        activity = tool_prepare_worker_activity(connection, now="2099-06-07T10:00:02Z")
    assert attempt["state"] == "recovery_required"
    assert attempt["released_at"] is None
    assert json.loads(attempt["recovery_evidence_json"]) == {
        "detectedAt": "2099-06-07T10:00:01Z",
        "jobStage": "claimed",
        "jobStatus": "running",
        "reason": "job has no durable outcome",
    }
    assert dict(job) == {
        "status": "running",
        "claimed_by": proof.claim_owner,
        "claimed_until": "2099-06-07T10:00:30Z",
        "heartbeat_at": "2099-06-07T10:00:00Z",
    }
    assert activity["activeClaims"] == 1
    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("replacement-worker", session="replacement"),
        now="2099-06-07T10:01:00Z",
    ) is None


def test_legacy_running_job_without_attempt_is_not_adopted(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::legacy-running", "name": "legacy-running"})
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET status = 'running', stage = 'dry_run', message = 'Legacy worker is running.'
            WHERE job_id = ?
            """,
            (job["jobId"],),
        )
        connection.commit()

    claimed = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("new-worker", session="new-session"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )

    assert claimed is None
    with get_connection(cfg) as connection:
        attempt_count = connection.execute(
            "SELECT COUNT(*) AS count FROM tool_prepare_attempts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()["count"]
        row = connection.execute(
            "SELECT status, stage, claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
    assert attempt_count == 0
    assert dict(row) == {
        "status": "running",
        "stage": "dry_run",
        "claimed_by": "",
        "attempts": 0,
    }


@pytest.mark.parametrize("lease_seconds", [0, -1])
def test_nonpositive_lease_is_rejected_without_mutation(tmp_path: Path, lease_seconds: int) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::invalid-lease", "name": "invalid-lease"})

    with pytest.raises(ValueError, match="TOOL_PREPARE_CLAIM_LEASE_INVALID"):
        claim_next_tool_prepare_job(
            cfg,
            identity=_identity("invalid-lease-worker"),
            now="2099-06-07T10:00:00Z",
            lease_seconds=lease_seconds,
        )

    with get_connection(cfg) as connection:
        attempt_count = connection.execute(
            "SELECT COUNT(*) AS count FROM tool_prepare_attempts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()["count"]
        row = connection.execute(
            "SELECT status, claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
    assert attempt_count == 0
    assert dict(row) == {"status": "queued", "claimed_by": "", "attempts": 0}


def _claim_proof(
    cfg,
    *,
    worker_id: str = "tool-worker",
    identity: ToolPrepareWorkerIdentity | None = None,
    lease_seconds: int = 30,
) -> ToolPrepareAttemptProof:
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=identity or _identity(worker_id),
        now="2099-06-07T10:00:00Z",
        lease_seconds=lease_seconds,
    )
    assert proof is not None
    return proof


def _identity(worker_id: str, *, session: str = "session-1") -> ToolPrepareWorkerIdentity:
    return ToolPrepareWorkerIdentity(
        worker_id=worker_id,
        session_id=session,
        process_instance_id=f"process-{session}",
        process_pid=os.getpid(),
        hostname="test-runner",
    )


def _assert_attempt_state(
    cfg,
    proof: ToolPrepareAttemptProof,
    *,
    state: str,
    heartbeat_at: str,
) -> None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT state, heartbeat_at, lease_expires_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
    assert row is not None
    assert row["state"] == state
    assert row["heartbeat_at"] == heartbeat_at
