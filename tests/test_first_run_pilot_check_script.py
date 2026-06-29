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
    assert '$RequiredEvidence = @("resultPackage", "validationCard", "evidenceBundle"' in source
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
    assert "function Assert-ExecutionReadiness" in source
    assert "$ApiBase/api/v1/servers/$([uri]::EscapeDataString($ResolvedServerId))/execution-diagnostics" in source
    assert "execution diagnostics readiness must be ok" in source
    assert "blockingReasonCount = $blockingReasons.Count" in source
    assert "$executionReadinessProof = Assert-ExecutionReadiness $ServerId" in source
    assert "function Get-SampleUploadRoleAudit" in source
    assert "function New-SampleUploadProof" in source
    assert "sampleUploadProof = New-SampleUploadProof $uploads" in source
    assert "h2ometa.first-run.sample-upload-proof.v1" in source
    assert "h2ometa.workflow-sample-data-prep-proof.v1" in source
    assert "sample upload $role must include sample prep proof" in source
    assert "sampleDataPrepProof = @{" in source
    assert "items = @($Uploads | ForEach-Object { $_.prepProof })" in source
    assert "metadata\", \"barcodes\", \"sequences" in source
    assert "sample uploads include unexpected roles" in source
    assert "sample uploads include duplicate roles" in source
    assert "sha256 = $upload.sha256" in source
    assert "expectedSha256 = $upload.expectedSha256" in source
    assert "unexpectedRoles = $unexpectedRoles" in source
    assert "duplicateRoles = $duplicateRoles" in source
    assert "prepProofPassedCount = $passedPrepItems.Count" in source
    assert (
        "passed = ($missingRoles.Count -eq 0 -and $unexpectedRoles.Count -eq 0 "
        "-and $duplicateRoles.Count -eq 0 -and $passedItems.Count -eq $requiredRoles.Count "
        "-and $passedPrepItems.Count -eq $requiredRoles.Count)"
    ) in source
    assert "passedCount = $passedItems.Count" in source
    assert "expectedRoles = $requiredRoles" in source
    assert "missingRoles = $missingRoles" in source
    assert "$ApiBase/api/v1/workflow-sample-data/$([uri]::EscapeDataString($FirstRunPipelineId))/uploads" in source
    assert "$ApiBase/api/v1/runs" in source
    assert "projectId = \"first-run-pilot\"" in source
    assert "runSpec = (New-FirstRunRunSpec $uploads)" in source
    assert "$ApiBase/api/v1/runs/$([uri]::EscapeDataString($TargetRunId))/detail" in source
    assert "first-run did not complete within $RunTimeoutSeconds seconds" in source
    assert "/api/v1/first-run/runs/$([uri]::EscapeDataString($RunId))/finalize" in source
    assert "h2ometa.first-run.finalization.v1" in source
    assert "ready finalization must include validationCard, resultPackage, and evidenceBundle" in source
    assert "ready finalization must include a single-user-lab pilotHandoff" in source
    assert "h2ometa.first-run.evidence-bundle.v1" in source
    assert "ready finalization must expose the same first-run evidenceBundle" in source
    assert "first-run evidenceBundle must include exactly one $role file" in source
    assert "first-run evidenceBundle result package file must match package hashes" in source
    assert "first-run evidenceBundle $role filename must be" in source
    assert "keep-result-package-validation-card-and-handoff-together" in source
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
    assert "pilotHandoff nextScenarios $scenarioId must include tool slice promotion handoff" in source
    assert "pilotHandoff nextScenarios $scenarioId tool slice promotion must require WorkflowReady" in source
    assert "pilotHandoff nextScenarios $scenarioId tool option must include acceptance evidence contract" in source
    assert "pilotHandoff nextScenarios $scenarioId tool option acceptance evidence must be explicit" in source
    assert "pilotHandoff nextScenarios $scenarioId tool option must reject pending string-only evidence" in source
    assert "pilotHandoff nextScenarios $scenarioId tool option evidence pointers must cover required evidence" in source
    assert "pilotHandoff nextScenarios $scenarioId tool promotion evidence must be explicit" in source
    assert "pilotHandoff nextScenarios $scenarioId tool promotion checklist must include RuleSpec proof" in source
    assert "pilotHandoff nextScenarios $scenarioId tool promotion checklist must include smoke fixture proof" in source
    assert "pilotHandoff nextScenarios $scenarioId tool promotion must end in scenario evidence bundle" in source
    assert "pilotHandoff nextScenarios $scenarioId tool promotion must reject tool-count-only readiness" in source
    assert "pilotHandoff nextScenarios $scenarioId must include database install handoff" in source
    assert "pilotHandoff nextScenarios $scenarioId database install handoff must stay manual" in source
    assert "pilotHandoff nextScenarios $scenarioId ready scan schema must be database-pack-ready-scan v1" in source
    assert "pilotHandoff nextScenarios $scenarioId ready scan endpoint must be declared" in source
    assert "pilotHandoff nextScenarios $scenarioId registration prefill must come from ready scan" in source
    assert "pilotHandoff nextScenarios $scenarioId registration prefill must preserve pack lineage" in source
    assert "pilotHandoff nextScenarios $scenarioId database install handoff must reject automatic install" in source
    assert "taxonomy nextScenario must advertise one available database pack" in source
    assert "AMR nextScenario must advertise missing database pack templates" in source
    assert "RUN_OWN_SMALL_SAMPLE" in source
    assert "$handoffProof = Assert-FirstRunPilotHandoff $finalization" in source
    assert "pilotHandoffSchemaVersion = $handoff.schemaVersion" in source
    assert "evidenceBundleSchemaVersion = $bundle.schemaVersion" in source
    assert "evidenceBundleFileRoles = @($requiredFiles | ForEach-Object { $_.role })" in source
    assert "backupRestoreSchemaVersion = $backup.schemaVersion" in source
    assert "nextScenarioIds = @($nextScenarios | ForEach-Object { $_.scenarioId })" in source
    assert "$nextScenarioDatabasePackCoverage = @($nextScenarios | ForEach-Object" in source
    assert "nextScenarioDatabasePackCoverage = $nextScenarioDatabasePackCoverage" in source
    assert "toolSliceRequiredState = $_.toolSlicePromotionHandoff.requiredState" in source
    assert "toolSlicePromotionEvidence = @($_.toolSlicePromotionHandoff.promotionContract.requiredEvidence)" in source
    assert "toolAcceptanceContractCount = @($_.toolSlicePromotionHandoff.toolOptions | Where-Object" in source
    assert "readyScanPath = $_.databaseInstallHandoff.readyScan.path" in source
    assert "registrationPrefillSource = $_.databaseInstallHandoff.registration.prefillSource" in source
    assert "handoffProof = $handoffProof" in source
    assert "function Assert-FirstRunBlockedNextAction" in source
    assert 'FIRST_RUN_WORKFLOW_REVISION_REQUIRED = "/workflows/first-run#runner-readiness"' in source
    assert 'FIRST_RUN_REPORT_PREVIEW_REQUIRED = "/workflows/first-run#run-report"' in source
    assert 'FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH = "/workflows/first-run#sample-data"' in source
    assert 'FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED = "/workflows/first-run#evidence-bundle"' in source
    assert 'FIRST_RUN_PILOT_HANDOFF_REQUIRED = "/workflows/first-run#evidence-bundle"' in source
    assert '$FirstRunRecoveryAnchors = @("runner-readiness", "sample-data", "run-report", "result-package", "validation-card", "evidence-bundle")' in source
    assert "blocked finalization must include nextAction code and target" in source
    assert "blocked finalization nextAction target must match $($Action.code)" in source
    assert "blocked finalization nextAction target must use a first-run recovery anchor" in source
    assert "blocked finalization nextAction target must stay inside first-run" in source
    assert "$blockedActionProof = Assert-FirstRunBlockedNextAction $finalization.nextAction" in source
    assert "blockedActionProof = $blockedActionProof" in source
    assert "executionReadinessProof = $executionReadinessProof" in source
    assert "sampleUploadProof = $sampleUploadProof" in source
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
    assert "executionReadinessProof.ok: true" in source
    assert 'sampleUploadProof.schemaVersion: "h2ometa.first-run.sample-upload-proof.v1"' in source
    assert "sampleUploadProof.passed: true" in source
    assert "sampleUploadProof.unexpectedRoles: []" in source
    assert "sampleUploadProof.duplicateRoles: []" in source
    assert "ready first-run evidence bundle" in source
