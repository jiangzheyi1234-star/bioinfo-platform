param(
  [string]$ApiBase = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

function Invoke-Api {
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Path,
    [object]$Body = $null
  )

  $uri = "$ApiBase$Path"
  if ($null -eq $Body) {
    return Invoke-RestMethod -Method $Method -Uri $uri -TimeoutSec 20
  }

  return Invoke-RestMethod `
    -Method $Method `
    -Uri $uri `
    -ContentType "application/json" `
    -Body ($Body | ConvertTo-Json -Depth 10) `
    -TimeoutSec 20
}

function Assert-ApiFails {
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Path,
    [object]$Body = $null
  )

  try {
    $null = Invoke-Api -Method $Method -Path $Path -Body $Body
  }
  catch {
    return
  }
  throw "Expected API failure but request succeeded: $Method $Path"
}

Write-Host "=== M6 Regression (Desktop Migration) ==="
Write-Host "API Base: $ApiBase"

$health = Invoke-Api -Method "GET" -Path "/health"
if ($health.status -ne "ok") {
  throw "Health check failed: $($health | ConvertTo-Json -Compress)"
}
Write-Host "[PASS] /health"

$projectsResp = Invoke-Api -Method "GET" -Path "/api/v1/projects"
$projects = @($projectsResp.items)
$projectId = ""

if ($projects.Count -eq 0) {
  $newProjectName = "m6_regression_" + (Get-Date -Format "yyyyMMdd_HHmmss")
  $created = Invoke-Api -Method "POST" -Path "/api/v1/projects" -Body @{
    name = $newProjectName
    description = "auto regression project"
    open_after_create = $true
  }
  $projectId = [string]$created.item.project_id
  Write-Host "[PASS] create project: $projectId"
}
else {
  $projectId = [string]$projects[0].project_id
}

$null = Invoke-Api -Method "POST" -Path "/api/v1/projects/$projectId/open"
Write-Host "[PASS] open project: $projectId"

$currentProject = Invoke-Api -Method "GET" -Path "/api/v1/projects/current"
if ([string]$currentProject.item.project_id -ne $projectId) {
  throw "Current project mismatch: expected=$projectId actual=$([string]$currentProject.item.project_id)"
}
Write-Host "[PASS] current project matches opened project"

$toolsResp = Invoke-Api -Method "GET" -Path "/api/v1/tools"
$tools = @($toolsResp.items)
if ($tools.Count -gt 0) {
  $firstToolId = [string]$tools[0].id
  $null = Invoke-Api -Method "GET" -Path "/api/v1/tools/$firstToolId/descriptor"
  Write-Host "[PASS] tool descriptor: $firstToolId"
}
else {
  Write-Host "[WARN] no tools found; skip descriptor check"
}

$executionsResp = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/executions?limit=10"
Write-Host "[PASS] executions list, rows=$(@($executionsResp.items).Count)"

$historyResp = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/history?limit=10"
Write-Host "[PASS] history list, rows=$(@($historyResp.items).Count)"

$null = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/tools"
Write-Host "[PASS] workbench tools"

$wbConfig = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/config"
$featureCount = @($wbConfig.item.features).Count
Write-Host "[PASS] workbench config, features=$featureCount"

$wbHistory = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/history"
$historyRows = @($wbHistory.items)
Write-Host "[PASS] workbench history, rows=$($historyRows.Count)"

$dbPaths = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/configured-databases"
foreach ($entry in @($dbPaths.items)) {
  if (-not $entry.PSObject.Properties["key"] -or -not $entry.PSObject.Properties["path"] -or -not $entry.PSObject.Properties["label"]) {
    throw "configured-databases row missing required fields: $($entry | ConvertTo-Json -Compress)"
  }
}
Write-Host "[PASS] configured databases, rows=$(@($dbPaths.items).Count)"

if ($historyRows.Count -gt 0) {
  $executionId = [string]$historyRows[0].execution_id
  try {
    $null = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/executions/$executionId/result"
    Write-Host "[PASS] workbench result: $executionId"
  }
  catch {
    Write-Host "[WARN] workbench result not available: $executionId"
  }

  try {
    $null = Invoke-Api -Method "GET" -Path "/api/v1/projects/$projectId/workbench/executions/$executionId/remote-status"
    Write-Host "[PASS] workbench remote status: $executionId"
  }
  catch {
    Write-Host "[WARN] workbench remote status not available: $executionId"
  }
}
else {
  Write-Host "[INFO] no workbench history rows; skip result/remote-status checks"
}

Assert-ApiFails -Method "DELETE" -Path "/api/v1/projects/$projectId/workbench/executions/not_exists_regression_check"
Write-Host "[PASS] delete missing execution fails loudly"

Assert-ApiFails -Method "POST" -Path "/api/v1/workbench/run" -Body @{
  project_id = $projectId
  tool_id = ""
  params = @{}
}
Write-Host "[PASS] invalid workbench run fails loudly"

Write-Host "=== Regression Completed ==="
