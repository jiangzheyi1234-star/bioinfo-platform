from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "release-candidate-operating-loop.md"
SCRIPT = ROOT / "scripts" / "verify_release_candidate.ps1"
PLATFORM_EVIDENCE_HELPER = ROOT / "scripts" / "rc_platform_evidence.ps1"
FIRST_RUN_PILOT_HELPER = ROOT / "scripts" / "rc_first_run_pilot_proof.ps1"
PILOT_BACKUP_HELPER = ROOT / "scripts" / "rc_single_user_pilot_backup_plan.ps1"


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_candidate_operating_loop_doc_defines_handoff_contract() -> None:
    source = DOC.read_text(encoding="utf-8")
    readme = _source("docs/README.md")
    roadmap = _source("docs/roadmaps/maturity-hardening.md")

    for token in (
        "h2ometa-release-candidate-evidence.v1",
        "No RC evidence, no production handoff",
        "release-evidence/<commit>/",
        "release-candidate-summary.json",
        "release-candidate-summary.md",
        "handoffEligible: false",
        "required / ci-green",
        "-CiRunUrl",
        "-SecurityAnalysisRunUrl",
        "-SecurityAnalysisUnavailableReason",
        "-ContainerImageScanRunUrl",
        "-ContainerImageScanUnavailableReason",
        "Security Analysis evidence mode",
        "Container Image Scan evidence mode",
        "-RunNpmCi",
        "-DevelopmentOnly",
        "scripts/verify_release_candidate.ps1",
        "run.bat --web",
        "-StartLocalWeb",
        "-UseUserAppStateForLocalWeb",
        "run.bat --desktop",
        "-DesktopStartupEvidence",
        "scripts/local_web_smoke.ps1",
        "-RunWebE2E",
        "-WebE2ERepeat",
        "-RunFirstRunPilotProof",
        "-FirstRunPilotRunId",
        "first-run pilot proof path",
        "single-user backup plan path",
        "first-run-pilot-proof.json",
        "single-user-pilot-backup-plan.json",
        "scripts/first_run_pilot_check.ps1",
        "scripts\\single_user_pilot_backup_plan.ps1",
        "firstRunPilotProof.closedLoopProven: true",
        "firstRunPilotProof.runTimingProof.withinExpectedDurationWindow: true",
        "-RunSingleUserPilotBackupPlan",
        "-SingleUserPilotRemoteRunnerSharedRoot",
        "singleUserPilotBackupPlan.readyForManualBackup: true",
        "singleUserPilotBackupPlan.firstRunProof.accepted: true",
        "singleUserPilotBackupPlan.firstRunProof.summary.runTimingProof.withinExpectedDurationWindow: true",
        "fresh `submitted-run` proof from `-RunFirstRunPilotProof`",
        "fails closed when the pilot proof is reused through `-FirstRunPilotRunId`",
        "Skipping the First Successful Run pilot proof or the single-user pilot backup plan blocks `localSingleUserProofEligible`",
        "localSingleUserProofEligible",
        "scripts/check_remote_runner_release_readiness.py",
        "database-pack-lifecycle-v1",
        "Runtime manifest drift gate",
        "runtimeManifestDrift.hasDrift",
    ):
        assert token in source

    assert "release-candidate-operating-loop.md" in readme
    assert "P0-11 Release Candidate Operating Loop Criteria" in roadmap
    assert "-RunFirstRunPilotProof" in roadmap
    assert "first-run-pilot-proof.json" in roadmap


