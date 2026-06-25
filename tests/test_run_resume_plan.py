from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.execution_plan_hash import stable_plan_hash
from apps.remote_runner.execution_resume_plan import build_run_resume_plan


def test_run_resume_plan_previews_snakemake_rerun_incomplete_without_enabling_execution(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    result_dir = tmp_path / "results"
    work_dir.mkdir()
    result_dir.mkdir()
    present_output = result_dir / "present.txt"
    present_output.write_text("ok\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present_output), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )

    plan = _resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume", result_dir=result_dir),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True, work_dir=work_dir)],
        active_lease=None,
        managed_work_dir=tmp_path,
        managed_results_dir=result_dir,
    )

    assert plan["schemaVersion"] == "run-resume-plan.v1"
    assert len(plan["planHash"]) == 64
    assert plan["planHash"] == stable_plan_hash(plan)
    assert plan["supported"] is False
    assert plan["eligible"] is False
    assert plan["eligibleNow"] is False
    assert plan["executionEnabled"] is False
    assert plan["activationReadiness"]["schemaVersion"] == "run-resume-activation-readiness.v1"
    assert plan["activationReadiness"]["executionReady"] is False
    assert plan["activationReadiness"]["executionEnabled"] is False
    assert plan["activationReadiness"]["reasonCode"] == "WORKDIR_REUSE_POLICY_UNPROVEN"
    assert plan["activationReadiness"]["readyCheckCount"] == 2
    assert plan["activationReadiness"]["blockedCheckCount"] == 4
    assert plan["activationReadiness"]["summary"] == {
        "attemptCount": 1,
        "expectedOutputCount": 2,
        "checkedOutputCount": 2,
        "existingOutputCount": 1,
        "missingOutputCount": 1,
        "unsafeOutputCount": 0,
        "uncheckedOutputCount": 0,
        "unverifiedOutputCount": 2,
    }
    assert plan["activationReadiness"]["redactionPolicy"]["pathsExposed"] is False
    assert plan["commandPreviewAvailable"] is True
    assert plan["reasonCode"] == "RUN_RESUME_PREVIEW_AVAILABLE"
    assert plan["latestAttempt"]["state"] == "failed"
    assert plan["workdirEvidence"] == {
        "available": True,
        "workDirReusable": False,
        "pathExposed": False,
        "reasonCode": "WORKDIR_REUSE_POLICY_UNPROVEN",
    }
    assert plan["incompleteOutputAudit"]["schemaVersion"] == "run-output-audit.v1"
    assert plan["incompleteOutputAudit"]["available"] is True
    assert plan["incompleteOutputAudit"]["pathExposed"] is False
    assert plan["incompleteOutputAudit"]["expectedOutputCount"] == 2
    assert plan["incompleteOutputAudit"]["checkedOutputCount"] == 2
    assert plan["incompleteOutputAudit"]["existingOutputCount"] == 1
    assert plan["incompleteOutputAudit"]["missingOutputCount"] == 1
    assert plan["incompleteOutputAudit"]["unsafeOutputCount"] == 0
    assert plan["incompleteOutputAudit"]["unverifiedOutputCount"] == 2
    assert plan["incompleteOutputAudit"]["reasonCode"] == "OUTPUT_AUDIT_MISSING_OUTPUTS"
    assert [item["key"] for item in plan["incompleteOutputAudit"]["outputs"]] == ["present", "missing"]
    assert all(item["pathExposed"] is False and "path" not in item for item in plan["incompleteOutputAudit"]["outputs"])
    assert plan["artifactAdoptionBoundary"]["reasonCode"] == "ARTIFACT_ADOPTION_UNPROVEN"
    assert plan["snakemakeOptions"] == {
        "schemaVersion": "snakemake-run-resume-options.v1",
        "rerunIncomplete": True,
        "argsPreview": ["--rerun-incomplete"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }
    assert "RUN_RESUME_MUTATION_API_DISABLED" in plan["blockedReasonCodes"]


def test_run_resume_plan_blocks_without_workflow_revision() -> None:
    plan = _resume_plan(
        run=_run(status="failed", workflow_revision_id=""),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease=None,
    )

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "WORKFLOW_REVISION_MISSING"
    assert plan["snakemakeOptions"]["argsPreview"] == []


def test_run_resume_plan_blocks_active_lease_and_non_resumable_attempt() -> None:
    active = _resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease={"state": "active"},
    )
    succeeded_attempt = _resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed"),
        attempts=[_attempt(state="succeeded", work_dir_present=True)],
        active_lease=None,
    )

    assert active["reasonCode"] == "ACTIVE_LEASE"
    assert active["commandPreviewAvailable"] is False
    assert succeeded_attempt["reasonCode"] == "RUN_RESUME_LATEST_ATTEMPT_NOT_RESUMABLE"
    assert succeeded_attempt["commandPreviewAvailable"] is False


def test_run_resume_plan_blocks_dead_lettered_jobs() -> None:
    plan = _resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed", dead_lettered_at="2099-06-07T10:00:03Z"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease=None,
    )

    assert plan["reasonCode"] == "RUN_RESUME_DEAD_LETTERED"
    assert plan["commandPreviewAvailable"] is False


def _run(*, status: str, workflow_revision_id: str, result_dir: Path | None = None) -> dict[str, object]:
    return {
        "runId": "run_resume",
        "workflowRevisionId": workflow_revision_id,
        "status": status,
        "resultDir": str(result_dir or ""),
    }


def _job(*, state: str, dead_lettered_at: str | None = None) -> dict[str, object]:
    return {
        "state": state,
        "deadLetteredAt": dead_lettered_at,
    }


def _attempt(*, state: str, work_dir_present: bool, work_dir: Path | None = None) -> dict[str, object]:
    attempt = {
        "attemptId": f"att_{state}",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "state": state,
        "exitCode": 1 if state == "failed" else 0,
        "finishedAt": "2099-06-07T10:00:03Z",
        "updatedAt": "2099-06-07T10:00:03Z",
        "workDirPresent": work_dir_present,
    }
    if work_dir is not None:
        attempt["workDir"] = str(work_dir)
    return attempt


def _resume_plan(
    *,
    run: dict[str, object],
    job: dict[str, object] | None,
    attempts: list[dict[str, object]],
    active_lease: dict[str, object] | None,
    managed_work_dir: Path | str = ".",
    managed_results_dir: Path | str = ".",
) -> dict[str, object]:
    return build_run_resume_plan(
        run=run,
        job=job,
        attempts=attempts,
        active_lease=active_lease,
        managed_work_dir=str(managed_work_dir),
        managed_results_dir=str(managed_results_dir),
    )
