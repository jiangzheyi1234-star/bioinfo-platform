from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest

import apps.remote_runner.tool_prepare_attempt_mutations as mutations
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_attempt_mutations import (
    fail_tool_prepare_job,
    mark_tool_prepare_job_waiting_resource,
    mark_tool_prepare_job_worker_failure,
    record_tool_prepare_job_event,
)
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job
from tests.helpers.reference_database import make_configured_remote_runner


MutationCall = Callable[[Any, ToolPrepareAttemptProof], dict[str, Any]]


def test_record_event_requires_active_proof_and_keeps_attempt_active(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::event")

    result = record_tool_prepare_job_event(
        cfg,
        proof,
        stage="runtime_check",
        message="Runtime check passed.",
        level="success",
        details={"runtime": "snakemake"},
        now="2099-06-07T10:00:01Z",
    )

    assert result == {
        "attemptId": proof.attempt_id,
        "generation": 1,
        "jobId": proof.job_id,
        "stage": "runtime_check",
        "status": "running",
    }
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT status, stage, message, claimed_by, attempts FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status, last_error_json FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        event = connection.execute(
            """
            SELECT stage, level, message, details_json, created_at
            FROM tool_prepare_job_events
            WHERE job_id = ? AND stage = 'runtime_check'
            """,
            (proof.job_id,),
        ).fetchone()
    assert dict(job) == {
        "status": "running",
        "stage": "runtime_check",
        "message": "Runtime check passed.",
        "claimed_by": proof.claim_owner,
        "attempts": 1,
    }
    assert dict(attempt) == {"state": "active", "outcome_status": "", "last_error_json": "{}"}
    assert dict(event) == {
        "stage": "runtime_check",
        "level": "success",
        "message": "Runtime check passed.",
        "details_json": json.dumps(
            {
                "attemptId": proof.attempt_id,
                "generation": 1,
                "runtime": "snakemake",
                "workerId": proof.worker_id,
            },
            sort_keys=True,
        ),
        "created_at": "2099-06-07T10:00:01Z",
    }


def test_fail_records_atomic_outcome_validation_evidence_and_event(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::failed")

    result = fail_tool_prepare_job(
        cfg,
        proof,
        code="SNAKEMAKE_DRY_RUN_FAILED",
        message="Snakemake dry-run failed.",
        now="2099-06-07T10:00:02Z",
    )

    assert result == {
        "attemptId": proof.attempt_id,
        "generation": 1,
        "jobId": proof.job_id,
        "stage": "failed",
        "status": "failed",
    }
    with get_connection(cfg) as connection:
        job = connection.execute(
            """
            SELECT status, stage, error_code, claimed_by, claimed_until, finished_at
            FROM tool_prepare_jobs WHERE job_id = ?
            """,
            (proof.job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status, last_error_json FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        validation = connection.execute(
            "SELECT stage, status, failure_code, evidence_id FROM tool_validation_results WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
        event = connection.execute(
            "SELECT stage, level, details_json FROM tool_prepare_job_events WHERE job_id = ? AND stage = 'failed'",
            (proof.job_id,),
        ).fetchone()
        evidence_count = connection.execute(
            "SELECT COUNT(*) AS count FROM evidence_events WHERE event_id = ?",
            (validation["evidence_id"],),
        ).fetchone()["count"]
    assert job["status"] == "failed"
    assert job["stage"] == "failed"
    assert job["error_code"] == "SNAKEMAKE_DRY_RUN_FAILED"
    assert job["claimed_by"] == proof.claim_owner
    assert job["claimed_until"] == "2099-06-07T10:00:30Z"
    assert job["finished_at"] == "2099-06-07T10:00:02Z"
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == "failed"
    assert json.loads(attempt["last_error_json"])["code"] == "SNAKEMAKE_DRY_RUN_FAILED"
    assert dict(validation) == {
        "stage": "failed",
        "status": "failed",
        "failure_code": "SNAKEMAKE_DRY_RUN_FAILED",
        "evidence_id": validation["evidence_id"],
    }
    assert evidence_count == 1
    assert dict(event) == {
        "stage": "failed",
        "level": "error",
        "details_json": json.dumps(
            {
                "attemptId": proof.attempt_id,
                "code": "SNAKEMAKE_DRY_RUN_FAILED",
                "generation": 1,
                "workerId": proof.worker_id,
            },
            sort_keys=True,
        ),
    }


def test_waiting_resource_records_details_validation_and_keeps_claim(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::waiting")

    result = mark_tool_prepare_job_waiting_resource(
        cfg,
        proof,
        code="RESOURCE_BINDING_MISSING",
        message="Required database is missing.",
        details={"resourceKey": "kraken2_db", "acceptedTemplates": ["kraken2"]},
        now="2099-06-07T10:00:03Z",
    )

    assert result["status"] == "waiting_resource"
    assert result["stage"] == "waiting_resource"
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT status, stage, error_code, claimed_by FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status, last_error_json FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        event = connection.execute(
            "SELECT details_json FROM tool_prepare_job_events WHERE job_id = ? AND stage = 'waiting_resource'",
            (proof.job_id,),
        ).fetchone()
        validation = connection.execute(
            "SELECT status, failure_code FROM tool_validation_results WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
    assert dict(job) == {
        "status": "waiting_resource",
        "stage": "waiting_resource",
        "error_code": "RESOURCE_BINDING_MISSING",
        "claimed_by": proof.claim_owner,
    }
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == "waiting_resource"
    assert json.loads(attempt["last_error_json"])["details"]["resourceKey"] == "kraken2_db"
    assert json.loads(event["details_json"]) == {
        "acceptedTemplates": ["kraken2"],
        "attemptId": proof.attempt_id,
        "code": "RESOURCE_BINDING_MISSING",
        "generation": 1,
        "resourceKey": "kraken2_db",
        "workerId": proof.worker_id,
    }
    assert dict(validation) == {"status": "waiting_resource", "failure_code": "RESOURCE_BINDING_MISSING"}


def test_worker_failure_retry_cannot_be_reclaimed_before_exact_release(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(
        tmp_path,
        tool_id="bioconda::retry",
        payload_overrides={"maxAttempts": 2},
    )

    retry = mark_tool_prepare_job_worker_failure(
        cfg,
        proof,
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed",
        now="2099-06-07T10:00:04Z",
        retry_delay_seconds=0,
    )

    assert retry == {
        "attemptId": proof.attempt_id,
        "generation": 1,
        "jobId": proof.job_id,
        "stage": "retry_wait",
        "status": "queued",
        "exhaustedAt": None,
        "nextAttemptAt": "2099-06-07T10:00:04Z",
    }
    with get_connection(cfg) as connection:
        job = connection.execute(
            """
            SELECT status, stage, claimed_by, claimed_until, next_attempt_at, last_worker_error_json
            FROM tool_prepare_jobs WHERE job_id = ?
            """,
            (proof.job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status, last_error_json FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
    assert job["status"] == "queued"
    assert job["stage"] == "retry_wait"
    assert job["claimed_by"] == proof.claim_owner
    assert job["claimed_until"] == "2099-06-07T10:00:30Z"
    assert job["next_attempt_at"] == "2099-06-07T10:00:04Z"
    assert json.loads(job["last_worker_error_json"])["attempts"] == 1
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == "retry_wait"
    assert json.loads(attempt["last_error_json"])["code"] == "TOOL_PREPARE_WORKER_CRASHED"
    assert claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-before-release", session="before-release"),
        now="2099-06-07T10:00:05Z",
        lease_seconds=30,
    ) is None

    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:06Z",
    ) is True
    next_proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-after-release", session="after-release"),
        now="2099-06-07T10:00:07Z",
        lease_seconds=30,
    )
    assert next_proof is not None
    assert next_proof.generation == 2


def test_worker_failure_exhaustion_is_durable_before_release(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(
        tmp_path,
        tool_id="bioconda::exhausted",
        payload_overrides={"maxAttempts": 1},
    )

    exhausted = mark_tool_prepare_job_worker_failure(
        cfg,
        proof,
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed permanently",
        now="2099-06-07T10:00:08Z",
    )

    assert exhausted["status"] == "exhausted"
    assert exhausted["stage"] == "exhausted"
    assert exhausted["exhaustedAt"] == "2099-06-07T10:00:08Z"
    assert exhausted["nextAttemptAt"] is None
    with get_connection(cfg) as connection:
        job = connection.execute(
            "SELECT status, claimed_by, exhausted_at FROM tool_prepare_jobs WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        validation = connection.execute(
            "SELECT status, failure_code, evidence_id FROM tool_validation_results WHERE job_id = ?",
            (proof.job_id,),
        ).fetchone()
    assert dict(job) == {
        "status": "exhausted",
        "claimed_by": proof.claim_owner,
        "exhausted_at": "2099-06-07T10:00:08Z",
    }
    assert dict(attempt) == {"state": "active", "outcome_status": "exhausted"}
    assert validation["status"] == "exhausted"
    assert validation["failure_code"] == "TOOL_PREPARE_WORKER_CRASHED"
    assert validation["evidence_id"]
    assert release_tool_prepare_worker_claim(
        cfg,
        proof=proof,
        now="2099-06-07T10:00:09Z",
    ) is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda cfg, proof: record_tool_prepare_job_event(
            cfg, proof, stage="stale_event", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: fail_tool_prepare_job(
            cfg, proof, code="STALE_FAIL", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: mark_tool_prepare_job_waiting_resource(
            cfg, proof, code="STALE_WAIT", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: mark_tool_prepare_job_worker_failure(
            cfg, proof, code="STALE_WORKER", message="stale", now="2099-06-07T10:01:01Z"
        ),
    ],
    ids=("event", "fail", "waiting", "worker-failure"),
)
def test_wrong_proof_causes_zero_writes(tmp_path: Path, mutation: MutationCall) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::wrong-proof")
    forged = replace(proof, claim_token="0" * 64)
    before = _database_state(cfg, proof.job_id)

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        mutation(cfg, forged)

    assert _database_state(cfg, proof.job_id) == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda cfg, proof: record_tool_prepare_job_event(
            cfg, proof, stage="stale_event", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: fail_tool_prepare_job(
            cfg, proof, code="STALE_FAIL", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: mark_tool_prepare_job_waiting_resource(
            cfg, proof, code="STALE_WAIT", message="stale", now="2099-06-07T10:01:01Z"
        ),
        lambda cfg, proof: mark_tool_prepare_job_worker_failure(
            cfg, proof, code="STALE_WORKER", message="stale", now="2099-06-07T10:01:01Z"
        ),
    ],
    ids=("event", "fail", "waiting", "worker-failure"),
)
def test_stale_generation_causes_zero_writes(tmp_path: Path, mutation: MutationCall) -> None:
    cfg, old_proof = _claimed_job(
        tmp_path,
        tool_id="bioconda::stale-generation",
        payload_overrides={"maxAttempts": 2},
    )
    mark_tool_prepare_job_worker_failure(
        cfg,
        old_proof,
        code="FIRST_ATTEMPT_FAILED",
        message="retry",
        now="2099-06-07T10:00:01Z",
        retry_delay_seconds=0,
    )
    release_tool_prepare_worker_claim(cfg, proof=old_proof, now="2099-06-07T10:00:02Z")
    current_proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-generation-2", session="generation-2"),
        now="2099-06-07T10:00:03Z",
        lease_seconds=30,
    )
    assert current_proof is not None
    before = _database_state(cfg, old_proof.job_id)

    with pytest.raises(ToolPrepareClaimLostError, match="attempt is not active"):
        mutation(cfg, old_proof)

    assert _database_state(cfg, old_proof.job_id) == before
    with get_connection(cfg) as connection:
        current = connection.execute(
            "SELECT state FROM tool_prepare_attempts WHERE attempt_id = ?",
            (current_proof.attempt_id,),
        ).fetchone()
    assert current["state"] == "active"


def test_validation_exception_rolls_back_job_attempt_event_and_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::rollback")
    before = _database_state(cfg, proof.job_id)

    def crash_validation(*_args, **_kwargs):
        raise RuntimeError("validation ledger unavailable")

    monkeypatch.setattr(mutations, "record_prepare_job_validation_result", crash_validation)
    with pytest.raises(RuntimeError, match="validation ledger unavailable"):
        fail_tool_prepare_job(
            cfg,
            proof,
            code="ROLLBACK_TEST",
            message="must roll back",
            now="2099-06-07T10:00:10Z",
        )

    assert _database_state(cfg, proof.job_id) == before


def test_invalid_max_attempts_fails_closed_without_writes(tmp_path: Path) -> None:
    cfg, proof = _claimed_job(tmp_path, tool_id="bioconda::invalid-max-attempts")
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE tool_prepare_jobs SET max_attempts = 0 WHERE job_id = ?",
            (proof.job_id,),
        )
        connection.commit()
    before = _database_state(cfg, proof.job_id)

    with pytest.raises(ToolPrepareClaimLostError, match="prepare job max_attempts is invalid"):
        mark_tool_prepare_job_worker_failure(
            cfg,
            proof,
            code="INVALID_SCHEMA",
            message="must not continue",
            now="2099-06-07T10:00:11Z",
        )

    assert _database_state(cfg, proof.job_id) == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda cfg: record_tool_prepare_job_event(cfg, stage="x", message="x"),
        lambda cfg: fail_tool_prepare_job(cfg, code="x", message="x"),
        lambda cfg: mark_tool_prepare_job_waiting_resource(cfg, code="x", message="x"),
        lambda cfg: mark_tool_prepare_job_worker_failure(cfg, code="x", message="x"),
    ],
)
def test_mutations_do_not_accept_missing_or_legacy_proof(tmp_path: Path, mutation) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with pytest.raises(TypeError):
        mutation(cfg)


def _claimed_job(
    tmp_path: Path,
    *,
    tool_id: str,
    payload_overrides: dict[str, Any] | None = None,
):
    cfg = make_configured_remote_runner(tmp_path)
    payload = {"id": tool_id, "name": tool_id.rsplit("::", 1)[-1], **(payload_overrides or {})}
    create_tool_prepare_job(cfg, payload)
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=_identity("worker-1"),
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert proof is not None
    return cfg, proof


def _identity(worker_id: str, *, session: str = "session-1") -> ToolPrepareWorkerIdentity:
    return ToolPrepareWorkerIdentity(
        worker_id=worker_id,
        session_id=session,
        process_instance_id=f"process-{session}",
        process_pid=os.getpid(),
        hostname="test-runner",
    )


def _database_state(cfg, job_id: str) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        job = connection.execute(
            """
            SELECT status, stage, message, error_code, claimed_by, claimed_until,
                   heartbeat_at, attempts, next_attempt_at, exhausted_at, finished_at,
                   last_worker_error_json, updated_at
            FROM tool_prepare_jobs WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        attempts = connection.execute(
            """
            SELECT attempt_id, generation, state, outcome_status, last_error_json,
                   heartbeat_at, lease_expires_at, released_at, updated_at
            FROM tool_prepare_attempts WHERE job_id = ? ORDER BY generation
            """,
            (job_id,),
        ).fetchall()
        events = connection.execute(
            """
            SELECT stage, level, message, details_json, created_at
            FROM tool_prepare_job_events WHERE job_id = ? ORDER BY rowid
            """,
            (job_id,),
        ).fetchall()
        counts = {
            table: connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in (
                "tool_validation_results",
                "tool_runtime_profiles",
                "evidence_events",
                "tool_index",
            )
        }
    return {
        "attempts": [dict(row) for row in attempts],
        "counts": counts,
        "events": [dict(row) for row in events],
        "job": dict(job),
    }
