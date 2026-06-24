function Invoke-PlatformWorkflowEvidence {
    param(
        [System.Collections.Generic.List[object]]$Steps,
        [string]$Name,
        [string]$RunUrl,
        [string]$UnavailableReason,
        [string]$RunUrlParameterName,
        [string]$UnavailableReasonParameterName,
        [string]$RunUrlLogKey,
        [string]$WorkflowName,
        [string]$ExpectedJobs,
        [string]$EvidenceDir,
        [string]$SourceCommit
    )
    $runUrl = $RunUrl.Trim()
    $unavailableReason = $UnavailableReason.Trim()
    $result = [ordered]@{ recorded = $false; mode = "missing"; runUrl = $runUrl; unavailableReason = $unavailableReason }
    if ($runUrl -and $unavailableReason) {
        Invoke-RcStep -Steps $Steps -Name $Name -Required $true -EvidenceDir $EvidenceDir -Body { throw "$RunUrlParameterName and $UnavailableReasonParameterName are mutually exclusive" }
    } elseif ($runUrl -and $runUrl -notmatch "^https://github\.com/.+/actions/runs/\d+") {
        Invoke-RcStep -Steps $Steps -Name $Name -Required $true -EvidenceDir $EvidenceDir -Body { throw "$RunUrlParameterName must point to a GitHub Actions run URL" }
    } elseif ($runUrl) {
        $result["recorded"] = $true
        $result["mode"] = "green"
        Invoke-RcStep -Steps $Steps -Name $Name -Required $true -EvidenceDir $EvidenceDir -Body {
            Write-Host "$RunUrlLogKey=$runUrl"
            Write-Host "workflow=$WorkflowName"
            Write-Host "expectedJobs=$ExpectedJobs"
            Write-Host "sourceCommit=$SourceCommit"
        }
    } elseif ($unavailableReason) {
        $result["recorded"] = $true
        $result["mode"] = "unavailable"
        Add-StepResult -Steps $Steps -Name $Name -Status "unavailable" -Required $false -LogPath "" -DurationSeconds 0 -Message "$WorkflowName unavailable platform gate recorded: $unavailableReason"
    } else {
        Add-SkippedStep -Steps $Steps -Name $Name -Required $false -Message "production handoff requires -$RunUrlParameterName or -$UnavailableReasonParameterName; handoffEligible will be false"
    }
    return [pscustomobject]$result
}
