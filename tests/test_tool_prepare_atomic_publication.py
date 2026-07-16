from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from apps.remote_runner import tool_prepare_publication as publication
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareClaimLostError,
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
)
from apps.remote_runner.tool_prepare_publication import publish_validated_tool_for_attempt
from tests.helpers.reference_database import make_remote_runner_config


COMPLETED_AT = "2099-06-07T10:01:00Z"


def test_atomic_publication_commits_all_records_and_retains_active_attempt(tmp_path: Path) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)

    result = publish_validated_tool_for_attempt(
        cfg,
        proof=proof,
        validated_tool=tool,
        completed_at=COMPLETED_AT,
    )

    with get_connection(cfg) as connection:
        stored_job = connection.execute(
            "SELECT * FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT * FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        index = connection.execute(
            "SELECT * FROM tool_index WHERE tool_id = ?",
            (tool["id"],),
        ).fetchone()
        validation = connection.execute(
            "SELECT * FROM tool_validation_results WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
        events = connection.execute(
            "SELECT stage, details_json FROM tool_prepare_job_events WHERE job_id = ? ORDER BY rowid",
            (job["jobId"],),
        ).fetchall()
        evidence_payloads = connection.execute(
            "SELECT payload_json FROM evidence_events ORDER BY seq",
        ).fetchall()
        counts = _publication_counts(connection)

    assert counts == {
        "evidence_events": 1,
        "tool_index": 1,
        "tool_revisions": 1,
        "tool_runtime_profiles": 1,
        "tool_validation_results": 1,
        "tools": 1,
    }
    assert stored_job["status"] == "succeeded"
    assert stored_job["stage"] == "published"
    assert stored_job["claimed_by"] == proof.claim_owner
    assert int(stored_job["attempts"]) == proof.generation
    assert json.loads(stored_job["result_json"]) == result
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == "succeeded"
    assert attempt["released_at"] is None
    assert validation["validation_result_id"] == result["validationResultId"]
    assert validation["evidence_id"] == result["evidenceId"]
    assert json.loads(index["validation_summary_json"]) == result["validationSummary"]
    assert [row["stage"] for row in events] == ["queued", "claimed", "published"]

    persisted_hash = str(attempt["claim_token_hash"])
    public_corpus = json.dumps(
        {
            "evidence": [row["payload_json"] for row in evidence_payloads],
            "events": [row["details_json"] for row in events],
            "result": result,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    assert proof.claim_token not in public_corpus
    assert persisted_hash not in public_corpus


def test_cancel_before_publication_prevents_every_publication_write(tmp_path: Path) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)
    cancelled = cancel_tool_prepare_job(cfg, job["jobId"])
    assert cancelled["status"] == "cancelled"

    with pytest.raises(ToolPrepareClaimLostError, match="claim projection rejected"):
        publish_validated_tool_for_attempt(
            cfg,
            proof=proof,
            validated_tool=tool,
            completed_at=COMPLETED_AT,
        )

    with get_connection(cfg) as connection:
        assert _row_count(connection, "tool_revisions") == 0
        assert _row_count(connection, "tools") == 0
        assert _row_count(connection, "tool_index") == 0
        statuses = [
            str(row["status"])
            for row in connection.execute(
                "SELECT status FROM tool_validation_results WHERE job_id = ? ORDER BY rowid",
                (job["jobId"],),
            ).fetchall()
        ]
        attempt = connection.execute(
            "SELECT state, outcome_status FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        published_events = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM tool_prepare_job_events WHERE job_id = ? AND stage = 'published'",
                (job["jobId"],),
            ).fetchone()["count"]
        )

    assert statuses == ["cancelled"]
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == "cancelled"
    assert published_events == 0


@pytest.mark.parametrize("fault_point", ["after_validation", "after_published_event"])
def test_publication_failure_injection_rolls_back_the_entire_unit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault_point: str,
) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)

    if fault_point == "after_validation":
        original = publication.record_prepare_job_validation_result

        def fail_after_validation(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected failure after validation")

        monkeypatch.setattr(publication, "record_prepare_job_validation_result", fail_after_validation)
    else:
        original_event = publication._insert_published_event

        def fail_after_event(*args, **kwargs):
            original_event(*args, **kwargs)
            raise RuntimeError("injected failure after published event")

        monkeypatch.setattr(publication, "_insert_published_event", fail_after_event)

    with pytest.raises(RuntimeError, match="injected failure"):
        publish_validated_tool_for_attempt(
            cfg,
            proof=proof,
            validated_tool=tool,
            completed_at=COMPLETED_AT,
        )

    with get_connection(cfg) as connection:
        assert _publication_counts(connection) == {
            "evidence_events": 0,
            "tool_index": 0,
            "tool_revisions": 0,
            "tool_runtime_profiles": 0,
            "tool_validation_results": 0,
            "tools": 0,
        }
        stored_job = connection.execute(
            "SELECT status, stage, result_json FROM tool_prepare_jobs WHERE job_id = ?",
            (job["jobId"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status FROM tool_prepare_attempts WHERE attempt_id = ?",
            (proof.attempt_id,),
        ).fetchone()
        stages = [
            str(row["stage"])
            for row in connection.execute(
                "SELECT stage FROM tool_prepare_job_events WHERE job_id = ? ORDER BY rowid",
                (job["jobId"],),
            ).fetchall()
        ]

    assert stored_job["status"] == "running"
    assert stored_job["stage"] == "claimed"
    assert stored_job["result_json"] is None
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == ""
    assert stages == ["queued", "claimed"]


def test_same_proof_replays_committed_result_without_duplicate_records(tmp_path: Path) -> None:
    cfg, _job, proof, tool = _claimed_prepare_job(tmp_path)
    first = publish_validated_tool_for_attempt(
        cfg,
        proof=proof,
        validated_tool=tool,
        completed_at=COMPLETED_AT,
    )
    with get_connection(cfg) as connection:
        before = _all_effect_counts(connection)

    replay = publish_validated_tool_for_attempt(
        cfg,
        proof=proof,
        validated_tool=tool,
        completed_at="2099-06-07T10:02:00Z",
    )

    with get_connection(cfg) as connection:
        after = _all_effect_counts(connection)
    assert replay == first
    assert after == before


def test_wrong_claim_token_is_rejected_without_writes(tmp_path: Path) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)
    forged = replace(proof, claim_token="forged-claim-token")

    with pytest.raises(ToolPrepareClaimLostError, match="attempt proof rejected"):
        publish_validated_tool_for_attempt(
            cfg,
            proof=forged,
            validated_tool=tool,
            completed_at=COMPLETED_AT,
        )

    _assert_no_publication_writes(cfg, job_id=job["jobId"], attempt_id=proof.attempt_id)


def test_claim_for_one_job_cannot_publish_a_different_tool(tmp_path: Path) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)
    different_tool = {
        **tool,
        "id": "bioconda::multiqc",
        "name": "MultiQC",
        "packageSpec": "bioconda::multiqc=1.30",
    }

    with pytest.raises(ToolPrepareClaimLostError, match="does not match prepare job"):
        publish_validated_tool_for_attempt(
            cfg,
            proof=proof,
            validated_tool=different_tool,
            completed_at=COMPLETED_AT,
        )

    _assert_no_publication_writes(cfg, job_id=job["jobId"], attempt_id=proof.attempt_id)


def test_claim_cannot_publish_same_tool_with_a_different_package_reservation(tmp_path: Path) -> None:
    cfg, job, proof, tool = _claimed_prepare_job(tmp_path)
    different_package = {**tool, "packageSpec": "bioconda::fastqc=0.11.9"}

    with pytest.raises(ToolPrepareClaimLostError, match="does not match prepare job reservation"):
        publish_validated_tool_for_attempt(
            cfg,
            proof=proof,
            validated_tool=different_package,
            completed_at=COMPLETED_AT,
        )

    _assert_no_publication_writes(cfg, job_id=job["jobId"], attempt_id=proof.attempt_id)


def _claimed_prepare_job(tmp_path: Path):
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    request = _tool_payload()
    job = create_tool_prepare_job(cfg, request)
    tool = {key: value for key, value in request.items() if key != "validationTarget"}
    identity = ToolPrepareWorkerIdentity(
        worker_id="atomic-publication-worker",
        session_id="atomic-publication-session",
        process_instance_id="atomic-publication-process",
        process_pid=4242,
        hostname="atomic-runner",
    )
    proof = claim_next_tool_prepare_job(
        cfg,
        identity=identity,
        now="2099-06-07T10:00:00Z",
        lease_seconds=300,
    )
    assert proof is not None
    return cfg, job, proof, tool


def _tool_payload() -> dict[str, object]:
    return {
        "id": "bioconda::fastqc",
        "name": "FastQC",
        "source": "bioconda",
        "sourceLabel": "Bioconda",
        "version": "0.12.1",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "summary": "Read quality control.",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "platforms": ["linux-64"],
        "validationTarget": "workflow-ready",
    }


def _publication_counts(connection) -> dict[str, int]:
    return {
        table: _row_count(connection, table)
        for table in (
            "evidence_events",
            "tool_index",
            "tool_revisions",
            "tool_runtime_profiles",
            "tool_validation_results",
            "tools",
        )
    }


def _all_effect_counts(connection) -> dict[str, int]:
    counts = _publication_counts(connection)
    counts["tool_prepare_job_events"] = _row_count(connection, "tool_prepare_job_events")
    return counts


def _assert_no_publication_writes(cfg, *, job_id: str, attempt_id: str) -> None:
    with get_connection(cfg) as connection:
        assert _publication_counts(connection) == {
            "evidence_events": 0,
            "tool_index": 0,
            "tool_revisions": 0,
            "tool_runtime_profiles": 0,
            "tool_validation_results": 0,
            "tools": 0,
        }
        job = connection.execute(
            "SELECT status, stage, result_json FROM tool_prepare_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, outcome_status FROM tool_prepare_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    assert job["status"] == "running"
    assert job["stage"] == "claimed"
    assert job["result_json"] is None
    assert attempt["state"] == "active"
    assert attempt["outcome_status"] == ""


def _row_count(connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"])
