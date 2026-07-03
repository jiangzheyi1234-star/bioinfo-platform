function Assert-FirstRunCompletionProof {
    param(
        [object]$Finalization,
        [string]$ValidationCardJsonSha256
    )

    $proof = $Finalization.completionProof
    $card = $Finalization.validationCard
    $package = $Finalization.resultPackage
    $handoff = $Finalization.pilotHandoff
    $bundle = $handoff.evidenceBundle
    if ($null -eq $proof -or $proof.schemaVersion -ne "h2ometa.first-run.completion-proof.v1") {
        Fail-Pilot "ready finalization must include a persisted first-run completionProof"
    }
    if ($proof.ready -ne $true) {
        Fail-Pilot "ready first-run completionProof must be ready"
    }
    if ($proof.serverId -ne $card.runner.serverId) {
        Fail-Pilot "completionProof must match validationCard server"
    }
    if ($proof.runId -ne $card.run.runId -or $proof.resultId -ne $card.result.resultId) {
        Fail-Pilot "completionProof must match validationCard run and result"
    }
    if ($proof.workflowRevisionId -ne $card.workflowRevision.workflowRevisionId) {
        Fail-Pilot "completionProof must match validationCard WorkflowRevision"
    }
    if ($proof.packageExportId -ne $package.packageExportId -or $proof.packageEvidenceId -ne $package.evidenceId) {
        Fail-Pilot "completionProof must match resultPackage identity"
    }
    if ($proof.resultPackageSha256 -ne $package.sha256 -or $proof.resultPackageManifestSha256 -ne $package.manifestSha256) {
        Fail-Pilot "completionProof must match resultPackage hashes"
    }
    if ($proof.validationCardGeneratedAt -ne $card.generatedAt) {
        Fail-Pilot "completionProof must match validationCard generatedAt"
    }
    if ($proof.validationCardJsonSha256 -ne $ValidationCardJsonSha256) {
        Fail-Pilot "completionProof must match downloaded validation card hash"
    }

    $checks = @($card.checks)
    $passedChecks = @($checks | Where-Object { $_.status -eq "passed" })
    if ($proof.validationChecksPassed -ne $passedChecks.Count -or $proof.validationChecksTotal -ne $checks.Count) {
        Fail-Pilot "completionProof must match validationCard checks"
    }
    if ($proof.reportReady -ne $true) {
        Fail-Pilot "completionProof must mark report evidence ready"
    }
    $reportOutputNames = @($card.reportInterpretation.outputs | ForEach-Object { $_.name })
    if (((@($proof.reportOutputNames) | Sort-Object) -join "|") -ne (($reportOutputNames | Sort-Object) -join "|")) {
        Fail-Pilot "completionProof report outputs must match validationCard report"
    }
    if ($proof.evidenceBundleId -ne $bundle.bundleId -or $proof.evidenceBundleReady -ne $true) {
        Fail-Pilot "completionProof must match ready first-run evidenceBundle"
    }
    $bundleRoles = @($bundle.requiredFiles | ForEach-Object { $_.role })
    if (((@($proof.evidenceBundleFileRoles) | Sort-Object) -join "|") -ne (($bundleRoles | Sort-Object) -join "|")) {
        Fail-Pilot "completionProof evidenceBundle roles must match pilotHandoff evidenceBundle"
    }
    if ([string]::IsNullOrWhiteSpace([string]$proof.savedAt)) {
        Fail-Pilot "completionProof must include savedAt"
    }
    $savedAt = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse([string]$proof.savedAt, [ref]$savedAt) -or $savedAt.Offset.TotalSeconds -ne 0) {
        Fail-Pilot "completionProof savedAt must be a UTC timestamp"
    }

    return [ordered]@{
        schemaVersion = $proof.schemaVersion
        savedAt = $proof.savedAt
        serverId = $proof.serverId
        runId = $proof.runId
        resultId = $proof.resultId
        workflowRevisionId = $proof.workflowRevisionId
        packageExportId = $proof.packageExportId
        packageEvidenceId = $proof.packageEvidenceId
        resultPackageSha256 = $proof.resultPackageSha256
        resultPackageManifestSha256 = $proof.resultPackageManifestSha256
        validationCardGeneratedAt = $proof.validationCardGeneratedAt
        validationCardJsonSha256 = $proof.validationCardJsonSha256
        validationChecksPassed = $proof.validationChecksPassed
        validationChecksTotal = $proof.validationChecksTotal
        evidenceBundleId = $proof.evidenceBundleId
        evidenceBundleFileRoles = @($proof.evidenceBundleFileRoles)
    }
}
