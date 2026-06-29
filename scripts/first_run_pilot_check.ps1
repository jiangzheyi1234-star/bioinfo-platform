param(
    [string]$ApiBase = $(if ($env:H2OMETA_API_BASE) { $env:H2OMETA_API_BASE } else { "http://127.0.0.1:8765" }),
    [string]$WebBase = $(if ($env:H2OMETA_WEB_BASE) { $env:H2OMETA_WEB_BASE } else { "http://127.0.0.1:3765" }),
    [int]$TimeoutSeconds = 20,
    [string]$RunId = "",
    [string]$ServerId = "",
    [switch]$RequireFinalizationReady
)

$ErrorActionPreference = "Stop"
$FirstRunPipelineId = "moving-pictures-16s-rulegraph-v1"
$FirstRunScenarioId = "moving-pictures-16s"
$RequiredEvidence = @("resultPackage", "validationCard", "workflowRevision", "inputLineage", "outputChecksums")

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
        [hashtable]$Body
    )
    try {
        return Invoke-RestMethod -Method Post -Uri $Url -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8) -TimeoutSec $TimeoutSeconds
    } catch {
        Fail-Pilot "POST failed: $Url :: $($_.Exception.Message)"
    }
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

$finalizationStatus = "not-run"
$finalizationAction = $null
if ($RunId) {
    Write-Step "checking first-run finalization for $RunId"
    $body = @{ actor = "first-run-pilot-check" }
    if ($ServerId) {
        $body["serverId"] = $ServerId
    }
    $finalization = (Post-Json "$ApiBase/api/v1/first-run/runs/$([uri]::EscapeDataString($RunId))/finalize" $body).data
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
    } elseif ($finalization.status -eq "blocked") {
        $finalizationAction = $finalization.nextAction
        if ($RequireFinalizationReady) {
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
    runId = $RunId
    finalizationStatus = $finalizationStatus
    finalizationNextAction = $finalizationAction
}

Write-Step "passed"
$summary | ConvertTo-Json -Depth 8
