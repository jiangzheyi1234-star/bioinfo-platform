from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_first_run_pilot_check_is_exposed_from_web_package() -> None:
    package = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["smoke:first-run"] == (
        "powershell -ExecutionPolicy Bypass -File ../../scripts/first_run_pilot_check.ps1"
    )


def test_first_run_pilot_check_verifies_single_user_first_result_contract() -> None:
    source = (REPO_ROOT / "scripts" / "first_run_pilot_check.ps1").read_text(encoding="utf-8")

    assert "FIRST_RUN_PILOT_CHECK_FAILED" in source
    assert "$ApiBase/health" in source
    assert "$ApiBase/api/v1/workflow-catalog" in source
    assert "$ApiBase/api/v1/workflow-scenario-packs" in source
    assert "moving-pictures-16s-rulegraph-v1" in source
    assert "moving-pictures-16s" in source
    assert "/workflows/first-run" in source
    assert "app/workflows/first-run/page.js" in source
    assert "resultPackage" in source
    assert "validationCard" in source
    assert "workflowRevision" in source
    assert "inputLineage" in source
    assert "outputChecksums" in source
    assert "[switch]$RunFirstSuccessfulRun" in source
    assert "[int]$RunTimeoutSeconds = 1800" in source
    assert "[int]$SampleDataTimeoutSeconds = 300" in source
    assert "$ApiBase/api/v1/servers?refresh=true" in source
    assert "a connected and ready server is required for first-run execution" in source
    assert "must be connected and ready for first-run execution" in source
    assert "$_.connected -eq $true -and $_.ready -eq $true -and $_.serverId" in source
    assert "$ApiBase/api/v1/workflow-sample-data/$([uri]::EscapeDataString($FirstRunPipelineId))/uploads" in source
    assert "$ApiBase/api/v1/runs" in source
    assert "projectId = \"first-run-pilot\"" in source
    assert "runSpec = (New-FirstRunRunSpec $uploads)" in source
    assert "$ApiBase/api/v1/runs/$([uri]::EscapeDataString($TargetRunId))/detail" in source
    assert "first-run did not complete within $RunTimeoutSeconds seconds" in source
    assert "/api/v1/first-run/runs/$([uri]::EscapeDataString($RunId))/finalize" in source
    assert "h2ometa.first-run.finalization.v1" in source
    assert "ready finalization must include validationCard and resultPackage" in source
    assert "ready finalization must include a single-user-lab pilotHandoff" in source
    assert "function Assert-FirstRunPilotHandoff" in source
    assert "pilotHandoff evidence must match validationCard run and result" in source
    assert "pilotHandoff evidence must match resultPackage hashes" in source
    assert "pilotHandoff evidence must match validationCard resultPackage hashes" in source
    assert "ready validationCard checks must all be passed" in source
    assert "pilotHandoff evidence must match validationCard checks" in source
    assert "backupRestore handoff must include the read-only backup plan command" in source
    assert "backupRestore handoff must include the submitted-run restore proof command" in source
    assert "backupRestore handoff must reject hot sqlite copy, secret archive, and cache-as-durable-state" in source
    assert "pilotHandoff must include next scenario pilots" in source
    assert "taxonomy-classification" in source
    assert "amr-annotation" in source
    assert "pilotHandoff nextScenarios $scenarioId must remain blocked until operator gates pass" in source
    assert "pilotHandoff nextScenarios $scenarioId must include blocked gate evidence" in source
    assert "taxonomy nextScenario must advertise one available database pack" in source
    assert "AMR nextScenario must advertise missing database pack templates" in source
    assert "RUN_OWN_SMALL_SAMPLE" in source
    assert "$handoffProof = Assert-FirstRunPilotHandoff $finalization" in source
    assert "pilotHandoffSchemaVersion = $handoff.schemaVersion" in source
    assert "backupRestoreSchemaVersion = $backup.schemaVersion" in source
    assert "nextScenarioIds = @($nextScenarios | ForEach-Object { $_.scenarioId })" in source
    assert "handoffProof = $handoffProof" in source
    assert "blocked finalization must include nextAction code and target" in source
    assert "if ($RequireFinalizationReady -or $RunFirstSuccessfulRun)" in source
    assert "-RunFirstSuccessfulRun cannot be combined with -RunId" in source
    assert "-RequireFinalizationReady requires -RunId or -RunFirstSuccessfulRun" in source
    assert 'SmokeOnly = "catalog-page-smoke"' in source
    assert 'FinalizedRun = "finalized-run"' in source
    assert 'SubmittedRun = "submitted-run"' in source
    assert "$closedLoopProven = $false" in source
    assert "$closedLoopProven = $true" in source
    assert "serverId = $ServerId" in source
    assert "closedLoopProven = $closedLoopProven" in source
    assert "closedLoopProofMode = $closedLoopProofMode" in source
    assert "h2ometa.first-run-pilot-check.v1" in source


def test_first_run_pilot_docs_keep_mutating_proof_explicit() -> None:
    source = (REPO_ROOT / "docs" / "release-candidate-operating-loop.md").read_text(encoding="utf-8")

    assert "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady" in source
    assert 'closedLoopProven: true' in source
    assert 'closedLoopProofMode: "submitted-run"' in source
