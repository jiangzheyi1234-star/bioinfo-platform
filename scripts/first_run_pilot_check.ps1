param(
    [string]$ApiBase = $(if ($env:H2OMETA_API_BASE) { $env:H2OMETA_API_BASE } else { "http://127.0.0.1:8765" }),
    [string]$WebBase = $(if ($env:H2OMETA_WEB_BASE) { $env:H2OMETA_WEB_BASE } else { "http://127.0.0.1:3765" }),
    [int]$TimeoutSeconds = 20,
    [int]$SampleDataTimeoutSeconds = 300,
    [int]$FinalizationTimeoutSeconds = 120,
    [int]$RunTimeoutSeconds = 1800,
    [int]$PollSeconds = 5,
    [string]$RunId = "",
    [string]$ServerId = "",
    [switch]$RunFirstSuccessfulRun,
    [switch]$RequireFinalizationReady
)

$ErrorActionPreference = "Stop"
$FirstRunPipelineId = "moving-pictures-16s-rulegraph-v1"
$FirstRunScenarioId = "moving-pictures-16s"
$RequiredEvidence = @("resultPackage", "validationCard", "workflowRevision", "inputLineage", "outputChecksums")
$ClosedLoopProofModes = @{
    SmokeOnly = "catalog-page-smoke"
    FinalizedRun = "finalized-run"
    SubmittedRun = "submitted-run"
}
$BlockedNextActionTargets = @{
    FIRST_RUN_NOT_SUCCESSFUL = "/workflows/first-run#run-report"
    FIRST_RUN_WORKFLOW_REVISION_REQUIRED = "/workflows/first-run#runner-readiness"
    FIRST_RUN_REPORT_PREVIEW_REQUIRED = "/workflows/first-run#run-report"
    FIRST_RUN_SAMPLE_INPUTS_REQUIRED = "/workflows/first-run#sample-data"
    FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH = "/workflows/first-run#sample-data"
}
$FirstRunRecoveryAnchors = @("runner-readiness", "sample-data", "run-report", "result-package", "validation-card")

function Write-Step {
    param([string]$Message)
    Write-Host "[first-run-pilot] $Message"
}

function Fail-Pilot {
    param([string]$Message)
    throw "FIRST_RUN_PILOT_CHECK_FAILED: $Message"
}

function Get-Json {
    param([string]$Url)
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSeconds
    } catch {
        Fail-Pilot "JSON request failed: $Url :: $($_.Exception.Message)"
    }
}

function Get-Page {
    param([string]$Url)
    try {
        return Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
    } catch {
        Fail-Pilot "Page request failed: $Url :: $($_.Exception.Message)"
    }
}

function Post-Json {
    param(
        [string]$Url,
        [hashtable]$Body,
        [int]$RequestTimeoutSeconds = $TimeoutSeconds
    )
    try {
        return Invoke-RestMethod -Method Post -Uri $Url -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8) -TimeoutSec $RequestTimeoutSeconds
    } catch {
        Fail-Pilot "POST failed: $Url :: $($_.Exception.Message)"
    }
}

function Get-ServerId {
    param([string]$ExplicitServerId)
    $servers = Get-Json "$ApiBase/api/v1/servers?refresh=true"
    Assert-ArrayData $servers "servers"
    if ($ExplicitServerId) {
        $selected = @($servers.data.items | Where-Object { $_.serverId -eq $ExplicitServerId }) | Select-Object -First 1
        if ($null -eq $selected) {
            Fail-Pilot "server $ExplicitServerId was not found"
        }
    } else {
        $selected = @($servers.data.items | Where-Object { $_.connected -eq $true -and $_.ready -eq $true -and $_.serverId }) | Select-Object -First 1
    }
    if ($null -eq $selected -or -not $selected.serverId) {
        Fail-Pilot "a connected and ready server is required for first-run execution"
    }
    if ($selected.connected -ne $true -or $selected.ready -ne $true) {
        Fail-Pilot "server $($selected.serverId) must be connected and ready for first-run execution"
    }
    return $selected.serverId
}

