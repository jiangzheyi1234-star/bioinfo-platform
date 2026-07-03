param(
    [string]$AppDataRoot = "",
    [string]$LocalAppDataRoot = "",
    [string]$DevCacheRoot = "",
    [string]$RemoteRunnerSharedRoot = "",
    [string]$FirstRunProofPath = "",
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

function Add-ProofError {
    param(
        [System.Collections.Generic.List[object]]$Errors,
        [string]$Code,
        [string]$Message
    )
    $Errors.Add([ordered]@{ code = $Code; message = $Message }) | Out-Null
}

function Get-StringArray {
    param([object]$Value)
    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { if ($null -ne $_) { [string]$_ } })
}

function Test-SameStringSet {
    param([string[]]$Actual, [string[]]$Expected)
    $actualSorted = @($Actual | Sort-Object)
    $expectedSorted = @($Expected | Sort-Object)
    if ($actualSorted.Count -ne $expectedSorted.Count) {
        return $false
    }
    for ($index = 0; $index -lt $expectedSorted.Count; $index++) {
        if ($actualSorted[$index] -ne $expectedSorted[$index]) {
            return $false
        }
    }
    return $true
}

function Test-ProofSha256 {
    param([object]$Value)
    return (([string]$Value).Trim() -match "^[0-9a-fA-F]{64}$")
}

function Convert-ToProofNumber {
    param([object]$Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $null
    }
    try {
        return [double]$Value
    } catch {
        return $null
    }
}

