param(
    [string]$ApiBase = $(if ($env:H2OMETA_API_BASE) { $env:H2OMETA_API_BASE } else { "http://127.0.0.1:8765" }),
    [string]$WebBase = $(if ($env:H2OMETA_WEB_BASE) { $env:H2OMETA_WEB_BASE } else { "http://127.0.0.1:3765" }),
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[local-web-smoke] $Message"
}

function Fail-Smoke {
    param([string]$Message)
    throw "LOCAL_WEB_SMOKE_FAILED: $Message"
}

function Get-Json {
    param([string]$Url)
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSeconds
    } catch {
        Fail-Smoke "JSON request failed: $Url :: $($_.Exception.Message)"
    }
}

function Get-Page {
    param([string]$Url)
    try {
        return Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSeconds
    } catch {
        Fail-Smoke "Page request failed: $Url :: $($_.Exception.Message)"
    }
}

function Assert-ArrayData {
    param(
        [object]$Payload,
        [string]$Name
    )
    if ($null -eq $Payload.data -or $null -eq $Payload.data.items) {
        Fail-Smoke "$Name response must include data.items"
    }
    if ($Payload.data.items -isnot [array]) {
        Fail-Smoke "$Name data.items must be an array"
    }
}

function Assert-PageText {
    param(
        [object]$Response,
        [string]$Route,
        [string[]]$ExpectedText
    )
    if ($Response.StatusCode -ne 200) {
        Fail-Smoke "$Route returned HTTP $($Response.StatusCode)"
    }
    foreach ($text in $ExpectedText) {
        if (-not $Response.Content.Contains($text)) {
            Fail-Smoke "$Route did not include expected text: $text"
        }
    }
}

function Assert-NextStaticAsset {
    param(
        [object]$Response,
        [string]$Kind,
        [string]$Pattern
    )
    $match = [regex]::Match($Response.Content, $Pattern)
    if (-not $match.Success) {
        Fail-Smoke "Web page did not include a Next static $Kind asset"
    }
    $assetUrl = "$WebBase$($match.Groups['path'].Value)"
    $asset = Get-Page $assetUrl
    if ($asset.StatusCode -ne 200) {
        Fail-Smoke "Next static $Kind asset returned HTTP $($asset.StatusCode): $assetUrl"
    }
}

Write-Step "checking Local API at $ApiBase"
$health = Get-Json "$ApiBase/health"
if ($health.status -ne "ok") {
    Fail-Smoke "/health status must be ok"
}

$serviceInfo = Get-Json "$ApiBase/api/v1/service-info"
if ($serviceInfo.item.readiness.status -ne "ready") {
    Fail-Smoke "/api/v1/service-info readiness must be ready"
}

$catalog = Get-Json "$ApiBase/api/v1/workflow-catalog"
Assert-ArrayData $catalog "workflow catalog"
if ($catalog.data.items.Count -lt 1) {
    Fail-Smoke "workflow catalog must expose at least one workflow"
}

$tools = Get-Json "$ApiBase/api/v1/tools"
Assert-ArrayData $tools "tools"

$databases = Get-Json "$ApiBase/api/v1/databases"
Assert-ArrayData $databases "databases"

Write-Step "checking Web UI at $WebBase"
$routes = @(
    @{ Path = "/workflows/first-run"; Text = @("app/workflows/first-run/page.js", "/workflows/first-run") },
    @{ Path = "/workflows"; Text = @("/workflows/databases", "/workflows/tools", "app/workflows/page.js") },
    @{ Path = "/workflows/databases"; Text = @("app/workflows/databases/page.js", "/workflows/tools") },
    @{ Path = "/workflows/tools"; Text = @("app/workflows/tools/page.js", "/workflows/databases") },
    @{ Path = "/workflows/detail?workflow=generated-tool-run-v1"; Text = @("app/workflows/detail/page.js", "generated-tool-run-v1") },
    @{ Path = "/workflows/results"; Text = @("app/workflows/results/page.js", "/workflows/results") }
)

$firstPage = $null
foreach ($route in $routes) {
    $page = Get-Page "$WebBase$($route.Path)"
    if ($null -eq $firstPage) {
        $firstPage = $page
    }
    Assert-PageText $page $route.Path $route.Text
}

Assert-NextStaticAsset $firstPage "CSS" 'href="(?<path>/_next/static/css/[^"?]+(?:\?[^" ]*)?)"'
Assert-NextStaticAsset $firstPage "JS" 'src="(?<path>/_next/static/(?:chunks|app)/[^"?]+\.js(?:\?[^" ]*)?)"'

$summary = [ordered]@{
    apiBase = $ApiBase
    webBase = $WebBase
    workflowCount = $catalog.data.items.Count
    toolCount = $tools.data.items.Count
    databaseCount = $databases.data.items.Count
    backendSource = $serviceInfo.item.identity.backendSource
}

Write-Step "passed"
$summary | ConvertTo-Json -Depth 4