function Assert-Sample-Uploads {
    param([object[]]$Uploads)
    $requiredRoles = @("metadata", "barcodes", "sequences")
    foreach ($role in $requiredRoles) {
        $upload = @($Uploads | Where-Object { $_.role -eq $role }) | Select-Object -First 1
        if ($null -eq $upload) {
            Fail-Pilot "sample upload missing role $role"
        }
        if (-not $upload.uploadId -or -not $upload.filename) {
            Fail-Pilot "sample upload $role must include uploadId and filename"
        }
        if ($upload.integrityStatus -ne "passed" -or -not $upload.sha256 -or $upload.sha256 -ne $upload.expectedSha256) {
            Fail-Pilot "sample upload $role must have passed checksum evidence"
        }
    }
}

function New-FirstRunRunSpec {
    param([object[]]$Uploads)
    return @{
        projectId = "first-run-pilot"
        pipelineId = $FirstRunPipelineId
        inputs = @(
            $Uploads | ForEach-Object {
                @{
                    uploadId = $_.uploadId
                    filename = $_.filename
                    role = $_.role
                }
            }
        )
        params = @{}
    }
}

function New-SampleUploadProof {
    param([object[]]$Uploads)
    $items = @(
        $Uploads | ForEach-Object {
            [ordered]@{
                role = $_.role
                filename = $_.filename
                uploadId = $_.uploadId
                sha256 = $_.sha256
                expectedSha256 = $_.expectedSha256
                sizeBytes = $_.sizeBytes
                expectedSizeBytes = $_.expectedSizeBytes
                integrityStatus = $_.integrityStatus
            }
        }
    )
    return [ordered]@{
        passed = ($items.Count -eq 3 -and (@($items | Where-Object { $_.integrityStatus -eq "passed" -and $_.sha256 -and $_.sha256 -eq $_.expectedSha256 }).Count -eq 3))
        count = $items.Count
        roles = @($items | ForEach-Object { $_.role })
        items = $items
    }
}

function Submit-FirstRun {
    param([string]$ResolvedServerId)
    Write-Step "preparing official Moving Pictures sample data"
    $sampleResponse = Post-Json "$ApiBase/api/v1/workflow-sample-data/$([uri]::EscapeDataString($FirstRunPipelineId))/uploads" @{
        serverId = $ResolvedServerId
    } $SampleDataTimeoutSeconds
    $uploads = @($sampleResponse.data.items)
    Assert-Sample-Uploads $uploads
    Write-Step "submitting first-run workflow"
    $requestId = "req_first_run_pilot_$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    $submitResponse = Post-Json "$ApiBase/api/v1/runs" @{
        serverId = $ResolvedServerId
        requestId = $requestId
        idempotencyKey = $requestId
        runSpec = (New-FirstRunRunSpec $uploads)
    }
    $submitted = $submitResponse.data
    if (-not $submitted.runId) {
        Fail-Pilot "submitted first-run response must include runId"
    }
    return [ordered]@{
        runId = $submitted.runId
        sampleUploadProof = New-SampleUploadProof $uploads
    }
}

