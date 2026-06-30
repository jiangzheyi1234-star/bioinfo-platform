from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRST_RUN_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "first-run"
FIRST_RUN_COMPONENTS = FIRST_RUN_ROUTE / "_components"
FIRST_RUN_DOMAIN = FIRST_RUN_ROUTE / "_domain"


def test_first_run_ui_steps_and_report_are_status_contract_driven() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_report = (FIRST_RUN_COMPONENTS / "workflow-first-run-report.tsx").read_text(encoding="utf-8")
    first_run_progress = (FIRST_RUN_DOMAIN / "first-run-progress.ts").read_text(encoding="utf-8")
    first_run_types = (FIRST_RUN_DOMAIN / "first-run-types.ts").read_text(encoding="utf-8")

    assert 'import type { FirstRunStatus } from "./first-run-types"' in first_run_progress
    assert "reportEvidence?: FirstRunStatusEvidence[\"report\"]" in first_run_report
    assert "ready: reportEvidence?.ready === true" in first_run_report
    assert 'run?.status === "completed" && outputs.every' not in first_run_report
    assert "firstRunStepIdForStage" in first_run_progress
    assert 'stage === "inspect_failed_run"' in first_run_progress
    assert "hasStatus ? evidence?.sampleCache?.status === \"ready\" : input.sampleReady" in first_run_progress
    assert "hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted" in first_run_progress
    assert "action?.code === \"FINALIZE_FIRST_RUN\"" in first_run_progress
    assert "firstRunStatus: firstRunStatusSnapshot || null" in first_run_page
    assert "input.reportReady" not in first_run_progress
    assert "input.packageReady" not in first_run_progress
    assert "input.validationReady" not in first_run_progress
    assert "input.runFailed" not in first_run_progress
    assert "runCompleted" not in first_run_progress
    assert "runTerminal" not in first_run_progress
    assert "includeArtifacts?: boolean;" in first_run_types
    assert "const reportReady = runCompleted && artifacts.length > 0" not in first_run_page
    assert "const reportReady =" not in first_run_page
    assert "evidence?.report?.ready === true" in first_run_progress
    assert "reportEvidence={firstRunStatusSnapshot?.evidence?.report}" in first_run_page
    assert "firstRunStatus={firstRunStatusSnapshot || null}" in first_run_page


def test_first_run_validation_and_trust_summary_are_status_contract_driven() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_completion = (FIRST_RUN_COMPONENTS / "workflow-first-run-completion.tsx").read_text(encoding="utf-8")
    first_run_trust_summary = (FIRST_RUN_COMPONENTS / "workflow-first-run-trust-summary.tsx").read_text(encoding="utf-8")
    first_run_validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")

    assert "firstRunStatus={firstRunStatusSnapshot || null}" in first_run_page
    assert "firstRunStatus: FirstRunStatus | null" in first_run_completion
    assert "firstRunStatus?: FirstRunStatus | null" not in first_run_completion
    assert "status: FirstRunStatus | null" in first_run_trust_summary
    assert "status?: FirstRunStatus | null" not in first_run_trust_summary
    assert "const validationEvidence = firstRunStatus?.evidence?.validation" in first_run_validation
    assert "const validationPassed = validationEvidence?.ready === true" in first_run_validation
    assert "data-validation-passed={validationPassed ? \"true\" : \"false\"}" in first_run_validation
    assert "evidence?.validation?.ready === true" in first_run_trust_summary
    assert "evidence?.sampleCache?.status === \"ready\"" in first_run_trust_summary
    assert "evidence?.report?.ready === true" in first_run_trust_summary
    assert "resultPackage?.ready === true" in first_run_trust_summary
    assert "FirstRunTrustSummary status={firstRunStatus}" in first_run_validation
    assert "FirstRunTrustSummary status={firstRunStatus}" in first_run_completion
    assert "firstRunValidationCardPassed" not in first_run_validation
    assert "?? checks.filter" not in first_run_trust_summary
    assert "|| packageExport?.sha256" not in first_run_trust_summary
    assert "|| packageExport?.manifestSha256" not in first_run_trust_summary
    assert "latestPackage?.sha256 || resultPackageEvidence?.sha256" not in first_run_completion
    assert "latestPackage?.manifestSha256 || resultPackageEvidence?.manifestSha256" not in first_run_completion
    assert "validationChecksPassed ?? checks.filter" not in first_run_validation
    assert not (FIRST_RUN_DOMAIN / "first-run-validation-state.ts").exists()


def test_first_run_conductor_uses_status_contract_before_local_run_hints() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_conductor = (FIRST_RUN_COMPONENTS / "workflow-first-run-conductor.tsx").read_text(encoding="utf-8")

    assert "firstRunStatus: firstRunStatusSnapshot || null" in first_run_page
    assert "statusAction: firstRunStatusSnapshot?.nextAction || null" not in first_run_page
    assert "firstRunStatus: FirstRunStatus | null" in first_run_conductor
    assert "statusAction?: FirstRunNextAction | null" not in first_run_conductor
    assert "const status = input.firstRunStatus" in first_run_conductor
    assert "hasStatus ? evidence?.sampleCache?.status === \"ready\" : input.sampleReady" in first_run_conductor
    assert "hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted" in first_run_conductor
    assert "return continueActionFromStatus(status.nextAction)" in first_run_conductor


def test_first_run_evidence_actions_use_status_run_id_before_local_run() -> None:
    first_run_evidence_state = (FIRST_RUN_ROUTE / "_state" / "use-first-run-evidence.ts").read_text(encoding="utf-8")

    assert 'const firstRunRunId = statusRun?.runId || run?.runId || ""' in first_run_evidence_state
    assert 'const runStatus = statusRun?.status || run?.status || ""' in first_run_evidence_state
    assert "fetchFirstRunValidationCard(firstRunRunId" in first_run_evidence_state
    assert "finalizeFirstRun(firstRunRunId" in first_run_evidence_state
    assert "runId: firstRunRunId" in first_run_evidence_state
    assert "if (!run?.runId" not in first_run_evidence_state
    assert "fetchFirstRunValidationCard(run.runId" not in first_run_evidence_state
    assert "finalizeFirstRun(run.runId" not in first_run_evidence_state
