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
    assert "/api/v1/first-run/runs/$([uri]::EscapeDataString($RunId))/finalize" in source
    assert "h2ometa.first-run.finalization.v1" in source
    assert "ready finalization must include validationCard and resultPackage" in source
    assert "ready finalization must include a single-user-lab pilotHandoff" in source
    assert "blocked finalization must include nextAction code and target" in source
    assert "-RequireFinalizationReady requires -RunId from a completed Moving Pictures first run" in source
    assert 'SmokeOnly = "catalog-page-smoke"' in source
    assert 'FinalizedRun = "finalized-run"' in source
    assert "$closedLoopProven = $false" in source
    assert "$closedLoopProven = $true" in source
    assert "closedLoopProven = $closedLoopProven" in source
    assert "closedLoopProofMode = $closedLoopProofMode" in source
    assert "h2ometa.first-run-pilot-check.v1" in source