function Assert-ExecutionReadiness {
    param([string]$ResolvedServerId)
    Write-Step "checking execution readiness for $ResolvedServerId"
    $diagnostics = (Get-Json "$ApiBase/api/v1/servers/$([uri]::EscapeDataString($ResolvedServerId))/execution-diagnostics").data
    if ($null -eq $diagnostics) {
        Fail-Pilot "execution diagnostics response must include data"
    }
    $readiness = $diagnostics.readiness
    $blockingReasons = @($readiness.blockingReasons)
    $degradedReasons = @($readiness.degradedReasons)
    if ($null -eq $readiness -or $readiness.ok -ne $true) {
        $firstBlocker = @($blockingReasons | Select-Object -First 1)
        $detail = @(
            [string]$readiness.reasonCode,
            [string]$firstBlocker.code,
            [string]$firstBlocker.message,
            [string]$readiness.status
        ) | Where-Object { $_ } | Select-Object -First 3
        if (@($detail).Count -eq 0) {
            $detail = @("execution readiness is not ok")
        }
        Fail-Pilot "execution diagnostics readiness must be ok: $($detail -join ' / ')"
    }
    return [ordered]@{
        schemaVersion = [string]$diagnostics.schemaVersion
        readinessSchemaVersion = [string]$readiness.schemaVersion
        ok = $true
        status = [string]$readiness.status
        reasonCode = [string]$readiness.reasonCode
        blockingReasonCount = $blockingReasons.Count
        degradedReasonCount = $degradedReasons.Count
    }
}

function Wait-Run-Terminal {
    param([string]$TargetRunId)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RunTimeoutSeconds)
    $lastStatus = "unknown"
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $detail = (Get-Json "$ApiBase/api/v1/runs/$([uri]::EscapeDataString($TargetRunId))/detail").data
        $run = $detail.run
        $lastStatus = [string]$run.status
        if ($lastStatus -in @("completed", "failed", "error", "canceled", "cancelled")) {
            if ($lastStatus -ne "completed") {
                Fail-Pilot "first-run ended as $lastStatus"
            }
            return $run
        }
        Start-Sleep -Seconds $PollSeconds
    }
    Fail-Pilot "first-run did not complete within $RunTimeoutSeconds seconds; last status $lastStatus"
}

function Assert-ArrayData {
    param(
        [object]$Payload,
        [string]$Name
    )
    if ($null -eq $Payload.data -or $null -eq $Payload.data.items) {
        Fail-Pilot "$Name response must include data.items"
    }
    if ($Payload.data.items -isnot [array]) {
        Fail-Pilot "$Name data.items must be an array"
    }
}

function Assert-FirstRunPilotHandoff {
    param([object]$Finalization)
    $card = $Finalization.validationCard
    $package = $Finalization.resultPackage
    $handoff = $Finalization.pilotHandoff
    if ($null -eq $handoff -or $handoff.schemaVersion -ne "h2ometa.first-run.single-user-lab-pilot-handoff.v1") {
        Fail-Pilot "ready finalization must include a single-user-lab pilotHandoff"
    }
    if ($handoff.scope -ne "single-user-lab" -or $handoff.status -ne "ready") {
        Fail-Pilot "ready pilotHandoff must be single-user-lab and ready"
    }

    $evidence = $handoff.evidence
    if ($null -eq $evidence) {
        Fail-Pilot "ready pilotHandoff must include evidence"
    }
    if ($evidence.runId -ne $card.run.runId -or $evidence.resultId -ne $card.result.resultId) {
        Fail-Pilot "pilotHandoff evidence must match validationCard run and result"
    }
    if ($evidence.workflowRevisionId -ne $card.workflowRevision.workflowRevisionId) {
        Fail-Pilot "pilotHandoff evidence must match validationCard WorkflowRevision"
    }
    if ($evidence.packageExportId -ne $package.packageExportId) {
        Fail-Pilot "pilotHandoff evidence must match resultPackage packageExportId"
    }
    if ($evidence.packageSha256 -ne $package.sha256 -or $evidence.manifestSha256 -ne $package.manifestSha256) {
        Fail-Pilot "pilotHandoff evidence must match resultPackage hashes"
    }
    if ($evidence.packageSha256 -ne $card.resultPackage.sha256 -or $evidence.manifestSha256 -ne $card.resultPackage.manifestSha256) {
        Fail-Pilot "pilotHandoff evidence must match validationCard resultPackage hashes"
    }

    $checks = @($card.checks)
    $passedChecks = @($checks | Where-Object { $_.status -eq "passed" })
    if ($checks.Count -eq 0 -or $passedChecks.Count -ne $checks.Count) {
        Fail-Pilot "ready validationCard checks must all be passed"
    }
    if ($evidence.validationChecksTotal -ne $checks.Count -or $evidence.validationChecksPassed -ne $passedChecks.Count) {
        Fail-Pilot "pilotHandoff evidence must match validationCard checks"
    }

    $backup = $handoff.backupRestore
    if ($null -eq $backup -or $backup.schemaVersion -ne "h2ometa.first-run.backup-restore-handoff.v1") {
        Fail-Pilot "pilotHandoff must include backupRestore handoff"
    }
    if ($backup.mode -ne "read-only-plan" -or $backup.noAutomaticBackup -ne $true) {
        Fail-Pilot "backupRestore handoff must be a read-only plan with no automatic backup"
    }
    if ($backup.requiresIsolatedRestore -ne $true -or $backup.requiresManualSecretRebind -ne $true) {
        Fail-Pilot "backupRestore handoff must require isolated restore and manual secret rebind"
    }
    $expectedBackupPlanCommand = 'scripts\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "<remote-shared-root>" -RequireExistingState'
    if ($backup.planCommand -ne $expectedBackupPlanCommand) {
        Fail-Pilot "backupRestore handoff must include the read-only backup plan command"
    }
    $expectedRestoreProofCommand = 'scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady'
    if ($backup.restoreProofCommand -ne $expectedRestoreProofCommand) {
        Fail-Pilot "backupRestore handoff must include the submitted-run restore proof command"
    }
    if ($backup.runbookPath -ne "docs/single-user-pilot-backup-restore.md") {
        Fail-Pilot "backupRestore handoff must point at the single-user pilot runbook"
    }
    $expectedExcludedActions = @("hot-sqlite-copy", "secret-archive", "cache-as-durable-state")
    if ((@($backup.excludedActions) -join "|") -ne ($expectedExcludedActions -join "|")) {
        Fail-Pilot "backupRestore handoff must reject hot sqlite copy, secret archive, and cache-as-durable-state"
    }

    $nextScenarios = @($handoff.nextScenarios)
    if ($nextScenarios.Count -lt 2) {
        Fail-Pilot "pilotHandoff must include next scenario pilots"
    }
    foreach ($scenarioId in @("taxonomy-classification", "amr-annotation")) {
        $scenario = @($nextScenarios | Where-Object { $_.scenarioId -eq $scenarioId }) | Select-Object -First 1
        if ($null -eq $scenario -or $scenario.target -ne "/workflows") {
            Fail-Pilot "pilotHandoff nextScenarios missing $scenarioId"
        }
        if ($scenario.status -ne "blocked") {
            Fail-Pilot "pilotHandoff nextScenarios $scenarioId must remain blocked until operator gates pass"
        }
        if (@($scenario.blockedChecks).Count -lt 3) {
            Fail-Pilot "pilotHandoff nextScenarios $scenarioId must include blocked gate evidence"
        }
        if ($null -eq $scenario.databasePackCoverage) {
            Fail-Pilot "pilotHandoff nextScenarios $scenarioId must include databasePackCoverage"
        }
    }
    $taxonomyScenario = @($nextScenarios | Where-Object { $_.scenarioId -eq "taxonomy-classification" }) | Select-Object -First 1
    if ($taxonomyScenario.databasePackCoverage.packCount -ne 1) {
        Fail-Pilot "taxonomy nextScenario must advertise one available database pack"
    }
    $amrScenario = @($nextScenarios | Where-Object { $_.scenarioId -eq "amr-annotation" }) | Select-Object -First 1
    if ((@($amrScenario.databasePackCoverage.missingTemplates) -join "|") -ne "card_rgi|eggnog_mapper|interproscan") {
        Fail-Pilot "AMR nextScenario must advertise missing database pack templates"
    }

    if ($handoff.nextAction.code -ne "RUN_OWN_SMALL_SAMPLE" -or $handoff.nextAction.target -ne "/workflows") {
        Fail-Pilot "pilotHandoff nextAction must guide the operator to run an own small sample"
    }
    return [ordered]@{
        pilotHandoffSchemaVersion = $handoff.schemaVersion
        packageSha256 = $evidence.packageSha256
        manifestSha256 = $evidence.manifestSha256
        validationChecksPassed = $evidence.validationChecksPassed
        validationChecksTotal = $evidence.validationChecksTotal
        backupRestoreSchemaVersion = $backup.schemaVersion
        backupPlanCommand = $backup.planCommand
        restoreProofCommand = $backup.restoreProofCommand
        nextScenarioIds = @($nextScenarios | ForEach-Object { $_.scenarioId })
    }
}

function Assert-FirstRunBlockedNextAction {
    param([object]$Action)
    if ($null -eq $Action -or -not $Action.code -or -not $Action.target) {
        Fail-Pilot "blocked finalization must include nextAction code and target"
    }
    if ($BlockedNextActionTargets.ContainsKey([string]$Action.code)) {
        $expectedTarget = $BlockedNextActionTargets[[string]$Action.code]
        if ($Action.target -ne $expectedTarget) {
            Fail-Pilot "blocked finalization nextAction target must match $($Action.code)"
        }
    }
    if ($Action.target.StartsWith("/workflows/first-run#")) {
        $anchor = $Action.target.Split("#", 2)[1]
        if ($FirstRunRecoveryAnchors -notcontains $anchor) {
            Fail-Pilot "blocked finalization nextAction target must use a first-run recovery anchor"
        }
    } elseif ($Action.target -ne "/workflows/first-run") {
        Fail-Pilot "blocked finalization nextAction target must stay inside first-run"
    }
    return [ordered]@{
        code = $Action.code
        target = $Action.target
        label = $Action.label
    }
}

Write-Step "checking Local API at $ApiBase"
$health = Get-Json "$ApiBase/health"
if ($health.status -ne "ok") {
    Fail-Pilot "/health status must be ok"
}

$catalog = Get-Json "$ApiBase/api/v1/workflow-catalog"
Assert-ArrayData $catalog "workflow catalog"
$workflow = @($catalog.data.items | Where-Object { $_.id -eq $FirstRunPipelineId }) | Select-Object -First 1
if ($null -eq $workflow) {
    Fail-Pilot "workflow catalog must include $FirstRunPipelineId"
}
if ($workflow.runnable -ne $true) {
    Fail-Pilot "$FirstRunPipelineId must be runnable for a single-user pilot"
}

$packs = Get-Json "$ApiBase/api/v1/workflow-scenario-packs"
Assert-ArrayData $packs "workflow scenario packs"
$pack = @($packs.data.items | Where-Object { $_.scenarioId -eq $FirstRunScenarioId }) | Select-Object -First 1
if ($null -eq $pack) {
    Fail-Pilot "scenario packs must include $FirstRunScenarioId"
}
if ($pack.status -ne "ready" -or $pack.firstRunPath -ne "/workflows/first-run") {
    Fail-Pilot "$FirstRunScenarioId must be ready and point at /workflows/first-run"
}
foreach ($evidence in $RequiredEvidence) {
    if ($pack.resultEvidence -notcontains $evidence) {
        Fail-Pilot "$FirstRunScenarioId resultEvidence missing $evidence"
    }
}

Write-Step "checking First Successful Run UI at $WebBase"
$firstRunPage = Get-Page "$WebBase/workflows/first-run"
if ($firstRunPage.StatusCode -ne 200) {
    Fail-Pilot "/workflows/first-run returned HTTP $($firstRunPage.StatusCode)"
}
if (-not $firstRunPage.Content.Contains("app/workflows/first-run/page.js")) {
    Fail-Pilot "/workflows/first-run must include the first-run Next page bundle"
}

