from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.candidate_output_storage import (
    adopt_verified_candidate_outputs,
    record_candidate_output,
    verify_candidate_outputs,
)
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from tests.helpers.reference_database import make_configured_remote_runner


def _create_attempt(cfg, run_id: str = "run_candidate"):
    create_run_record(
        cfg,
        server_id="srv_candidate",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_candidate",
            "pipelineId": "pipeline_candidate",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_candidate",
        now="2026-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return claim


def _expected_report(path: Path, sha256: str | None = None) -> dict[str, dict[str, object]]:
    spec: dict[str, object] = {
        "path": str(path),
        "kind": "report",
        "mimeType": "text/plain",
    }
    if sha256 is not None:
        spec["sha256"] = sha256
    return {"report": spec}


def test_candidate_output_must_be_verified_before_adoption(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg)
    output = tmp_path / "report.txt"
    output.write_text("candidate output\n", encoding="utf-8")

    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        output_key="report",
        path=output,
        observed_at="2026-06-07T10:00:05Z",
    )

    assert candidate["verificationState"] == "pending"
    assert candidate["sha256"]

    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_NOT_VERIFIED: report"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            expected_outputs=_expected_report(output),
            adopted_at="2026-06-07T10:00:06Z",
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []

    verification = verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        expected_outputs=_expected_report(output, sha256=candidate["sha256"]),
        verified_at="2026-06-07T10:00:07Z",
    )
    adopted = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        expected_outputs=_expected_report(output),
        adopted_at="2026-06-07T10:00:08Z",
    )
    replay = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        expected_outputs=_expected_report(output),
        adopted_at="2026-06-07T10:00:09Z",
    )

    assert verification["verified"] == ["report"]
    assert verification["rejected"] == []
    assert adopted["artifactIds"] == replay["artifactIds"]
    artifacts = fetch_run_results(cfg, claim["runId"])["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["artifactId"] == adopted["artifactIds"][0]
    assert artifacts[0]["sha256"] == candidate["sha256"]


def test_candidate_output_verification_rejects_checksum_mismatch_and_missing_expected(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_reject")
    output = tmp_path / "report.txt"
    output.write_text("candidate output\n", encoding="utf-8")
    record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        output_key="report",
        path=output,
        observed_at="2026-06-07T10:00:05Z",
    )

    verification = verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        expected_outputs={
            "report": {
                "path": str(output),
                "kind": "report",
                "mimeType": "text/plain",
                "sha256": "wrong",
            },
            "summary": {
                "path": str(tmp_path / "summary.txt"),
                "kind": "table",
                "mimeType": "text/plain",
            },
        },
        verified_at="2026-06-07T10:00:06Z",
    )

    assert verification["verified"] == []
    assert verification["rejected"] == [
        {"outputKey": "report", "reason": "OUTPUT_CHECKSUM_MISMATCH"}
    ]
    assert verification["missing"] == ["summary"]
    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_NOT_VERIFIED: report"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            expected_outputs=_expected_report(output),
            adopted_at="2026-06-07T10:00:07Z",
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []
