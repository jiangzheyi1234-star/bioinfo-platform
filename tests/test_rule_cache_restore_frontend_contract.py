from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(name: str) -> str:
    return (COMPONENTS / name).read_text(encoding="utf-8")


def test_rule_cache_restore_frontend_wires_all_fenced_steps() -> None:
    api = _source("workflows-page-api.ts")
    model = _source("workflow-rule-cache-restore-model.ts")
    actions = _source("workflow-rule-cache-restore-actions.tsx")
    context_panel = _source("workflow-run-execution-context.tsx")
    detail_panel = _source("workflow-run-detail-panel.tsx")

    for suffix, confirmation in [
        ("pins/prepare", "prepare-rule-cache-restore-pins"),
        ("pins/apply", "apply-rule-cache-restore-pins"),
        ("staged-files/prepare", "prepare-rule-cache-restore-staged-files"),
        ("staged-files/apply", "apply-rule-cache-restore-staged-files"),
        ("final-outputs/prepare", "prepare-rule-cache-restore-final-outputs"),
        ("final-outputs/apply", "apply-rule-cache-restore-final-outputs"),
        ("adoption/prepare", "prepare-rule-cache-restore-adoption"),
        ("adoption/apply", "apply-rule-cache-restore-adoption"),
    ]:
        assert suffix in api
        assert confirmation in api

    assert "runWorkflowRuleCacheRestoreAction" in api
    assert "`/api/v1/runs/${encodeURIComponent(runId)}/rules/cache-restore/${endpoint}`" in api
    assert "planHash: request.planHash" in api
    assert "attemptId: request.attemptId" in api
    assert "leaseGeneration: request.leaseGeneration" in api
    assert 'actor: "workflow-ui"' in api
    assert "operator_confirmed_rule_cache_restore_${request.stage}_${request.action}" in api
    assert "invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY)" in api
    assert "invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY)" in api

    assert "WorkflowRuleCacheRestoreActions" in context_panel
    assert "plan={context.ruleCacheRestorePlan || context.ruleRetryExecutionPlan?.cacheRestorePlan}" in context_panel
    assert "attemptId={lease?.attemptId}" in context_panel
    assert "leaseGeneration={lease?.leaseGeneration}" in context_panel
    assert "onRunRuleCacheRestoreAction" in context_panel
    assert "runWorkflowRuleCacheRestoreAction(run.runId, request)" in detail_panel
    assert "setRuleCacheRestoreResult(result)" in detail_panel
    assert "await onRunChanged?.()" in detail_panel
    assert "ruleCacheRestoreError" in detail_panel

    assert 'WorkflowRuleCacheRestoreStage =\n  | "pins"' in model
    assert '"staged-files"' in model
    assert '"final-outputs"' in model
    assert '"adoption"' in model
    assert 'WorkflowRuleCacheRestoreAction = "prepare" | "apply"' in model
    assert "WorkflowRuleCacheRestoreRequest" in model
    assert "WorkflowRuleCacheRestoreResult" in model
    assert "artifactIdsExposed?: boolean" in model
    assert "pendingAdoptionCount?: number" in model
    assert "activePinCount?: number" in model
    assert "workflowRuleCacheRestorePlanReady" in model
    assert "window.confirm" in actions
    assert "unsafeProjection" in actions
    assert "cacheKeysExposed" in actions
    assert "storageUrisExposed" in actions
    assert "pathsExposed" in actions
    assert "busyKey === key" in actions
    assert "lastResult?.evidenceId" in actions


def test_rule_cache_restore_frontend_keeps_raw_storage_fields_out_of_ui_contract() -> None:
    model = _source("workflow-rule-cache-restore-model.ts")
    actions = _source("workflow-rule-cache-restore-actions.tsx")
    detail_panel = _source("workflow-run-detail-panel.tsx")
    source = "\n".join([model, actions, detail_panel])

    forbidden = [
        "cachePinIds",
        "cacheEntryIds",
        "artifactBlobIds",
        "cacheKey?:",
        "keyPayload?:",
        "keyPayloads?:",
        "storageUri?:",
        "localPath",
        "packagePath",
        "packageUri",
    ]
    for marker in forbidden:
        assert marker not in source
