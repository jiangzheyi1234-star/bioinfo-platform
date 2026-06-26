from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(name: str) -> str:
    return (COMPONENTS / name).read_text(encoding="utf-8")


def test_rule_retry_frontend_wires_confirmation_gated_plan_hash_request() -> None:
    api = _source("workflows-page-api.ts")
    model = _source("workflow-rule-retry-model.ts")
    action = _source("workflow-rule-retry-action.tsx")
    context_panel = _source("workflow-run-execution-context.tsx")
    detail_panel = _source("workflow-run-detail-panel.tsx")

    assert "retryWorkflowRunRules" in api
    assert "`/api/v1/runs/${encodeURIComponent(runId)}/rules/retry`" in api
    assert 'confirmation: "retry-failed-rules"' in api
    assert "planHash: request.planHash" in api
    assert 'actor: "workflow-ui"' in api
    assert 'reason: "operator_confirmed_rule_retry"' in api
    assert "invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY)" in api
    assert "invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY)" in api

    assert "WorkflowRuleRetryRequest" in model
    assert "WorkflowRuleRetryResult" in model
    assert "WorkflowRuleRetryResponse" in model
    assert "workflowRuleRetryCanSubmit" in model
    assert "plan?.executionEnabled === true" in model
    assert "plan.eligibleNow === true" in model
    assert "plan.planHash.length === 64" in model
    assert "(plan.selectedRules?.length || 0) > 0" in model
    assert "readiness?.executionReady === true" in model
    assert "readiness.executionEnabled === true" in model
    assert "(readiness.blockedCheckCount || 0) === 0" in model
    assert "orchestration?.contractReady === true" in model
    assert "orchestration.executorReady === true" in model
    assert "orchestration.queueMutationAllowed === true" in model
    assert "orchestration.runStateMutationAllowed === true" in model
    assert "orchestration.launchReady === true" in model
    assert "orchestration.executionBoundaryReady === true" in model
    assert "launch?.preflightReady === true" in model
    assert "launch.executorStartAllowed === true" in model
    assert "boundary?.boundaryReady === true" in model
    assert "boundary.executorStartAllowed === true" in model
    assert "pathsExposed !== true" in model
    assert "storageUrisExposed !== true" in model

    assert "WorkflowRuleRetryAction" in action
    assert "window.confirm" in action
    assert "workflowRuleRetryCanSubmit(plan)" in action
    assert "plan.executionReasonCode" in action
    assert "plan.activationReadiness?.reasonCode" in action
    assert "executor not ready" in action
    assert "launch preflight blocked" in action
    assert "execution boundary blocked" in action
    assert "const planHash = plan.planHash || \"\"" in action
    assert "onRetry?.({ planHash })" in action

    assert "onRetryRunRules" in context_panel
    assert "plan={context.ruleRetryExecutionPlan}" in context_panel
    assert "retryingRunRules" in context_panel
    assert "ruleRetryResult" in context_panel
    assert "retryWorkflowRunRules(run.runId, request)" in detail_panel
    assert "setRuleRetryResult(result)" in detail_panel
    assert "ruleRetryError" in detail_panel
    assert "await onRunChanged?.()" in detail_panel


def test_rule_retry_frontend_result_contract_stays_public_and_path_redacted() -> None:
    model = _source("workflow-rule-retry-model.ts")
    action = _source("workflow-rule-retry-action.tsx")
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
        "workdir",
        "cacheKey",
        "artifactBlobId",
        "outputAdoptionScope",
        "operatorFreeText",
    ]:
        assert marker not in source

    assert "commandId?: string" in model
    assert "jobId?: string" in model
    assert "selectedRuleCount?: number" in model
    assert "rerunRuleCount?: number" in model
    assert "remainingAttempts?: number" in model
