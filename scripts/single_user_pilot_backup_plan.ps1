param(
    [string]$AppDataRoot = "",
    [string]$LocalAppDataRoot = "",
    [string]$DevCacheRoot = "",
    [string]$RemoteRunnerSharedRoot = "",
    [switch]$RequireExistingState
)

$ErrorActionPreference = "Stop"

function Resolve-LocalPathText {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }
    return [System.IO.Path]::GetFullPath($PathText)
}

function Get-DefaultAppDataRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:APPDATA)) {
        return (Join-Path $env:APPDATA "H2OMeta")
    }
    $profileRoot = [Environment]::GetFolderPath("ApplicationData")
    if (-not [string]::IsNullOrWhiteSpace($profileRoot)) {
        return (Join-Path $profileRoot "H2OMeta")
    }
    return ""
}

function Get-DefaultLocalAppDataRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return (Join-Path $env:LOCALAPPDATA "H2OMeta")
    }
    $profileRoot = [Environment]::GetFolderPath("LocalApplicationData")
    if (-not [string]::IsNullOrWhiteSpace($profileRoot)) {
        return (Join-Path $profileRoot "H2OMeta")
    }
    return ""
}

function Get-DefaultDevCacheRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:H2OMETA_DEV_CACHE_ROOT)) {
        return $env:H2OMETA_DEV_CACHE_ROOT
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        return (Join-Path $env:LOCALAPPDATA "H2OMeta\dev-cache")
    }
    return ""
}

function Join-LocalPathText {
    param(
        [string]$BasePath,
        [string]$ChildPath
    )
    if ([string]::IsNullOrWhiteSpace($BasePath)) {
        return ""
    }
    return (Join-Path $BasePath $ChildPath)
}

function New-LocalStateItem {
    param(
        [string]$Label,
        [string]$PathText,
        [bool]$IncludeInBackup,
        [bool]$RequiredForPilot,
        [string]$Reason
    )
    $resolved = Resolve-LocalPathText $PathText
    $exists = $false
    if (-not [string]::IsNullOrWhiteSpace($resolved)) {
        $exists = Test-Path -LiteralPath $resolved
    }
    return [ordered]@{
        label = $Label
        path = $resolved
        exists = $exists
        includeInBackup = $IncludeInBackup
        requiredForPilot = $RequiredForPilot
        reason = $Reason
    }
}

function Add-Blocker {
    param(
        [System.Collections.Generic.List[object]]$Blockers,
        [string]$Code,
        [string]$Message
    )
    $Blockers.Add([ordered]@{ code = $Code; message = $Message }) | Out-Null
}

if ([string]::IsNullOrWhiteSpace($AppDataRoot)) {
    $AppDataRoot = Get-DefaultAppDataRoot
}
if ([string]::IsNullOrWhiteSpace($LocalAppDataRoot)) {
    $LocalAppDataRoot = Get-DefaultLocalAppDataRoot
}
if ([string]::IsNullOrWhiteSpace($DevCacheRoot)) {
    $DevCacheRoot = Get-DefaultDevCacheRoot
}

$localState = @(
    (New-LocalStateItem "local-control-plane-state" $AppDataRoot $true $true "Stores config.json, trusted known_hosts, server registry metadata, and non-secret references needed to reconnect the local app."),
    (New-LocalStateItem "local-app-cache" (Join-LocalPathText $LocalAppDataRoot "Cache") $false $false "Rebuildable web/API indexes and downloaded metadata; exclude from the pilot archive."),
    (New-LocalStateItem "local-dev-cache" $DevCacheRoot $false $false "Rebuildable launcher/runtime artifact cache; exclude from the pilot archive.")
)

$remoteRootSupplied = -not [string]::IsNullOrWhiteSpace($RemoteRunnerSharedRoot)
$remoteRoot = if ($remoteRootSupplied) { $RemoteRunnerSharedRoot } else { "~/.h2ometa/runner/shared" }
$remoteState = [ordered]@{
    operatorSuppliedRoot = $remoteRootSupplied
    sharedRoot = $remoteRoot
    copyMode = "manual-stopped-runner-or-runner-online-backup"
    include = @(
        "data/runner.db",
        "uploads/",
        "results/",
        "work/",
        "logs/",
        "config/snakemake/default/"
    )
    secretRebind = @(
        "config/runner.json token and artifact secret fields are not ordinary archive evidence",
        "OS keyring SSH passwords and runner tokens must be re-entered or migrated through an operator-approved secret process",
        "SSH private keys referenced by identity_ref stay under the operator's SSH policy and are not collected by this plan"
    )
}

$blockers = New-Object System.Collections.Generic.List[object]
$localControlPlane = $localState | Where-Object { $_.label -eq "local-control-plane-state" } | Select-Object -First 1
if ($RequireExistingState.IsPresent -and -not $localControlPlane.exists) {
    Add-Blocker $blockers "NO_EXISTING_LOCAL_APP_STATE" "No local H2OMeta APPDATA state exists for the pilot profile."
}
if (-not $remoteRootSupplied) {
    Add-Blocker $blockers "REMOTE_RUNNER_ROOT_NOT_SUPPLIED" "Pass -RemoteRunnerSharedRoot after runner readiness so the remote state root is explicit."
}

$expectedEvidenceBundleRoles = @("result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff")
$expectedNextScenarioIds = @("taxonomy-classification", "amr-annotation")
$expectedBackupPlanCommand = 'scripts\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "<remote-shared-root>" -RequireExistingState'
$expectedRestoreProofCommand = "scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady"