function New-FirstRunProofConsumption {
    param(
        [string]$PathText,
        [string[]]$ExpectedEvidenceBundleRoles,
        [string[]]$ExpectedReportOutputs,
        [string[]]$ExpectedNextScenarioIds,
        [string]$ExpectedBackupPlanCommand,
        [string]$ExpectedRestoreProofCommand
    )
    $errors = New-Object System.Collections.Generic.List[object]
    $resolved = Resolve-LocalPathText $PathText
    $proof = $null
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        Add-ProofError $errors "FIRST_RUN_PROOF_NOT_SUPPLIED" "Pass -FirstRunProofPath pointing at first_run_pilot_check.ps1 -ProofPath output before claiming backup readiness."
    } elseif (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        Add-ProofError $errors "FIRST_RUN_PROOF_FILE_MISSING" "First-run proof file does not exist: $resolved"
    } else {
        try {
            $proof = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
        } catch {
            Add-ProofError $errors "FIRST_RUN_PROOF_INVALID_JSON" "First-run proof file is not valid JSON: $($_.Exception.Message)"
        }
    }

    if ($null -ne $proof) {
        if ($proof.schemaVersion -ne "h2ometa.first-run-pilot-check.v1") {
            Add-ProofError $errors "FIRST_RUN_PROOF_SCHEMA_INVALID" "First-run proof schemaVersion must be h2ometa.first-run-pilot-check.v1."
        }
        if ($proof.closedLoopProven -ne $true) {
            Add-ProofError $errors "FIRST_RUN_PROOF_NOT_CLOSED_LOOP" "First-run proof must report closedLoopProven=true."
        }
        if ($proof.closedLoopProofMode -ne "submitted-run") {
            Add-ProofError $errors "FIRST_RUN_PROOF_MODE_UNSUPPORTED" "First-run proof must be a fresh submitted-run proof."
        }
        $timing = $proof.runTimingProof
        $timeoutBudget = Convert-ToProofNumber $timing.timeoutBudgetSeconds
        $windowMax = Convert-ToProofNumber $timing.durationWindowSeconds.maxSeconds
        if ($null -eq $timing -or $timing.schemaVersion -ne "h2ometa.first-run.timing-proof.v1" -or $timing.completedWithinTimeout -ne $true -or $timing.withinExpectedDurationWindow -ne $true) {
            Add-ProofError $errors "FIRST_RUN_PROOF_TIMING_REQUIRED" "First-run proof must include runTimingProof completed within the expected 30 minute window."
        } elseif ($null -eq $timeoutBudget -or $null -eq $windowMax -or $timeoutBudget -gt 1800 -or $windowMax -gt 1800) {
            Add-ProofError $errors "FIRST_RUN_PROOF_TIMING_REQUIRED" "First-run proof timing budget must be no more than 1800 seconds."
        }
        if ($null -eq $proof.executionReadinessProof -or $proof.executionReadinessProof.ok -ne $true) {
            Add-ProofError $errors "FIRST_RUN_PROOF_EXECUTION_READINESS_REQUIRED" "First-run proof must include executionReadinessProof.ok=true."
        }
        $sample = $proof.sampleUploadProof
        if ($null -eq $sample -or $sample.schemaVersion -ne "h2ometa.first-run.sample-upload-proof.v1" -or $sample.passed -ne $true) {
            Add-ProofError $errors "FIRST_RUN_PROOF_SAMPLE_UPLOAD_REQUIRED" "First-run proof must include a passed sampleUploadProof."
        } else {
            if ((Get-StringArray $sample.unexpectedRoles).Count -ne 0 -or (Get-StringArray $sample.duplicateRoles).Count -ne 0) {
                Add-ProofError $errors "FIRST_RUN_PROOF_SAMPLE_UPLOAD_REQUIRED" "First-run sampleUploadProof must not contain unexpected or duplicate roles."
            }
            if (-not (Test-SameStringSet (Get-StringArray $sample.expectedRoles) @("metadata", "barcodes", "sequences"))) {
                Add-ProofError $errors "FIRST_RUN_PROOF_SAMPLE_UPLOAD_REQUIRED" "First-run sampleUploadProof must cover metadata, barcodes, and sequences."
            }
        }
        $handoff = $proof.handoffProof
        if ($null -eq $handoff) {
            Add-ProofError $errors "FIRST_RUN_PROOF_HANDOFF_REQUIRED" "First-run proof must include handoffProof."
        } else {
            if ($handoff.evidenceBundleSchemaVersion -ne "h2ometa.first-run.evidence-bundle.v1") {
                Add-ProofError $errors "FIRST_RUN_PROOF_EVIDENCE_BUNDLE_REQUIRED" "handoffProof must include the first-run evidence bundle schema."
            }
            if (-not (Test-SameStringSet (Get-StringArray $handoff.evidenceBundleFileRoles) $ExpectedEvidenceBundleRoles)) {
                Add-ProofError $errors "FIRST_RUN_PROOF_EVIDENCE_BUNDLE_REQUIRED" "handoffProof must include exactly the portable evidence bundle file roles."
            }
            if ([string]::IsNullOrWhiteSpace([string]$handoff.resultId) -or [string]::IsNullOrWhiteSpace([string]$handoff.workflowRevisionId) -or [string]::IsNullOrWhiteSpace([string]$handoff.packageExportId)) {
                Add-ProofError $errors "FIRST_RUN_PROOF_HANDOFF_REQUIRED" "handoffProof must include resultId, workflowRevisionId, and packageExportId."
            }
            if ($null -eq $handoff.resultPackageDownload -or -not (Test-ProofSha256 $handoff.resultPackageDownload.sha256)) {
                Add-ProofError $errors "FIRST_RUN_PROOF_HANDOFF_REQUIRED" "handoffProof must include resultPackageDownload SHA-256 proof."
            }
            if ($null -eq $handoff.evidenceBundleDownload -or -not (Test-ProofSha256 $handoff.evidenceBundleDownload.zipManifestSha256) -or -not (Test-ProofSha256 $handoff.evidenceBundleDownload.validationCardJsonSha256)) {
                Add-ProofError $errors "FIRST_RUN_PROOF_EVIDENCE_BUNDLE_REQUIRED" "handoffProof must include evidenceBundleDownload hashes."
            }
            $completionProof = $handoff.completionProof
            $downloadedValidationCardSha = [string]$handoff.evidenceBundleDownload.validationCardJsonSha256
            $validationCardSha = [string]$handoff.validationCard.validationCardJsonSha256
            if ($null -eq $completionProof) {
                Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof must include persisted completionProof."
            } else {
                if ($completionProof.schemaVersion -ne "h2ometa.first-run.completion-proof.v1" -or $completionProof.ready -ne $true -or [string]::IsNullOrWhiteSpace([string]$completionProof.savedAt) -or [string]::IsNullOrWhiteSpace([string]$completionProof.validationCardJsonSha256)) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must be a persisted h2ometa.first-run.completion-proof.v1 proof with ready=true, savedAt, and validationCardJsonSha256."
                }
                if ($completionProof.serverId -ne $proof.serverId -or $completionProof.runId -ne $proof.runId -or $completionProof.resultId -ne $handoff.resultId -or $completionProof.workflowRevisionId -ne $handoff.workflowRevisionId -or $completionProof.packageExportId -ne $handoff.packageExportId) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must match first-run handoff identity."
                }
                if ($completionProof.resultPackageSha256 -ne $handoff.resultPackageDownload.sha256 -or -not (Test-ProofSha256 $completionProof.resultPackageSha256) -or -not (Test-ProofSha256 $completionProof.resultPackageManifestSha256)) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must include matching result package hashes."
                }
                if (-not (Test-ProofSha256 $completionProof.validationCardJsonSha256) -or $completionProof.validationCardJsonSha256 -ne $downloadedValidationCardSha -or (-not [string]::IsNullOrWhiteSpace($validationCardSha) -and $completionProof.validationCardJsonSha256 -ne $validationCardSha)) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must match validation card and evidence bundle hashes."
                }
                $completionChecksPassed = Convert-ToProofNumber $completionProof.validationChecksPassed
                $completionChecksTotal = Convert-ToProofNumber $completionProof.validationChecksTotal
                if ($null -eq $completionChecksPassed -or $null -eq $completionChecksTotal -or $completionChecksPassed -ne $completionChecksTotal -or $completionChecksTotal -lt 10) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof validation checks must be complete and include at least 10 checks."
                }
                if ($completionProof.reportReady -ne $true -or -not (Test-SameStringSet (Get-StringArray $completionProof.reportOutputNames) $ExpectedReportOutputs)) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must include ready official report outputs."
                }
                if ($completionProof.evidenceBundleReady -ne $true -or $completionProof.evidenceBundleId -ne "$($completionProof.resultId).first-run-evidence" -or -not (Test-SameStringSet (Get-StringArray $completionProof.evidenceBundleFileRoles) $ExpectedEvidenceBundleRoles)) {
                    Add-ProofError $errors "FIRST_RUN_PROOF_COMPLETION_PROOF_REQUIRED" "handoffProof completionProof must include a ready evidence bundle with exact proof roles."
                }
            }
            if ($handoff.backupPlanCommand -ne $ExpectedBackupPlanCommand -or $handoff.restoreProofCommand -ne $ExpectedRestoreProofCommand) {
                Add-ProofError $errors "FIRST_RUN_PROOF_BACKUP_HANDOFF_MISMATCH" "handoffProof backup/restore commands must match the read-only pilot handoff."
            }
            if (-not (Test-SameStringSet (Get-StringArray $handoff.nextScenarioIds) $ExpectedNextScenarioIds)) {
                Add-ProofError $errors "FIRST_RUN_PROOF_NEXT_SCENARIO_REQUIRED" "handoffProof must include the taxonomy and AMR next scenario gates."
            }
            $coverage = @($handoff.nextScenarioDatabasePackCoverage)
            if ($coverage.Count -lt 2) {
                Add-ProofError $errors "FIRST_RUN_PROOF_NEXT_SCENARIO_REQUIRED" "handoffProof must include database pack coverage for blocked next scenarios."
            }
        }
    }

    $accepted = ($errors.Count -eq 0)
    return [ordered]@{
        schemaVersion = "h2ometa.single-user-pilot-first-run-proof-consumption.v1"
        path = $resolved
        status = if ($accepted) { "accepted" } elseif ([string]::IsNullOrWhiteSpace($resolved)) { "not_supplied" } else { "blocked" }
        accepted = $accepted
        errors = @($errors.ToArray())
        summary = if ($null -eq $proof) { $null } else { [ordered]@{
            runId = [string]$proof.runId
            serverId = [string]$proof.serverId
            closedLoopProofMode = [string]$proof.closedLoopProofMode
            resultId = [string]$proof.handoffProof.resultId
            workflowRevisionId = [string]$proof.handoffProof.workflowRevisionId
            packageExportId = [string]$proof.handoffProof.packageExportId
            completionProof = if ($null -eq $proof.handoffProof.completionProof) { $null } else { [ordered]@{
                schemaVersion = [string]$proof.handoffProof.completionProof.schemaVersion
                ready = [bool]$proof.handoffProof.completionProof.ready
                savedAt = [string]$proof.handoffProof.completionProof.savedAt
                serverId = [string]$proof.handoffProof.completionProof.serverId
                runId = [string]$proof.handoffProof.completionProof.runId
                resultId = [string]$proof.handoffProof.completionProof.resultId
                workflowRevisionId = [string]$proof.handoffProof.completionProof.workflowRevisionId
                packageExportId = [string]$proof.handoffProof.completionProof.packageExportId
                resultPackageSha256 = [string]$proof.handoffProof.completionProof.resultPackageSha256
                resultPackageManifestSha256 = [string]$proof.handoffProof.completionProof.resultPackageManifestSha256
                validationCardJsonSha256 = [string]$proof.handoffProof.completionProof.validationCardJsonSha256
                validationChecksPassed = $proof.handoffProof.completionProof.validationChecksPassed
                validationChecksTotal = $proof.handoffProof.completionProof.validationChecksTotal
                reportReady = [bool]$proof.handoffProof.completionProof.reportReady
                reportOutputNames = Get-StringArray $proof.handoffProof.completionProof.reportOutputNames
                evidenceBundleId = [string]$proof.handoffProof.completionProof.evidenceBundleId
                evidenceBundleReady = [bool]$proof.handoffProof.completionProof.evidenceBundleReady
                evidenceBundleFileRoles = Get-StringArray $proof.handoffProof.completionProof.evidenceBundleFileRoles
            } }
            evidenceBundleFileRoles = Get-StringArray $proof.handoffProof.evidenceBundleFileRoles
            nextScenarioIds = Get-StringArray $proof.handoffProof.nextScenarioIds
            runTimingProof = if ($null -eq $proof.runTimingProof) { $null } else { [ordered]@{
                withinExpectedDurationWindow = [bool]$proof.runTimingProof.withinExpectedDurationWindow
                completedWithinTimeout = [bool]$proof.runTimingProof.completedWithinTimeout
                timeoutBudgetSeconds = $proof.runTimingProof.timeoutBudgetSeconds
                observedDurationSeconds = $proof.runTimingProof.observedDurationSeconds
                durationSource = [string]$proof.runTimingProof.durationSource
            } }
        } }
    }
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
$expectedReportOutputs = @("summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html")
$expectedNextScenarioIds = @("taxonomy-classification", "amr-annotation")
$expectedBackupPlanCommand = 'scripts\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "<remote-shared-root>" -FirstRunProofPath "<first-run-proof.json>" -RequireExistingState'
$expectedRestoreProofCommand = "scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady"
$firstRunProof = New-FirstRunProofConsumption `
    -PathText $FirstRunProofPath `
    -ExpectedEvidenceBundleRoles $expectedEvidenceBundleRoles `
    -ExpectedReportOutputs $expectedReportOutputs `
    -ExpectedNextScenarioIds $expectedNextScenarioIds `
    -ExpectedBackupPlanCommand $expectedBackupPlanCommand `
    -ExpectedRestoreProofCommand $expectedRestoreProofCommand
