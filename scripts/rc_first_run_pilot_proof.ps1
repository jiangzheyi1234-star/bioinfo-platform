param(
    [string]$RepoRoot,
    [string]$ApiBase,
    [string]$WebBase,
    [string]$ProofPath,
    [string]$RunId = ""
)

$ErrorActionPreference = "Stop"

$checkArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $RepoRoot "scripts\first_run_pilot_check.ps1"),
    "-ApiBase", $ApiBase,
    "-WebBase", $WebBase,
    "-RequireFinalizationReady",
    "-ProofPath", $ProofPath
)
if ($RunId) {
    $checkArgs += @("-RunId", $RunId)
} else {
    $checkArgs += "-RunFirstSuccessfulRun"
}

& powershell @checkArgs
if ($LASTEXITCODE -ne 0) {
    throw "first_run_pilot_check.ps1 exited with code $LASTEXITCODE"
}
if (-not (Test-Path -LiteralPath $ProofPath)) {
    throw "first-run pilot proof JSON was not written"
}

$proof = Get-Content -LiteralPath $ProofPath -Raw | ConvertFrom-Json
if ($proof.schemaVersion -ne "h2ometa.first-run-pilot-check.v1") {
    throw "first-run pilot proof schemaVersion is invalid"
}
if ($proof.closedLoopProven -ne $true) {
    throw "first-run pilot proof did not prove a closed loop"
}
if ($proof.handoffProof.validationCard.validationCardJsonSha256 -eq $null) {
    throw "first-run pilot proof must include validationCardJsonSha256"
}
if ($proof.handoffProof.evidenceBundleDownload.completionProofJsonSha256 -eq $null) {
    throw "first-run pilot proof must include completionProofJsonSha256"
}
if (-not $RunId) {
    if ($proof.runTimingProof.schemaVersion -ne "h2ometa.first-run.timing-proof.v1" -or $proof.runTimingProof.withinExpectedDurationWindow -ne $true) {
        throw "fresh first-run pilot proof must include runTimingProof within the expected duration window"
    }
}

Write-Host "proofPath=$ProofPath"
Write-Host "closedLoopProofMode=$($proof.closedLoopProofMode)"
Write-Host "runId=$($proof.runId)"
Write-Host "runTimingProof.withinExpectedDurationWindow=$($proof.runTimingProof.withinExpectedDurationWindow)"
Write-Host "workflowRevisionId=$($proof.handoffProof.workflowRevisionId)"
Write-Host "packageExportId=$($proof.handoffProof.packageExportId)"
