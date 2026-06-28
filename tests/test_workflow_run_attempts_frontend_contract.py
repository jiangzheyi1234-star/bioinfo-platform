from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_run_attempts_frontend_uses_stable_read_model_endpoint() -> None:
    api = _source("workflow-run-attempts-api.ts")
    model = _source("workflow-run-attempts-model.ts")
    panel = _source("workflow-run-attempts-panel.tsx")
    detail = _source("workflow-run-detail-panel.tsx")
    rules_panel = _source("workflow-run-rules-panel.tsx")

    assert "export type WorkflowRunAttemptsReadModel" in model
    assert "export type WorkflowRunAttemptSummary" in model
    assert "export type WorkflowRunExecutionSlot" in model
    assert "export type WorkflowRunAttemptsRedactionPolicy" in model
    assert "attempts?: WorkflowRunExecutionAttempt[]" in model
    assert "activeLease?: WorkflowRunExecutionLease | null" in model
    assert "slots?: WorkflowRunExecutionSlot[]" in model
    assert "redactionPolicy?: WorkflowRunAttemptsRedactionPolicy" in model

    assert "export async function fetchWorkflowRunAttempts" in api
    assert "WORKFLOW_RUN_ID_REQUIRED" in api
    assert "cachedAsync(key, 6_000" in api
    assert "requestLocalApiJson<WorkflowRunAttemptsResponse>(" in api
    assert '"GET"' in api
    assert "`/api/v1/runs/${encodeURIComponent(normalizedRunId)}/attempts`" in api
    assert "{ cache: \"no-store\" }" in api
    assert "attempts: response.data.attempts || []" in api
    assert "slots: response.data.slots || []" in api

    assert "export function WorkflowRunAttemptsPanel" in panel
    assert "export function RuleAttemptBadge" in panel
    assert "export function runAttemptByRule" in panel
    assert "setAttempts(null)" in panel
    assert "onAttemptsLoaded?.(null)" in panel
    assert "AttemptReadModelSummary" in panel
    assert "AttemptTimeline" in panel
    assert "AttemptRedactionNotice" in panel
    assert "active lease" in panel
    assert "slot states" in panel
    assert "当前远程 runner 未暴露 run attempts API" in panel
    assert "run-attempts.v1" in panel

    assert "WorkflowRunAttemptsPanel" in detail
    assert "RuleAttemptBadge" in rules_panel
    assert "runAttemptByRule" in rules_panel
    assert "const [runAttempts, setRunAttempts]" in detail
    assert "onAttemptsLoaded={setRunAttempts}" in detail
    assert "<WorkflowRunRulesPanel attempts={runAttempts} rules={rules} rulesModel={detail.rules} />" in detail


def test_run_attempts_frontend_keeps_observability_read_only_and_redacted() -> None:
    api = _source("workflow-run-attempts-api.ts")
    model = _source("workflow-run-attempts-model.ts")
    panel = _source("workflow-run-attempts-panel.tsx")
    detail = _source("workflow-run-detail-panel.tsx")

    for source in (api, panel):
        assert '"POST"' not in source
        assert '"PUT"' not in source
        assert '"PATCH"' not in source
        assert '"DELETE"' not in source

    for source in (panel,):
        assert "onRetryRule" not in source
        assert "retryRule" not in source
        assert "resumeRun" not in source
        assert "onResumeRun" not in source
    assert "WorkflowRunExecutionContextPanel" in detail
    assert "onResumeRun={handleResumeRun}" in detail

    projected_sensitive_fields = (
        "workDir?:",
        "processPid?:",
        "processGroupId?:",
        "runSpec?:",
        "executionOptions?:",
        "commandPayload?:",
        "slotErrorDetails?:",
        "storageUri?:",
        "localPath?:",
    )
    for forbidden in projected_sensitive_fields:
        assert forbidden not in model
        assert forbidden not in panel

    assert "workDirExposed?: boolean" in model
    assert "processIdentifiersExposed?: boolean" in model
    assert "commandPayloadExposed?: boolean" in model
    assert "runSpecExposed?: boolean" in model
    assert "slotErrorDetailsExposed?: boolean" in model