def test_release_candidate_script_collects_required_evidence_gates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    helper_source = PLATFORM_EVIDENCE_HELPER.read_text(encoding="utf-8")
    first_run_helper_source = FIRST_RUN_PILOT_HELPER.read_text(encoding="utf-8")
    pilot_backup_helper_source = PILOT_BACKUP_HELPER.read_text(encoding="utf-8")
    combined_source = source + "\n" + helper_source + "\n" + first_run_helper_source + "\n" + pilot_backup_helper_source

    for token in (
        "h2ometa-release-candidate-evidence.v1",
        "release-candidate-summary.json",
        "release-candidate-summary.md",
        "git -C $repoRoot status --porcelain=v1",
        "working tree is dirty",
        "[switch]$DevelopmentOnly",
        "H2OMETA_DEV_CACHE_ROOT",
        "UseUserAppStateForLocalWeb",
        "devCacheRoot",
        "ci-proof",
        "production handoff requires -CiRunUrl",
        "requiredCheck=required / ci-green",
        "[string]$SecurityAnalysisRunUrl",
        "[string]$SecurityAnalysisUnavailableReason",
        "[string]$ContainerImageScanRunUrl",
        "[string]$ContainerImageScanUnavailableReason",
        "rc_platform_evidence.ps1",
        "Invoke-PlatformWorkflowEvidence",
        "security-analysis-platform-evidence",
        "container-image-scan-platform-evidence",
        "$RunUrlParameterName and $UnavailableReasonParameterName are mutually exclusive",
        "$RunUrlParameterName must point to a GitHub Actions run URL",
        "ContainerImageScanRunUrl",
        "Container Image Scan",
        'Write-Host "workflow=$WorkflowName"',
        '-WorkflowName "Security Analysis"',
        "securityAnalysisEvidenceRecorded",
        "securityAnalysisEvidenceMode",
        "containerImageScanEvidenceRecorded",
        "containerImageScanEvidenceMode",
        '$result["mode"] = "green"',
        "production handoff requires -$RunUrlParameterName or -$UnavailableReasonParameterName",
        "-and $securityAnalysisEvidence.recorded -and $containerImageScanEvidence.recorded",
        'Invoke-Native "uv" @("run", "--frozen", "ruff", "check", "apps", "core", "scripts", "tests")',
        'Invoke-Native "uv" @("run", "--frozen", "python", "-m", "pytest", "-q")',
        "clean-install-proof",
        'Invoke-Native "npm" @("ci")',
        "production handoff requires -RunNpmCi",
        'Invoke-Native "npm" @("run", "lint")',
        'Invoke-Native "npm" @("run", "typecheck")',
        'Invoke-Native "npm" @("run", "build")',
        "scripts\\security_governance_audit.py",
        'Invoke-Native "uv" @("run", "--frozen", "python", "scripts\\security_governance_audit.py")',
        "Invoke-NativeWithRetry",
        "apps\\desktop",
        "--audit-level=moderate",
        'Invoke-NativeWithRetry "uvx" @("pip-audit"',
        "CVE-2026-44405",
        "tests/test_reference_database_pack_lifecycle_docs.py",
        "tests/test_reference_database_pack_catalog.py",
        "tests/test_reference_database_registry_templates.py",
        "tests/test_tool_contract_production_evidence.py",
        "Get-RuntimeManifestDrift",
        "runtime-manifest-drift",
        "release-scoped sources changed after the runtime manifest source commit",
        "config/remote-runner-release-manifest.json",
        "runtimeManifestDrift = $runtimeManifestDrift",
        "rc_first_run_pilot_proof.ps1",
        "rc_single_user_pilot_backup_plan.ps1",
        '$firstRunPilotProofPath = Join-Path $evidenceDir "first-run-pilot-proof.json"',
        "$firstRunPilotProof = [ordered]@{",
        '$singleUserPilotBackupPlanPath = Join-Path $evidenceDir "single-user-pilot-backup-plan.json"',
        "$singleUserPilotBackupPlan = [ordered]@{",
        "-RunFirstRunPilotProof and -FirstRunPilotRunId are mutually exclusive",
        "runFirstRunPilotProof = $RunFirstRunPilotProof.IsPresent",
        "firstRunPilotProofPath = $firstRunPilotProofPath",
        "firstRunPilotProof = $firstRunPilotProof",
        "runSingleUserPilotBackupPlan = $RunSingleUserPilotBackupPlan.IsPresent",
        "singleUserPilotBackupPlanPath = $singleUserPilotBackupPlanPath",
        "singleUserPilotBackupPlan = $singleUserPilotBackupPlan",
        "$firstRunPilotProof.closedLoopProven -eq $true",
        "Test-FirstRunTimingProof",
        "firstRunPilotTimingProofAccepted",
        "h2ometa.first-run.timing-proof.v1",
        "$firstRunPilotTimingProofAccepted",
        "$singleUserPilotBackupPlan.readyForManualBackup -eq $true",
        "h2ometa.first-run-pilot-check.v1",
        "h2ometa.single-user-pilot-backup-plan.v1",
        "single-user-pilot-backup-plan",
        "single_user_pilot_backup_plan.ps1",
        "-FirstRunProofPath",
        "single-user pilot backup plan requires -SingleUserPilotRemoteRunnerSharedRoot",
        "single-user pilot backup plan did not accept first-run proof",
        "-RunSingleUserPilotBackupPlan requires a fresh -RunFirstRunPilotProof submitted-run proof",
        "-RunSingleUserPilotBackupPlan requires -RunFirstRunPilotProof",
        "-RequireFinalizationReady",
        "-RunFirstSuccessfulRun",
        "validationCardJsonSha256",
        "localSingleUserProofEligible",
        "handoffEligible",
        '($($step.durationSeconds)s)',
    ):
        assert token in combined_source


