from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "single_user_pilot_backup_plan.ps1"
DOC = REPO_ROOT / "docs" / "release-candidate-operating-loop.md"
RUNBOOK = REPO_ROOT / "docs" / "single-user-pilot-backup-restore.md"


def test_single_user_pilot_backup_plan_script_defines_read_only_handoff() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "h2ometa.single-user-pilot-backup-plan.v1" in source
    assert "mode = \"read-only-plan\"" in source
    assert "readyForManualBackup" in source
    assert "[switch]$RequireExistingState" in source
    assert "REMOTE_RUNNER_ROOT_NOT_SUPPLIED" in source
    assert "NO_EXISTING_LOCAL_APP_STATE" in source
    assert "manual-stopped-runner-or-runner-online-backup" in source
    assert "hotCopyUnsupported = $true" in source
    assert "runner.db-wal" in source
    assert "data/runner.db" in source
    assert "uploads/" in source
    assert "results/" in source
    assert "config/snakemake/default/" in source
    assert "tool-packs/registry-v1.json" in source
    assert "external reference database paths registered in runner.db" in source
    assert "runtime/runner-state.json" in source
    assert "releases/" in source
    assert "conda-envs/" in source
    assert "OS keyring SSH passwords and runner tokens" in source
    assert "SSH private keys referenced by identity_ref" in source
    assert "H2OMETA_DEV_CACHE_ROOT" in source
    assert ".venv-win, .uv-cache-local, .next, out, node_modules" in source
    assert "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady" in source
    assert "closedLoopProven=true" in source
    assert "closedLoopProofMode=submitted-run" in source
    assert "executionReadinessProof.ok=true" in source
    assert "sampleUploadProof.schemaVersion=h2ometa.first-run.sample-upload-proof.v1" in source
    assert "sampleUploadProof.passed=true" in source
    assert "sampleUploadProof.unexpectedRoles=[]" in source
    assert "sampleUploadProof.duplicateRoles=[]" in source
    assert "sampleUploadProof covers metadata, barcodes, and sequences" in source
    assert "handoffProof.evidenceBundleSchemaVersion=h2ometa.first-run.evidence-bundle.v1" in source
    assert "handoffProof.evidenceBundleFileRoles=$($expectedEvidenceBundleRoles -join ',')" in source
    assert "handoffProof.nextScenarioIds=$($expectedNextScenarioIds -join ',')" in source
    assert "handoffProof.nextScenarioDatabasePackCoverage.toolSliceRequiredState=WorkflowReady" in source
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.toolSlicePromotionEvidence="
        "toolRevisionId,capability-bundle-v1,RuleSpec,environment-lock,smoke-fixture,expected-output-artifacts"
    ) in source
    assert "handoffProof.nextScenarioDatabasePackCoverage.toolAcceptanceContractCount>=3" in source
    assert "handoffProof.nextScenarioDatabasePackCoverage.taxonomy-classification.packCount=1" in source
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.amr-annotation.missingTemplates="
        "card_rgi,eggnog_mapper,interproscan"
    ) in source
    assert "handoffProof.nextScenarioDatabasePackCoverage.readyScanPath=/api/v1/database-pack-ready-scans" in source
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.registrationPrefillSource="
        "database-pack-ready-scan.registrationPrefill"
    ) in source
    assert "requiredHandoffProof" in source
    assert "manual-audited-database-and-sample-gates" in source
    assert "SINGLE_USER_PILOT_BACKUP_PLAN_FAILED" in source
    assert "Compress-Archive" not in source
    assert "Invoke-RestMethod" not in source
    assert "Invoke-Command" not in source


def _powershell_executable() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