$closedLoopProven = $false
$closedLoopProofMode = $ClosedLoopProofModes.SmokeOnly
$finalizationStatus = "not-run"
$finalizationAction = $null
$handoffProof = $null
$blockedActionProof = $null
$executionReadinessProof = $null
$sampleUploadProof = $null
if ($RunFirstSuccessfulRun -and $RunId) {
    Fail-Pilot "-RunFirstSuccessfulRun cannot be combined with -RunId"
}
if ($RequireFinalizationReady -and -not $RunId) {
    if (-not $RunFirstSuccessfulRun) {
        Fail-Pilot "-RequireFinalizationReady requires -RunId or -RunFirstSuccessfulRun"
    }
}
if ($RunFirstSuccessfulRun) {
    $ServerId = Get-ServerId $ServerId
    $executionReadinessProof = Assert-ExecutionReadiness $ServerId
    $submissionProof = Submit-FirstRun $ServerId
    $RunId = $submissionProof.runId
    $sampleUploadProof = $submissionProof.sampleUploadProof
    $null = Wait-Run-Terminal $RunId
    $closedLoopProofMode = $ClosedLoopProofModes.SubmittedRun
}
if ($RunId) {
    Write-Step "checking first-run finalization for $RunId"
    $body = @{ actor = "first-run-pilot-check" }
    if ($ServerId) {
        $body["serverId"] = $ServerId
    }
    $finalization = (Post-Json "$ApiBase/api/v1/first-run/runs/$([uri]::EscapeDataString($RunId))/finalize" $body $FinalizationTimeoutSeconds).data
    if ($finalization.schemaVersion -ne "h2ometa.first-run.finalization.v1") {
        Fail-Pilot "first-run finalization schemaVersion is invalid"
    }
    $finalizationStatus = $finalization.status
    if ($finalization.status -eq "ready") {
        if ($null -eq $finalization.validationCard -or $null -eq $finalization.resultPackage) {
            Fail-Pilot "ready finalization must include validationCard and resultPackage"
        }
        if (-not $finalization.resultPackage.sha256 -or -not $finalization.resultPackage.manifestSha256) {
            Fail-Pilot "ready finalization resultPackage must include sha256 and manifestSha256"
        }
        $handoffProof = Assert-FirstRunPilotHandoff $finalization
        $closedLoopProven = $true
        if (-not $RunFirstSuccessfulRun) {
            $closedLoopProofMode = $ClosedLoopProofModes.FinalizedRun
        }
    } elseif ($finalization.status -eq "blocked") {
        $finalizationAction = $finalization.nextAction
        if ($RequireFinalizationReady -or $RunFirstSuccessfulRun) {
            Fail-Pilot "first-run finalization is blocked: $($finalization.nextAction.code)"
        }
        $blockedActionProof = Assert-FirstRunBlockedNextAction $finalization.nextAction
    } else {
        Fail-Pilot "first-run finalization status must be ready or blocked"
    }
}

$summary = [ordered]@{
    schemaVersion = "h2ometa.first-run-pilot-check.v1"
    apiBase = $ApiBase
    webBase = $WebBase
    pipelineId = $FirstRunPipelineId
    workflowReady = $true
    scenarioId = $FirstRunScenarioId
    scenarioStatus = $pack.status
    firstRunPath = $pack.firstRunPath
    serverId = $ServerId
    runId = $RunId
    closedLoopProven = $closedLoopProven
    closedLoopProofMode = $closedLoopProofMode
    finalizationStatus = $finalizationStatus
    finalizationNextAction = $finalizationAction
    handoffProof = $handoffProof
    blockedActionProof = $blockedActionProof
    executionReadinessProof = $executionReadinessProof
    sampleUploadProof = $sampleUploadProof
}

Write-Step "passed"
$summary | ConvertTo-Json -Depth 8