def test_release_candidate_script_keeps_optional_gates_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    helper_source = PLATFORM_EVIDENCE_HELPER.read_text(encoding="utf-8")
    local_web_helper_source = (ROOT / "scripts" / "rc_local_web_stack.ps1").read_text(encoding="utf-8")
    combined_source = source + "\n" + local_web_helper_source

    assert "[switch]$RunLocalWebSmoke" in source
    assert "[switch]$StartLocalWeb" in source
    assert "[switch]$UseUserAppStateForLocalWeb" in source
    assert "Invoke-WithLocalWebAppState" in source
    assert "rc_local_web_stack.ps1" in source
    assert "H2OMETA_HEADLESS_LAUNCH" in combined_source
    assert "local-web-launcher" in source
    assert "pass -StartLocalWeb to launch run.bat --web headlessly" in source
    assert "Start-Process" in combined_source
    assert "run.bat --web did not exit within 120 seconds" in combined_source
    assert "Wait-LocalWebStack" in combined_source
    assert "/api/v1/service-info" in combined_source
    assert "apiReadinessStatus" in combined_source
    assert "Save-LocalWebStackLogs" in combined_source
    assert ".h2ometa-api.out.log" in combined_source
    assert "local-web-stack-" in combined_source
    assert "pass -RunLocalWebSmoke after starting run.bat --web" in source
    assert "scripts\\local_web_smoke.ps1" in source
    assert "[switch]$RunWebE2E" in source
    assert "[ValidateRange(1, 10)]" in source
    assert "[int]$WebE2ERepeat = 1" in source
    assert "web-e2e" in source
    assert 'Invoke-Native "npm" @("run", "test:e2e")' in source
    assert "E2E_API_BASE" in source
    assert "pass -RunWebE2E to execute Playwright" in source
    assert "[switch]$RunFirstRunPilotProof" in source
    assert "[switch]$RunSingleUserPilotBackupPlan" in source
    assert '[string]$FirstRunPilotRunId = ""' in source
    assert '[string]$SingleUserPilotRemoteRunnerSharedRoot = ""' in source
    assert "first-run-pilot-proof" in source
    assert "-ProofPath" in source
    assert "pass -RunFirstRunPilotProof to prove the full Moving Pictures first successful run" in source
    assert "single-user-pilot-backup-plan" in source
    assert "pass -RunSingleUserPilotBackupPlan with -SingleUserPilotRemoteRunnerSharedRoot" in source
    assert "[string]$DesktopStartupEvidence" in source
    assert "desktop-startup-evidence" in source
    assert "pass -DesktopStartupEvidence after starting run.bat --desktop" in source
    assert "[string]$ReleaseGateEvidence" in source
    assert 'Add-StepResult -Steps $Steps -Name $Name -Status "unavailable"' in helper_source
    assert "[switch]$RequireReleaseGateEvidence" in source
    assert "$runtimeGateRequired = $runtimeGateRequested" in source
    assert "$RequireRuntimeManifestArtifacts.IsPresent" in source
    assert "$RequireRuntimeSupplyChain.IsPresent" in source
    assert "[bool]$ReleaseTag" in source
    assert "$runtimeGateRequested = (" in source
    assert "$runtimeManifestArtifactsRequired = $true" in source
    assert "$runtimeSupplyChainRequired = $true" in source
    assert "Required $runtimeGateRequired" in source
    assert "pass -ReleaseGateEvidence for runtime artifact production readiness" in source
    assert "scripts\\check_remote_runner_release_readiness.py" in source
    assert "--release-gate-evidence" in source
    assert "--require-manifest-artifacts" in source
    assert "--require-supply-chain" in source
    assert '"failed" } else { "skipped" }' in source


def test_release_candidate_evidence_is_local_only() -> None:
    gitignore = _source(".gitignore")

    assert "release-evidence/" in gitignore
