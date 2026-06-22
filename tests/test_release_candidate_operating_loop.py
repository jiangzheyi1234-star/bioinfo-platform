from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "release-candidate-operating-loop.md"
SCRIPT = ROOT / "scripts" / "verify_release_candidate.ps1"


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
        "localSingleUserProofEligible",
        "scripts/check_remote_runner_release_readiness.py",
        "database-pack-lifecycle-v1",
        "Runtime manifest drift gate",
        "runtimeManifestDrift.hasDrift",
    ):
        assert token in source

    assert "release-candidate-operating-loop.md" in readme
    assert "P0-11 Release Candidate Operating Loop Criteria" in roadmap


def test_release_candidate_script_collects_required_evidence_gates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

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
        "localSingleUserProofEligible",
        "handoffEligible",
    ):
        assert token in source


def test_release_candidate_script_keeps_optional_gates_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$RunLocalWebSmoke" in source
    assert "[switch]$StartLocalWeb" in source
    assert "[switch]$UseUserAppStateForLocalWeb" in source
    assert "Invoke-WithLocalWebAppState" in source
    assert "H2OMETA_HEADLESS_LAUNCH" in source
    assert "local-web-launcher" in source
    assert "pass -StartLocalWeb to launch run.bat --web headlessly" in source
    assert "Start-Process" in source
    assert "run.bat --web did not exit within 120 seconds" in source
    assert "Wait-LocalWebStack" in source
    assert "/api/v1/service-info" in source
    assert "apiReadinessStatus" in source
    assert "Save-LocalWebStackLogs" in source
    assert ".h2ometa-api.out.log" in source
    assert "local-web-stack-" in source
    assert "pass -RunLocalWebSmoke after starting run.bat --web" in source
    assert "scripts\\local_web_smoke.ps1" in source
    assert "[switch]$RunWebE2E" in source
    assert "[ValidateRange(1, 10)]" in source
    assert "[int]$WebE2ERepeat = 1" in source
    assert "web-e2e" in source
    assert 'Invoke-Native "npm" @("run", "test:e2e")' in source
    assert "E2E_API_BASE" in source
    assert "pass -RunWebE2E to execute Playwright" in source
    assert "[string]$DesktopStartupEvidence" in source
    assert "desktop-startup-evidence" in source
    assert "pass -DesktopStartupEvidence after starting run.bat --desktop" in source
    assert "[string]$ReleaseGateEvidence" in source
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
