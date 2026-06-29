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
    return $submitted.runId
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
    $RunId = Submit-FirstRun $ServerId
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
        if ($null -eq $finalization.pilotHandoff -or $finalization.pilotHandoff.scope -ne "single-user-lab") {
            Fail-Pilot "ready finalization must include a single-user-lab pilotHandoff"
        }
        if (-not $finalization.resultPackage.sha256 -or -not $finalization.resultPackage.manifestSha256) {
            Fail-Pilot "ready finalization resultPackage must include sha256 and manifestSha256"
        }
        $closedLoopProven = $true
        if (-not $RunFirstSuccessfulRun) {
            $closedLoopProofMode = $ClosedLoopProofModes.FinalizedRun
        }
    } elseif ($finalization.status -eq "blocked") {
        $finalizationAction = $finalization.nextAction
        if ($RequireFinalizationReady -or $RunFirstSuccessfulRun) {
            Fail-Pilot "first-run finalization is blocked: $($finalization.nextAction.code)"
        }
        if ($null -eq $finalization.nextAction -or -not $finalization.nextAction.code -or -not $finalization.nextAction.target) {
            Fail-Pilot "blocked finalization must include nextAction code and target"
        }
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
}

Write-Step "passed"
$summary | ConvertTo-Json -Depth 8
