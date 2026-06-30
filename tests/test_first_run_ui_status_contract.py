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
