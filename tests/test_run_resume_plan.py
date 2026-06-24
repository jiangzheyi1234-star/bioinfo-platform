from __future__ import annotations

from apps.remote_runner.execution_resume_plan import build_run_resume_plan


def test_run_resume_plan_previews_snakemake_rerun_incomplete_without_enabling_execution() -> None:
    plan = build_run_resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease=None,
    )

    assert plan["schemaVersion"] == "run-resume-plan.v1"
    assert plan["supported"] is False
    assert plan["eligible"] is False
    assert plan["eligibleNow"] is False
    assert plan["executionEnabled"] is False
    assert plan["commandPreviewAvailable"] is True
    assert plan["reasonCode"] == "RUN_RESUME_PREVIEW_AVAILABLE"
    assert plan["latestAttempt"]["state"] == "failed"
    assert plan["workdirEvidence"] == {
        "available": True,
        "workDirReusable": False,
        "pathExposed": False,
        "reasonCode": "WORKDIR_REUSE_POLICY_UNPROVEN",
    }
    assert plan["incompleteOutputAudit"]["reasonCode"] == "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN"
    assert plan["artifactAdoptionBoundary"]["reasonCode"] == "ARTIFACT_ADOPTION_UNPROVEN"
    assert plan["snakemakeOptions"] == {
        "schemaVersion": "snakemake-run-resume-options.v1",
        "rerunIncomplete": True,
        "argsPreview": ["--rerun-incomplete"],
        "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
    }
    assert "RUN_RESUME_MUTATION_API_DISABLED" in plan["blockedReasonCodes"]


def test_run_resume_plan_blocks_without_workflow_revision() -> None:
    plan = build_run_resume_plan(
        run=_run(status="failed", workflow_revision_id=""),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease=None,
    )

    assert plan["commandPreviewAvailable"] is False
    assert plan["reasonCode"] == "WORKFLOW_REVISION_MISSING"
    assert plan["snakemakeOptions"]["argsPreview"] == []


def test_run_resume_plan_blocks_active_lease_and_non_resumable_attempt() -> None:
    active = build_run_resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease={"state": "active"},
    )
    succeeded_attempt = build_run_resume_plan(
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
    plan = build_run_resume_plan(
        run=_run(status="failed", workflow_revision_id="wfrev_resume"),
        job=_job(state="failed", dead_lettered_at="2099-06-07T10:00:03Z"),
        attempts=[_attempt(state="failed", work_dir_present=True)],
        active_lease=None,
    )

    assert plan["reasonCode"] == "RUN_RESUME_DEAD_LETTERED"
    assert plan["commandPreviewAvailable"] is False


def _run(*, status: str, workflow_revision_id: str) -> dict[str, object]:
    return {
        "runId": "run_resume",
        "workflowRevisionId": workflow_revision_id,
        "status": status,
    }


def _job(*, state: str, dead_lettered_at: str | None = None) -> dict[str, object]:
    return {
        "state": state,
        "deadLetteredAt": dead_lettered_at,
    }


def _attempt(*, state: str, work_dir_present: bool) -> dict[str, object]:
    return {
        "attemptId": f"att_{state}",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "state": state,
        "exitCode": 1 if state == "failed" else 0,
        "finishedAt": "2099-06-07T10:00:03Z",
        "updatedAt": "2099-06-07T10:00:03Z",
        "workDirPresent": work_dir_present,
    }
