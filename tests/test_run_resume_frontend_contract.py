from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(name: str) -> str:
    return (COMPONENTS / name).read_text(encoding="utf-8")


def test_run_resume_frontend_wires_confirmation_gated_plan_hash_request() -> None:
    api = _source("workflows-page-api.ts")
    model = _source("workflow-run-resume-model.ts")
    action = _source("workflow-run-resume-action.tsx")
    context_panel = _source("workflow-run-execution-context.tsx")
    detail_panel = _source("workflow-run-detail-panel.tsx")

    assert "resumeWorkflowRun" in api
    assert "`/api/v1/runs/${encodeURIComponent(runId)}/resume`" in api
    assert 'confirmation: "resume-run"' in api
    assert "planHash: request.planHash" in api
    assert 'actor: "workflow-ui"' in api
    assert 'reason: "operator_confirmed_run_resume"' in api
    assert "invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY)" in api
    assert "invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY)" in api

    assert "WorkflowRunResumeRequest" in model
    assert "WorkflowRunResumeResult" in model
    assert "WorkflowRunResumeResponse" in model
    assert "workflowRunResumeCanSubmit" in model
    assert "plan?.executionEnabled === true" in model
    assert "plan.eligibleNow === true" in model
    assert "plan.commandPreviewAvailable === true" in model
    assert "plan.planHash.length === 64" in model
    assert "readiness?.executionReady === true" in model
    assert "readiness.executionEnabled === true" in model
    assert "(readiness.blockedCheckCount || 0) === 0" in model
    assert "workdir?.workDirReusable === true" in model
    assert "outputAudit?.available === true" in model
    assert "(outputAudit.unsafeOutputCount || 0) === 0" in model
    assert "(outputAudit.uncheckedOutputCount || 0) === 0" in model
    assert "(outputAudit.unverifiedOutputCount || 0) === 0" in model
    assert "(adoption?.enabled === true || adoption?.available === true)" in model
    assert "orchestration?.contractReady === true" in model
    assert "orchestration.executorReady === true" in model
    assert "orchestration.queueMutationAllowed === true" in model
    assert "orchestration.runStateMutationAllowed === true" in model
    assert "pathsExposed !== true" in model
    assert "storageUrisExposed !== true" in model
    assert "pathExposed !== true" in model
    assert "storageUriExposed !== true" in model

    assert "WorkflowRunResumeAction" in action
    assert "window.confirm" in action
    assert "workflowRunResumeCanSubmit(plan)" in action
    assert "plan.executionReasonCode" in action
    assert "plan.activationReadiness?.reasonCode" in action
    assert "workdir reuse blocked" in action
    assert "output audit unverified" in action
    assert "artifact adoption blocked" in action
    assert "executor not ready" in action
    assert "const planHash = plan.planHash || \"\"" in action
    assert "onResume?.({ planHash })" in action

    assert "onResumeRun" in context_panel
    assert "plan={context.resumePlan}" in context_panel
    assert "resumingRun" in context_panel
    assert "resumeResult" in context_panel
    assert "resumeWorkflowRun(run.runId, request)" in detail_panel
    assert "setResumeResult(result)" in detail_panel
    assert "resumeError" in detail_panel
    assert "await onRunChanged?.()" in detail_panel


def test_run_resume_frontend_action_contract_stays_public_and_path_redacted() -> None:
    model = _source("workflow-run-resume-model.ts")
    action = _source("workflow-run-resume-action.tsx")
    source = "\n".join([model, action])

    for marker in [
        "runSpec",
        "executionOptions",
        "snakemakeOptions",
        "argsPreview",
        "targetOutputKeys",
        "storageUri?:",
        "storageUris?:",
        "localPath",
        "resultDir",
        "cacheKey",
        "artifactBlobId",
        "outputAdoptionScope",
        "operatorFreeText",
    ]:
        assert marker not in source

    assert "commandId?: string" in model
    assert "jobId?: string" in model
    assert "remainingAttempts?: number" in model
    assert "reasonCode?: string" in model
