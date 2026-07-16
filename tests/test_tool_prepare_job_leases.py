from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_attempt_mutations import mark_tool_prepare_job_worker_failure
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    heartbeat_tool_prepare_job,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
    fetch_tool_prepare_job,
)
from tests.helpers.tool_prepare_identity import make_unverifiable_tool_prepare_worker_identity


def test_claim_tool_prepare_job_sets_lease_and_attempt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})

    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-a"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )

    assert proof is not None
    claimed = fetch_tool_prepare_job(cfg, job["jobId"])
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["stage"] == "claimed"
    assert claimed["lease"] == {
        "claimedBy": proof.claim_owner,
        "claimedUntil": "2099-06-07T10:00:30Z",
        "heartbeatAt": "2099-06-07T10:00:00Z",
        "attempts": 1,
        "maxAttempts": 3,
        "nextAttemptAt": None,
        "exhaustedAt": None,
    }
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT attempt_id, generation, state, worker_id, session_id, claim_token_hash FROM tool_prepare_attempts",
        ).fetchone()
        database_dump = "\n".join(connection.iterdump())
    assert dict(attempt) == {
        "attempt_id": proof.attempt_id,
        "generation": 1,
        "state": "active",
        "worker_id": "worker-a",
        "session_id": proof.session_id,
        "claim_token_hash": attempt["claim_token_hash"],
    }
    assert proof.claim_token not in repr(proof)
    assert proof.claim_token not in database_dump


def test_expired_running_tool_prepare_job_fails_closed_without_reclaim(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    first = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-a", session="first"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert first is not None

    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b", session="before-expiry"),
        now="2099-06-07T10:00:05Z",
        lease_seconds=10,
    ) is None
    reclaimed = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b", session="after-expiry"),
        now="2099-06-07T10:00:11Z",
        lease_seconds=10,
    )

    assert reclaimed is None
    with get_connection(cfg) as connection:
        attempts = connection.execute(
            "SELECT attempt_id, generation, state FROM tool_prepare_attempts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchall()
    assert [dict(row) for row in attempts] == [
        {"attempt_id": first.attempt_id, "generation": 1, "state": "active"}
    ]
    unchanged = fetch_tool_prepare_job(cfg, job["jobId"])
    assert unchanged is not None
    assert unchanged["lease"]["claimedBy"] == first.claim_owner
    assert unchanged["lease"]["attempts"] == 1


def test_legacy_running_tool_prepare_job_without_attempt_fails_closed(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
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

    reclaimed = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )

    assert reclaimed is None
    with get_connection(cfg) as connection:
        attempt_count = connection.execute(
            "SELECT COUNT(*) AS count FROM tool_prepare_attempts WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()["count"]
    assert attempt_count == 0
    unchanged = fetch_tool_prepare_job(cfg, job["jobId"])
    assert unchanged is not None
    assert unchanged["status"] == "running"
    assert unchanged["stage"] == "dry_run"
    assert unchanged["lease"]["claimedBy"] == ""
    assert unchanged["lease"]["attempts"] == 0


def test_tool_prepare_job_heartbeat_extends_current_lease(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-a"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert proof is not None

    accepted = heartbeat_tool_prepare_job(
        cfg,
        proof,
        now="2099-06-07T10:00:05Z",
        lease_seconds=10,
    )
    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        heartbeat_tool_prepare_job(
            cfg,
            replace(proof, claim_token="f" * 64),
            now="2099-06-07T10:00:06Z",
            lease_seconds=10,
        )

    assert accepted == {
        "accepted": True,
        "attemptId": proof.attempt_id,
        "generation": 1,
        "claimedUntil": "2099-06-07T10:00:15Z",
    }
    refreshed = fetch_tool_prepare_job(cfg, proof.job_id)
    assert refreshed is not None
    assert refreshed["lease"]["heartbeatAt"] == "2099-06-07T10:00:05Z"
    assert refreshed["lease"]["claimedUntil"] == "2099-06-07T10:00:15Z"


def test_tool_prepare_worker_failure_retries_then_exhausts(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::fastqc", "name": "fastqc", "maxAttempts": 2},
    )
    first = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-a", session="attempt-1"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert first is not None

    retry = mark_tool_prepare_job_worker_failure(
        cfg,
        first,
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed",
        now="2099-06-07T10:00:01Z",
        retry_delay_seconds=30,
    )
    assert retry["status"] == "queued"
    assert retry["stage"] == "retry_wait"
    assert retry["generation"] == 1
    assert retry["nextAttemptAt"] == "2099-06-07T10:00:31Z"
    waiting_release = fetch_tool_prepare_job(cfg, job["jobId"])
    assert waiting_release is not None
    assert waiting_release["lease"]["claimedBy"] == first.claim_owner
    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b", session="blocked-before-release"),
        now="2099-06-07T10:00:31Z",
        lease_seconds=10,
    ) is None
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=first,
        now="2099-06-07T10:00:02Z",
    ) is True
    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b", session="before-backoff"),
        now="2099-06-07T10:00:30Z",
        lease_seconds=10,
    ) is None

    second = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-b", session="attempt-2"),
        now="2099-06-07T10:00:31Z",
        lease_seconds=10,
    )
    assert second is not None
    exhausted = mark_tool_prepare_job_worker_failure(
        cfg,
        second,
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed again",
        now="2099-06-07T10:00:32Z",
        retry_delay_seconds=30,
    )

    assert exhausted["status"] == "exhausted"
    assert exhausted["stage"] == "exhausted"
    assert exhausted["generation"] == 2
    assert exhausted["exhaustedAt"] == "2099-06-07T10:00:32Z"
    durable = fetch_tool_prepare_job(cfg, job["jobId"])
    assert durable is not None
    assert durable["errorCode"] == "TOOL_PREPARE_WORKER_CRASHED"
    assert durable["lease"]["attempts"] == 2
    assert durable["lease"]["exhaustedAt"] == "2099-06-07T10:00:32Z"
    assert durable["lease"]["claimedBy"] == second.claim_owner
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=second,
        now="2099-06-07T10:00:33Z",
    ) is True
    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-c"),
        now="2099-06-07T10:01:32Z",
        lease_seconds=10,
    ) is None


