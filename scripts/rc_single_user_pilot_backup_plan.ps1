param(
    [string]$RepoRoot,
    [string]$FirstRunProofPath,
    [string]$RemoteRunnerSharedRoot,
    [string]$PlanPath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $FirstRunProofPath)) {
    throw "single-user pilot backup plan requires first-run-pilot-proof.json from -RunFirstRunPilotProof or -FirstRunPilotRunId"
}

$sharedRoot = $RemoteRunnerSharedRoot.Trim()
if (-not $sharedRoot) {
    throw "single-user pilot backup plan requires -SingleUserPilotRemoteRunnerSharedRoot"
}

$planArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $RepoRoot "scripts\single_user_pilot_backup_plan.ps1"),
    "-RemoteRunnerSharedRoot", $sharedRoot,
    "-FirstRunProofPath", $FirstRunProofPath,
    "-RequireExistingState"
)

$planOutput = & powershell @planArgs
$exitCode = $LASTEXITCODE
$planText = ($planOutput | Out-String).Trim()
if ($planText) {
    $planText | Set-Content -LiteralPath $PlanPath -Encoding utf8
}
if ($exitCode -ne 0) {
    throw "single_user_pilot_backup_plan.ps1 exited with code $exitCode"
}
if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "single-user pilot backup plan JSON was not written"
}

$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
if ($plan.schemaVersion -ne "h2ometa.single-user-pilot-backup-plan.v1") {
    throw "single-user pilot backup plan schemaVersion is invalid"
}
if ($plan.readyForManualBackup -ne $true) {
    throw "single-user pilot backup plan is not readyForManualBackup"
}
if ($plan.firstRunProof.accepted -ne $true) {
    throw "single-user pilot backup plan did not accept first-run proof"
}

Write-Host "planPath=$PlanPath"
Write-Host "readyForManualBackup=$($plan.readyForManualBackup)"
Write-Host "firstRunProofStatus=$($plan.firstRunProof.status)"