@pytest.mark.skipif(_powershell_executable() is None, reason="PowerShell is required to execute the pilot backup plan script")
def test_single_user_pilot_backup_plan_outputs_machine_readable_json(tmp_path: Path) -> None:
    appdata_root = tmp_path / "Roaming" / "H2OMeta"
    localappdata_root = tmp_path / "Local" / "H2OMeta"
    dev_cache_root = tmp_path / "dev-cache"
    appdata_root.mkdir(parents=True)
    localappdata_root.mkdir(parents=True)

    completed = subprocess.run(
        [
            _powershell_executable() or "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-AppDataRoot",
            str(appdata_root),
            "-LocalAppDataRoot",
            str(localappdata_root),
            "-DevCacheRoot",
            str(dev_cache_root),
            "-RemoteRunnerSharedRoot",
            "/home/lab/.h2ometa/runner/shared",
            "-RequireExistingState",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)

    assert summary["schemaVersion"] == "h2ometa.single-user-pilot-backup-plan.v1"
    assert summary["mode"] == "read-only-plan"
    assert summary["readyForManualBackup"] is True
    assert summary["blockers"] == []
    assert summary["localArchiveItems"] == ["config.json", "ssh/known_hosts", "tool-packs/registry-v1.json"]
    assert "data/runner.db" in summary["remoteState"]["include"]
    assert "runner.db-wal" in summary["archivePolicy"]["sqliteCopyRule"]
    assert "external reference database paths registered in runner.db" in summary["remoteSeparateOperatorItems"]
    assert "runtime/runner-state.json" in summary["remoteExcludedItems"]
    assert summary["restoreDrill"]["firstRunProofCommand"] == (
        "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady"
    )
    assert "executionReadinessProof.ok=true" in summary["restoreDrill"]["mustReport"]
    assert "sampleUploadProof.schemaVersion=h2ometa.first-run.sample-upload-proof.v1" in summary["restoreDrill"]["mustReport"]
    assert "sampleUploadProof.passed=true" in summary["restoreDrill"]["mustReport"]
    assert "sampleUploadProof.unexpectedRoles=[]" in summary["restoreDrill"]["mustReport"]
    assert "sampleUploadProof.duplicateRoles=[]" in summary["restoreDrill"]["mustReport"]
    assert "sampleUploadProof covers metadata, barcodes, and sequences" in summary["restoreDrill"]["mustReport"]
    assert (
        "handoffProof.evidenceBundleSchemaVersion=h2ometa.first-run.evidence-bundle.v1"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.evidenceBundleFileRoles=result-package,validation-card-json,validation-card-markdown,pilot-handoff"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.backupPlanCommand="
        'scripts\\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "<remote-shared-root>" -RequireExistingState'
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.restoreProofCommand=scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady"
        in summary["restoreDrill"]["mustReport"]
    )
    assert "handoffProof.nextScenarioIds=taxonomy-classification,amr-annotation" in summary["restoreDrill"]["mustReport"]
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.toolSliceRequiredState=WorkflowReady"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.toolSlicePromotionEvidence="
        "toolRevisionId,capability-bundle-v1,RuleSpec,environment-lock,smoke-fixture,expected-output-artifacts"
        in summary["restoreDrill"]["mustReport"]
    )
    assert "handoffProof.nextScenarioDatabasePackCoverage.toolAcceptanceContractCount>=3" in summary["restoreDrill"]["mustReport"]
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.taxonomy-classification.packCount=1"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.amr-annotation.missingTemplates="
        "card_rgi,eggnog_mapper,interproscan"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.readyScanPath=/api/v1/database-pack-ready-scans"
        in summary["restoreDrill"]["mustReport"]
    )
    assert (
        "handoffProof.nextScenarioDatabasePackCoverage.registrationPrefillSource="
        "database-pack-ready-scan.registrationPrefill"
        in summary["restoreDrill"]["mustReport"]
    )
    required_handoff = summary["restoreDrill"]["requiredHandoffProof"]
    assert required_handoff["evidenceBundleSchemaVersion"] == "h2ometa.first-run.evidence-bundle.v1"
    assert required_handoff["evidenceBundleFileRoles"] == [
        "result-package",
        "validation-card-json",
        "validation-card-markdown",
        "pilot-handoff",
    ]
    assert required_handoff["backupPlanCommand"] == (
        'scripts\\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "<remote-shared-root>" -RequireExistingState'
    )
    assert required_handoff["restoreProofCommand"] == (
        "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady"
    )
    assert required_handoff["nextScenarioIds"] == ["taxonomy-classification", "amr-annotation"]
    assert required_handoff["nextScenarioDatabasePackCoverage"] == [
        {
            "scenarioId": "taxonomy-classification",
            "status": "blocked",
            "packCount": 1,
            "missingTemplates": [],
            "toolSliceRequiredState": "WorkflowReady",
            "toolSlicePromotionEvidence": [
                "toolRevisionId",
                "capability-bundle-v1",
                "RuleSpec",
                "environment-lock",
                "smoke-fixture",
                "expected-output-artifacts",
            ],
            "toolAcceptanceContractCount": 3,
            "readyScanPath": "/api/v1/database-pack-ready-scans",
            "registrationPrefillSource": "database-pack-ready-scan.registrationPrefill",
        },
        {
            "scenarioId": "amr-annotation",
            "status": "blocked",
            "packCount": 0,
            "missingTemplates": ["card_rgi", "eggnog_mapper", "interproscan"],
            "toolSliceRequiredState": "WorkflowReady",
            "toolSlicePromotionEvidence": [
                "toolRevisionId",
                "capability-bundle-v1",
                "RuleSpec",
                "environment-lock",
                "smoke-fixture",
                "expected-output-artifacts",
            ],
            "toolAcceptanceContractCount": 3,
            "readyScanPath": "/api/v1/database-pack-ready-scans",
            "registrationPrefillSource": "database-pack-ready-scan.registrationPrefill",
        },
    ]
    assert required_handoff["operatorGateMode"] == "manual-audited-database-and-sample-gates"