$plan = [ordered]@{
    schemaVersion = "h2ometa.single-user-pilot-backup-plan.v1"
    generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    scope = "single-user-lab"
    mode = "read-only-plan"
    readyForManualBackup = ($blockers.Count -eq 0)
    blockers = @($blockers.ToArray())
    localState = $localState
    localArchiveItems = @(
        "config.json",
        "ssh/known_hosts",
        "tool-packs/registry-v1.json"
    )
    remoteState = $remoteState
    remoteSecretManagedItems = @(
        "config/runner.json token field",
        "config/runner.json artifact S3 secret fields when configured"
    )
    remoteSeparateOperatorItems = @(
        "external reference database paths registered in runner.db",
        "operator-managed SSH identities referenced by local identity_ref",
        "OS keyring entries referenced by local password_ref and runner token_ref"
    )
    remoteExcludedItems = @(
        "runtime/runner-state.json",
        "locks/",
        "releases/",
        "current",
        "tools/",
        "conda-envs/",
        "temporary runner process files"
    )
    archivePolicy = [ordered]@{
        stopBeforeCopy = $true
        hotCopyUnsupported = $true
        sqliteCopyRule = "Use a stopped-runner copy that includes runner.db, runner.db-wal, and runner.db-shm when present, or use a runner-provided SQLite online backup export."
        checksumAlgorithm = "SHA256"
        archiveEvidence = @(
            "archive name",
            "source commit",
            "operator",
            "createdAt",
            "SHA256",
            "included roots",
            "excluded categories",
            "restore drill result"
        )
        excludedCategories = @(
            "raw passwords, bearer tokens, private keys, and secret environment variables",
            "H2OMETA_DEV_CACHE_ROOT",
            "APPDATA-independent browser caches and npm/Playwright caches",
            ".venv-win, .uv-cache-local, .next, out, node_modules, and build outputs",
            "GitHub CLI auth material under LOCALAPPDATA unless separately approved by the operator"
        )
    }
    restoreDrill = [ordered]@{
        required = $true
        isolatedWindowsProfile = $true
        dedicatedRemoteRunnerRoot = $true
        firstRunProofCommand = $expectedRestoreProofCommand
        mustReport = @(
            "closedLoopProven=true",
            "closedLoopProofMode=submitted-run",
            "executionReadinessProof.ok=true",
            "sampleUploadProof.schemaVersion=h2ometa.first-run.sample-upload-proof.v1",
            "sampleUploadProof.passed=true",
            "sampleUploadProof.unexpectedRoles=[]",
            "sampleUploadProof.duplicateRoles=[]",
            "validationCard ready",
            "resultPackage SHA256 present",
            "sampleUploadProof covers metadata, barcodes, and sequences",
            "handoffProof.evidenceBundleSchemaVersion=h2ometa.first-run.evidence-bundle.v1",
            "handoffProof.evidenceBundleFileRoles=$($expectedEvidenceBundleRoles -join ',')",
            "handoffProof.backupPlanCommand=$expectedBackupPlanCommand",
            "handoffProof.restoreProofCommand=$expectedRestoreProofCommand",
            "handoffProof.nextScenarioIds=$($expectedNextScenarioIds -join ',')",
            "handoffProof.nextScenarioDatabasePackCoverage.taxonomy-classification.packCount=1",
            "handoffProof.nextScenarioDatabasePackCoverage.amr-annotation.missingTemplates=card_rgi,eggnog_mapper,interproscan",
            "handoffProof.nextScenarioDatabasePackCoverage.readyScanPath=/api/v1/database-pack-ready-scans",
            "handoffProof.nextScenarioDatabasePackCoverage.registrationPrefillSource=database-pack-ready-scan.registrationPrefill"
        )
        requiredHandoffProof = [ordered]@{
            evidenceBundleSchemaVersion = "h2ometa.first-run.evidence-bundle.v1"
            evidenceBundleFileRoles = $expectedEvidenceBundleRoles
            backupPlanCommand = $expectedBackupPlanCommand
            restoreProofCommand = $expectedRestoreProofCommand
            nextScenarioIds = $expectedNextScenarioIds
            nextScenarioDatabasePackCoverage = @(
                [ordered]@{
                    scenarioId = "taxonomy-classification"
                    status = "blocked"
                    packCount = 1
                    missingTemplates = @()
                    readyScanPath = "/api/v1/database-pack-ready-scans"
                    registrationPrefillSource = "database-pack-ready-scan.registrationPrefill"
                },
                [ordered]@{
                    scenarioId = "amr-annotation"
                    status = "blocked"
                    packCount = 0
                    missingTemplates = @("card_rgi", "eggnog_mapper", "interproscan")
                    readyScanPath = "/api/v1/database-pack-ready-scans"
                    registrationPrefillSource = "database-pack-ready-scan.registrationPrefill"
                }
            )
            operatorGateMode = "manual-audited-database-and-sample-gates"
        }
    }
    unsupportedOperations = @(
        "Copying runner.db while the remote runner is still writing to it",
        "Treating cache directories as durable backup state",
        "Bundling OS keyring contents or SSH private keys into the ordinary result archive",
        "Claiming restore success before the full First Successful Run proof passes"
    )
}

if ($RequireExistingState.IsPresent -and $blockers.Count -gt 0) {
    $plan | ConvertTo-Json -Depth 8
    throw "SINGLE_USER_PILOT_BACKUP_PLAN_FAILED: existing pilot state requirements were not met"
}

$plan | ConvertTo-Json -Depth 8
