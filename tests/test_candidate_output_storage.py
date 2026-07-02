from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.candidate_output_storage import (
    adopt_verified_candidate_outputs,
    record_candidate_output,
    verify_candidate_outputs,
)
from apps.remote_runner.artifact_ledger_storage import (
    list_artifact_materializations,
    list_run_artifact_edges,
)
from apps.remote_runner.artifact_cache_storage import list_artifact_cache_entries
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.reconciler import run_active_reconciler_once
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def _create_attempt(
    cfg,
    run_id: str = "run_candidate",
    *,
    execution: dict | None = None,
    workflow_revision_id: str | None = None,
):
    run_spec = {
        "runId": run_id,
        "projectId": "proj_candidate",
        "pipelineId": "pipeline_candidate",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }
    if workflow_revision_id:
        run_spec["workflowRevisionId"] = workflow_revision_id
    if execution is not None:
        run_spec["execution"] = execution
    create_run_record(
        cfg,
        server_id="srv_candidate",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_candidate",
        now="2099-06-07T10:00:00Z",
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


def _create_revision(cfg):
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_candidate",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "candidate"}]},
        graph_snapshot={"nodes": [{"id": "summarize", "toolRevisionId": "tool#candidate"}]},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa", "version": "candidate-test"},
    )


def test_candidate_output_must_be_verified_before_adoption(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg)
    output = Path(cfg.work_dir) / claim["runId"] / "report.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("candidate output\n", encoding="utf-8")

    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
        observed_at="2099-06-07T10:00:05Z",
    )

    assert candidate["verificationState"] == "pending"
    assert candidate["sha256"]

    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_NOT_VERIFIED: report"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=_expected_report(output),
            adopted_at="2099-06-07T10:00:06Z",
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []

    verification = verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=_expected_report(output, sha256=candidate["sha256"]),
        verified_at="2099-06-07T10:00:07Z",
    )
    adopted = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=_expected_report(output),
        adopted_at="2099-06-07T10:00:08Z",
    )
    replay = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=_expected_report(output),
        adopted_at="2099-06-07T10:00:09Z",
    )

    assert verification["verified"] == ["report"]
    assert verification["rejected"] == []
    assert adopted["artifactIds"] == replay["artifactIds"]
    artifacts = fetch_run_results(cfg, claim["runId"])["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["artifactId"] == adopted["artifactIds"][0]
    assert artifacts[0]["sha256"] == candidate["sha256"]
    edges = list_run_artifact_edges(cfg, claim["runId"])
    assert len(edges) == 1
    assert edges[0]["role"] == "output"
    assert edges[0]["portName"] == "report"
    assert edges[0]["contentHash"] == candidate["sha256"]
    assert list_artifact_materializations(cfg, edges[0]["artifactBlobId"])[0]["storageUri"] == output.resolve().as_uri()


def test_candidate_output_adoption_preserves_lineage_metadata(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    workflow_revision = _create_revision(cfg)
    claim = _create_attempt(
        cfg,
        "run_candidate_lineage",
        workflow_revision_id=workflow_revision["workflowRevisionId"],
    )
    output = Path(cfg.work_dir) / claim["runId"] / "report.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("candidate output\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
        observed_at="2099-06-07T10:00:05Z",
    )
    expected = {
        "report": {
            "path": str(output),
            "kind": "report",
            "mimeType": "text/plain",
            "sha256": candidate["sha256"],
            "stepId": "summarize",
            "upstreamRunId": "run_raw_reads",
        }
    }

    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
        verified_at="2099-06-07T10:00:07Z",
    )
    adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
        adopted_at="2099-06-07T10:00:08Z",
    )

    edges = list_run_artifact_edges(cfg, claim["runId"])
    assert len(edges) == 1
    assert edges[0]["portName"] == "report"
    assert edges[0]["stepId"] == "summarize"
    assert edges[0]["upstreamRunId"] == "run_raw_reads"
    result_bundle = fetch_run_results(cfg, claim["runId"])
    assert len(result_bundle["lineageEdges"]) == 1
    assert result_bundle["lineageEdges"][0]["runId"] == claim["runId"]
    assert result_bundle["lineageEdges"][0]["predicate"] == "prov:generated"
    assert result_bundle["lineageEdges"][0]["workflowRevisionId"] == workflow_revision["workflowRevisionId"]
    cache_entries = list_artifact_cache_entries(cfg, workflow_revision_id=workflow_revision["workflowRevisionId"])[
        "items"
    ]
    assert len(cache_entries) == 1
    assert cache_entries[0]["artifactKey"] == "report"
    assert cache_entries[0]["artifactId"] == result_bundle["artifacts"][0]["artifactId"]


def test_candidate_output_verification_rejects_checksum_mismatch_and_missing_expected(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_reject")
    output = tmp_path / "report.txt"
    output.write_text("candidate output\n", encoding="utf-8")
    record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
        observed_at="2099-06-07T10:00:05Z",
    )

    verification = verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
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
        verified_at="2099-06-07T10:00:06Z",
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
            lease_generation=claim["leaseGeneration"],
            expected_outputs=_expected_report(output),
            adopted_at="2099-06-07T10:00:07Z",
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []


def test_candidate_output_adoption_rejects_stale_lease_generation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_stale", execution={"retryPolicy": {"backoffSeconds": 0}})
    output = tmp_path / "stale.txt"
    output.write_text("old attempt\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )

    assert (
        claim_next_run_job(
            cfg,
            worker_id="worker_replacement",
            now="2099-06-07T10:01:00Z",
            lease_seconds=30,
        )
        is None
    )
    run_active_reconciler_once(
        cfg,
        now="2099-06-07T10:01:00Z",
        retry_delay_seconds=0,
    )
    replacement = claim_next_run_job(
        cfg,
        worker_id="worker_replacement",
        now="2099-06-07T10:01:00Z",
        lease_seconds=30,
    )
    assert replacement is not None
    assert replacement["leaseGeneration"] == claim["leaseGeneration"] + 1

    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=expected,
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []


def test_candidate_output_adoption_rehashes_file_inside_transaction(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_changed")
    output = tmp_path / "changed.txt"
    output.write_text("verified content\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )
    output.write_text("changed after verification\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_CHANGED_AFTER_VERIFICATION"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=expected,
        )
    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []


def test_candidate_adoption_atomically_completes_run_and_attempt(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_finalize")
    output = Path(cfg.results_dir) / claim["runId"] / "final.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("final output\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )
    adopted = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
        finalize_run=True,
        request_id=f"req_{claim['runId']}",
        result_dir=str(output.parent),
    )

    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage FROM runs WHERE run_id = ?",
            (claim["runId"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT output_adoption_state FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
        candidate_row = connection.execute(
            """
            SELECT adopted_artifact_id
            FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
            """,
            (claim["runId"], claim["attemptId"], claim["leaseGeneration"], "report"),
        ).fetchone()
    assert run["status"] == "completed"
    assert run["stage"] == "finalize"
    assert attempt["output_adoption_state"] == "adopted"
    assert candidate_row["adopted_artifact_id"] == adopted["artifactIds"][0]


def test_candidate_adoption_cannot_complete_terminal_run(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_terminal_finalize")
    output = Path(cfg.results_dir) / claim["runId"] / "final.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("final output\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'failed', stage = 'execute', state_version = 2,
                message = 'Terminal failure.'
            WHERE run_id = ?
            """,
            (claim["runId"],),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RUN_STATUS_TERMINAL_IMMUTABLE: failed -> completed"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=expected,
            finalize_run=True,
            request_id=f"req_{claim['runId']}",
            result_dir=str(output.parent),
        )

    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage, state_version, message FROM runs WHERE run_id = ?",
            (claim["runId"],),
        ).fetchone()
        candidate_row = connection.execute(
            "SELECT adopted_artifact_id FROM candidate_outputs WHERE candidate_output_id = ?",
            (candidate["candidateOutputId"],),
        ).fetchone()
        artifact_count = connection.execute(
            "SELECT COUNT(*) AS count FROM artifacts WHERE run_id = ?",
            (claim["runId"],),
        ).fetchone()["count"]
    assert dict(run) == {
        "status": "failed",
        "stage": "execute",
        "state_version": 2,
        "message": "Terminal failure.",
    }
    assert candidate_row["adopted_artifact_id"] is None
    assert artifact_count == 0


def test_candidate_output_adoption_rejects_unmanaged_path_without_artifact_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_unmanaged")
    output = tmp_path / "outside-candidate.txt"
    output.write_text("outside candidate\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )

    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_PATH_UNMANAGED: report"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=expected,
        )

    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT verification_state, adopted_artifact_id FROM candidate_outputs WHERE candidate_output_id = ?",
            (candidate["candidateOutputId"],),
        ).fetchone()
        artifact_count = connection.execute(
            "SELECT COUNT(*) AS count FROM artifacts WHERE run_id = ?",
            (claim["runId"],),
        ).fetchone()["count"]
    assert artifact_count == 0
    assert row["verification_state"] == "verified"
    assert row["adopted_artifact_id"] is None


def test_candidate_output_finalize_rejects_unmanaged_result_dir_without_artifact_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_unmanaged_result_dir")
    output = Path(cfg.work_dir) / claim["runId"] / "report.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("managed candidate\n", encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = _expected_report(output, sha256=candidate["sha256"])
    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )

    with pytest.raises(ValueError, match="CANDIDATE_OUTPUT_RESULT_DIR_UNMANAGED"):
        adopt_verified_candidate_outputs(
            cfg,
            run_id=claim["runId"],
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            expected_outputs=expected,
            finalize_run=True,
            request_id=f"req_{claim['runId']}",
            result_dir=str(tmp_path / "outside-result-dir"),
        )

    assert fetch_run_results(cfg, claim["runId"])["artifacts"] == []
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT status, stage, result_dir FROM runs WHERE run_id = ?", (claim["runId"],)).fetchone()
        row = connection.execute(
            "SELECT verification_state, adopted_artifact_id FROM candidate_outputs WHERE candidate_output_id = ?",
            (candidate["candidateOutputId"],),
        ).fetchone()
    assert run["status"] == "queued"
    assert run["stage"] == "submitted"
    assert run["result_dir"] == ""
    assert row["verification_state"] == "verified"
    assert row["adopted_artifact_id"] is None