foreach ($proofError in @($firstRunProof.errors)) {
    Add-Blocker $blockers $proofError.code $proofError.message
}

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
    firstRunProof = $firstRunProof
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
            "runTimingProof.schemaVersion=h2ometa.first-run.timing-proof.v1",
            "runTimingProof.completedWithinTimeout=true",
            "runTimingProof.withinExpectedDurationWindow=true",
            "runTimingProof.timeoutBudgetSeconds<=1800",
            "executionReadinessProof.ok=true",
            "sampleUploadProof.schemaVersion=h2ometa.first-run.sample-upload-proof.v1",
            "sampleUploadProof.passed=true",
            "sampleUploadProof.unexpectedRoles=[]",
            "sampleUploadProof.duplicateRoles=[]",
            "validationCard ready",
            "resultPackage SHA256 present",
            "sampleUploadProof covers metadata, barcodes, and sequences",
            "handoffProof.completionProof.savedAt",
            "handoffProof.completionProof.schemaVersion=h2ometa.first-run.completion-proof.v1",
            "handoffProof.completionProof.ready=true",
            "handoffProof.completionProof.validationChecksTotal>=10",
            "handoffProof.completionProof.reportOutputNames=$($expectedReportOutputs -join ',')",
            "handoffProof.completionProof.validationCardJsonSha256",
            "handoffProof.evidenceBundleSchemaVersion=h2ometa.first-run.evidence-bundle.v1",
            "handoffProof.evidenceBundleFileRoles=$($expectedEvidenceBundleRoles -join ',')",
            "handoffProof.backupPlanCommand=$expectedBackupPlanCommand",
            "handoffProof.restoreProofCommand=$expectedRestoreProofCommand",
            "handoffProof.nextScenarioIds=$($expectedNextScenarioIds -join ',')",
            "handoffProof.nextScenarioDatabasePackCoverage.toolSliceRequiredState=WorkflowReady",
            "handoffProof.nextScenarioDatabasePackCoverage.toolSlicePromotionEvidence=toolRevisionId,capability-bundle-v1,RuleSpec,environment-lock,smoke-fixture,expected-output-artifacts",
            "handoffProof.nextScenarioDatabasePackCoverage.toolAcceptanceContractCount>=3",
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
                    toolSliceRequiredState = "WorkflowReady"
                    toolSlicePromotionEvidence = @("toolRevisionId", "capability-bundle-v1", "RuleSpec", "environment-lock", "smoke-fixture", "expected-output-artifacts")
                    toolAcceptanceContractCount = 3
                    readyScanPath = "/api/v1/database-pack-ready-scans"
                    registrationPrefillSource = "database-pack-ready-scan.registrationPrefill"
                },
                [ordered]@{
                    scenarioId = "amr-annotation"
                    status = "blocked"
                    packCount = 0
                    missingTemplates = @("card_rgi", "eggnog_mapper", "interproscan")
                    toolSliceRequiredState = "WorkflowReady"
                    toolSlicePromotionEvidence = @("toolRevisionId", "capability-bundle-v1", "RuleSpec", "environment-lock", "smoke-fixture", "expected-output-artifacts")
                    toolAcceptanceContractCount = 3
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