def test_running_attempt_cannot_be_released_without_durable_outcome(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastp", "name": "fastp"})
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-running"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert proof is not None

    with pytest.raises(ToolPrepareClaimLostError, match="job has no durable outcome; recovery required"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=proof,
            now="2099-06-07T10:00:01Z",
        )

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, outcome_status, released_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
    assert dict(attempt) == {"state": "recovery_required", "outcome_status": "", "released_at": None}


def test_cancelled_attempt_requires_exact_proof_before_release(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::seqkit", "name": "seqkit"})
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-cancelled"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert proof is not None
    cancel_tool_prepare_job(cfg, proof.job_id)

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        release_tool_prepare_worker_claim(
            cfg,
            proof=replace(proof, claim_token="0" * 64),
            now="2099-06-07T10:00:01Z",
        )
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:02Z",
    ) is True

    refreshed = fetch_tool_prepare_job(cfg, proof.job_id)
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"
    assert refreshed["lease"]["claimedBy"] == ""
    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT state, outcome_status, released_at FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
    assert dict(attempt) == {
        "state": "released",
        "outcome_status": "cancelled",
        "released_at": "2099-06-07T10:00:02Z",
    }


def test_tool_prepare_job_migrates_lease_columns_for_legacy_database(tmp_path: Path) -> None:
    cfg = _config(tmp_path, initialize=False)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE tool_prepare_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                message TEXT NOT NULL,
                tool_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT,
                error_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                cancelled_at TEXT
            )
            """
        )
        connection.commit()

    initialize_or_migrate_runtime_db(cfg.db_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::multiqc", "name": "multiqc", "maxAttempts": 4},
    )

    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tool_prepare_jobs)").fetchall()}

    assert {
        "claimed_by",
        "claimed_until",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "exhausted_at",
        "backoff_seconds",
        "last_worker_error_json",
    } <= columns
    assert job["lease"]["maxAttempts"] == 4


def _identity(worker_id: str, *, session: str = "session-1") -> ToolPrepareWorkerIdentity:
    return make_unverifiable_tool_prepare_worker_identity(
        worker_id=worker_id,
        session_id=session,
        process_instance_id=f"process-{session}",
        hostname="lease-test-runner",
    )


def _config(tmp_path: Path, *, initialize: bool = True) -> RemoteRunnerConfig:
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    cfg = RemoteRunnerConfig(
        token="prepare-lease-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
    )
    if initialize:
        ensure_runtime_layout(cfg)
    return cfg