def test_single_user_pilot_backup_plan_is_exposed_from_web_package() -> None:
    package = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["smoke:pilot-backup-plan"] == (
        "powershell -ExecutionPolicy Bypass -File ../../scripts/single_user_pilot_backup_plan.ps1"
    )


def test_single_user_pilot_backup_docs_connect_restore_to_first_run_proof() -> None:
    source = DOC.read_text(encoding="utf-8") + "\n" + RUNBOOK.read_text(encoding="utf-8")
    readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    remote_strategy = (REPO_ROOT / "docs" / "remote-agent-deployment-strategy.md").read_text(encoding="utf-8")

    assert "Single-User Pilot Backup And Restore" in source
    assert "scripts\\single_user_pilot_backup_plan.ps1" in source
    assert "h2ometa.single-user-pilot-backup-plan.v1" in source
    assert "single-user-pilot-backup-restore.md" in source
    assert "single-user-pilot-backup-restore.md" in readme
    assert "single-user-pilot-backup-restore.md" in remote_strategy
    assert "%APPDATA%\\H2OMeta" in source
    assert "/home/<user>/.h2ometa/runner/shared" in source
    assert "data/runner.db" in source
    assert "config/snakemake/default" in source
    assert "tool-pack registry state" in source
    assert "External reference database paths registered in the runner database" in source
    assert "trusted `known_hosts`" in source
    assert "raw passwords, bearer tokens, SSH private keys" in source
    assert "runner.db-wal" in source
    assert "Store SHA-256 evidence for every archive." in source
    assert "isolated Windows profile" in source
    assert "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady" in source
    assert 'closedLoopProven: true' in source
    assert 'closedLoopProofMode: "submitted-run"' in source
    assert "executionReadinessProof.ok: true" in source
    assert 'sampleUploadProof.schemaVersion: "h2ometa.first-run.sample-upload-proof.v1"' in source
    assert "sampleUploadProof.passed: true" in source
    assert "sampleUploadProof.unexpectedRoles: []" in source
    assert "sampleUploadProof.duplicateRoles: []" in source
    assert "handoffProof.evidenceBundleSchemaVersion" in source
    assert "handoffProof.evidenceBundleFileRoles" in source
    assert "handoffProof.nextScenarioDatabasePackCoverage" in source
