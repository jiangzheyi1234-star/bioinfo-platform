from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.execution_resume_claim_preflight import (
    build_run_resume_claim_preflight,
    build_run_resume_execution_options,
    run_resume_execution_options_requested,
    validate_run_resume_claim_preflight,
    validate_run_resume_claim_state,
)
from apps.remote_runner.execution_resume_plan import build_run_resume_plan
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import update_run_state
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_resume_claim_preflight_accepts_plan_bound_scope(tmp_path: Path) -> None:
    plan = _resume_plan(tmp_path)
    options = build_run_resume_execution_options(plan)

    preflight = build_run_resume_claim_preflight(
        options,
        run_id="run_resume_claim",
        attempt_id="att_resume_target",
        lease_generation=2,
    )

    assert run_resume_execution_options_requested(options) is True
    assert preflight["schemaVersion"] == "run-resume-claim-preflight.v1"
    assert preflight["claimReady"] is True
    assert preflight["reasonCode"] == "RUN_RESUME_CLAIM_PREFLIGHT_READY"
    assert preflight["sourcePlanHash"] == plan["planHash"]
    assert preflight["sourceAttemptPresent"] is True
    assert preflight["outputScopeReady"] is True
    assert preflight["outputKeys"] == ["present", "missing"]
    assert preflight["rerunIncomplete"] is True
    assert preflight["forcerunRuleCount"] == 0
    assert preflight["finalizeRunOnAdoption"] is True
    assert preflight["pathExposed"] is False
    assert preflight["storageUriExposed"] is False
    assert options["snakemake"] == {
        "schemaVersion": "snakemake-run-resume-options.v1",
        "rerunIncomplete": True,
        "forcerunRules": [],
        "argsPreview": ["--rerun-incomplete"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }


def test_run_resume_claim_preflight_rejects_missing_source_plan_hash(tmp_path: Path) -> None:
    options = build_run_resume_execution_options(_resume_plan(tmp_path))
    options["resumeScope"]["sourcePlanHash"] = ""

    preflight = build_run_resume_claim_preflight(
        options,
        run_id="run_resume_claim",
        attempt_id="att_resume_target",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RUN_RESUME_SOURCE_PLAN_HASH_REQUIRED"
    with pytest.raises(ValueError, match="RUN_RESUME_SOURCE_PLAN_HASH_REQUIRED"):
        validate_run_resume_claim_preflight(
            options,
            run_id="run_resume_claim",
            attempt_id="att_resume_target",
            lease_generation=2,
        )


def test_run_resume_claim_preflight_rejects_disabled_rerun_incomplete(tmp_path: Path) -> None:
    options = build_run_resume_execution_options(_resume_plan(tmp_path))
    options["snakemake"]["rerunIncomplete"] = False

    preflight = build_run_resume_claim_preflight(
        options,
        run_id="run_resume_claim",
        attempt_id="att_resume_target",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RUN_RESUME_RERUN_INCOMPLETE_REQUIRED"


def test_run_resume_claim_preflight_rejects_forcerun_and_unsafe_flags(tmp_path: Path) -> None:
    options = build_run_resume_execution_options(_resume_plan(tmp_path))
    options["snakemake"]["forcerunRules"] = ["align"]
    options["snakemake"]["argsPreview"] = ["--rerun-incomplete", "--forcerun", "align"]

    preflight = build_run_resume_claim_preflight(
        options,
        run_id="run_resume_claim",
        attempt_id="att_resume_target",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert "RUN_RESUME_FORCERUN_RULES_FORBIDDEN" in preflight["blockedReasonCodes"]
    assert "RUN_RESUME_UNSAFE_FLAG_FORBIDDEN" in preflight["blockedReasonCodes"]


def test_run_resume_claim_preflight_rejects_redaction_exposure(tmp_path: Path) -> None:
    options = build_run_resume_execution_options(_resume_plan(tmp_path))
    options["resumeScope"]["pathExposed"] = True
    options["resumeScope"]["storageUriExposed"] = True

    preflight = build_run_resume_claim_preflight(
        options,
        run_id="run_resume_claim",
        attempt_id="att_resume_target",
        lease_generation=2,
    )

    assert preflight["claimReady"] is False
    assert preflight["reasonCode"] == "RUN_RESUME_EXECUTION_SCOPE_REDACTION_UNSAFE"
    assert preflight["pathExposed"] is True
    assert preflight["storageUriExposed"] is True


def test_run_resume_claim_reuses_source_workdir_for_target_attempt(tmp_path: Path) -> None:
    cfg, run_id, source_claim = _failed_source_attempt(tmp_path)
    options = _source_attempt_options(cfg, run_id)
    target_claim = _claim_resume_target_attempt(cfg, run_id, options)

    with get_connection(cfg) as connection:
        target_work_dir = connection.execute(
            "SELECT work_dir FROM run_attempts WHERE attempt_id = ?",
            (target_claim["attemptId"],),
        ).fetchone()["work_dir"]
    assert target_work_dir == source_claim["attempt"]["workDir"]

    preflight = validate_run_resume_claim_state(
        cfg,
        options,
        run_id=run_id,
        attempt_id=target_claim["attemptId"],
        lease_generation=target_claim["leaseGeneration"],
    )
    assert preflight["workdirReuseSatisfied"] is True


def test_run_resume_claim_state_validates_active_job_attempt_lease_and_reused_workdir(tmp_path: Path) -> None:
    cfg, run_id, source_claim = _failed_source_attempt(tmp_path)
    options = _source_attempt_options(cfg, run_id)
    target_claim = _claim_resume_target_attempt(cfg, run_id, options)
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_attempts SET work_dir = ? WHERE attempt_id = ?",
            (source_claim["attempt"]["workDir"], target_claim["attemptId"]),
        )
        connection.commit()

    preflight = validate_run_resume_claim_state(
        cfg,
        options,
        run_id=run_id,
        attempt_id=target_claim["attemptId"],
        lease_generation=target_claim["leaseGeneration"],
    )

    assert preflight["claimReady"] is True
    assert preflight["jobClaimed"] is True
    assert preflight["attemptRunning"] is True
    assert preflight["activeLeaseMatchesAttempt"] is True
    assert preflight["sourceAttemptReusable"] is True
    assert preflight["workdirReuseSatisfied"] is True
    assert preflight["persistedExecutionOptionsMatch"] is True


def _resume_plan(tmp_path: Path) -> dict:
    work_dir = tmp_path / "source-work"
    result_dir = tmp_path / "results"
    work_dir.mkdir()
    result_dir.mkdir()
    present_output = result_dir / "present.txt"
    present_output.write_text("ok\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present_output), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )
    return build_run_resume_plan(
        run={
            "runId": "run_resume_claim",
            "workflowRevisionId": "wfrev_resume",
            "status": "failed",
            "resultDir": str(result_dir),
        },
        job={"state": "failed"},
        attempts=[
            {
                "attemptId": "att_resume_source",
                "attemptNumber": 1,
                "leaseGeneration": 1,
                "state": "failed",
                "workDir": str(work_dir),
                "exitCode": 1,
                "finishedAt": "2099-06-07T10:00:10Z",
            }
        ],
        active_lease=None,
        managed_work_dir=str(tmp_path),
        managed_results_dir=str(result_dir),
    )


def _failed_source_attempt(tmp_path: Path):
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_resume_claim_state"
    create_run_record(
        cfg,
        server_id="srv_resume_claim",
        request_id="req_resume_claim",
        run_spec={
            "runId": run_id,
            "projectId": "proj_resume_claim",
            "pipelineId": "pipeline_resume_claim",
            "workflowRevisionId": "wfrev_resume",
            "execution": {"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
        },
        idempotency_key="idem_resume_claim",
        payload_hash="h" * 64,
    )
    source_claim = claim_next_run_job(
        cfg,
        worker_id="worker_resume_source",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert source_claim is not None
    source_work_dir = Path(str(source_claim["attempt"]["workDir"]))
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    present = result_dir / "present.txt"
    present.write_text("ok\n", encoding="utf-8")
    source_work_dir.mkdir(parents=True, exist_ok=True)
    (source_work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage="execute",
        message="Attempt failed.",
        request_id="req_resume_claim",
        attempt_id=source_claim["attemptId"],
        lease_generation=source_claim["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        source_claim["attemptId"],
        lease_generation=source_claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET result_dir = ?, finished_at = ?, last_updated_at = ? WHERE run_id = ?",
            (str(result_dir), "2099-06-07T10:00:10Z", "2099-06-07T10:00:10Z", run_id),
        )
        connection.commit()
    return cfg, run_id, source_claim


def _source_attempt_options(cfg, run_id: str) -> dict:
    from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context

    plan = fetch_run_execution_context(cfg, run_id)["resumePlan"]
    return build_run_resume_execution_options(plan)


def _claim_resume_target_attempt(cfg, run_id: str, options: dict) -> dict:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'queued', execution_options_json = ?, available_at = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (
                json.dumps(options, sort_keys=True, separators=(",", ":")),
                "2099-06-07T10:01:00Z",
                "2099-06-07T10:01:00Z",
                run_id,
            ),
        )
        connection.commit()
    target_claim = claim_next_run_job(
        cfg,
        worker_id="worker_resume_target",
        now="2099-06-07T10:01:00Z",
        lease_seconds=30,
    )
    assert target_claim is not None
    return target_claim
