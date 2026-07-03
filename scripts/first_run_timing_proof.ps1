function Format-UtcIso {
    param([DateTimeOffset]$Value)
    return $Value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Convert-FirstRunTimestamp {
    param([object]$Value)
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return ""
    }
    try {
        return ([DateTimeOffset]::Parse([string]$Value)).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    } catch {
        return ""
    }
}

function Get-FirstRunDurationSeconds {
    param([string]$StartedAt, [string]$FinishedAt)
    if ([string]::IsNullOrWhiteSpace($StartedAt) -or [string]::IsNullOrWhiteSpace($FinishedAt)) {
        return $null
    }
    try {
        $start = [DateTimeOffset]::Parse($StartedAt)
        $finish = [DateTimeOffset]::Parse($FinishedAt)
        return [math]::Round(($finish - $start).TotalSeconds, 3)
    } catch {
        return $null
    }
}

function New-RunTimingProof {
    param(
        [object]$Run,
        [object]$WaitProof,
        [DateTimeOffset]$ProofStartedAt,
        [DateTimeOffset]$ProofFinishedAt,
        [int]$RunTimeoutSeconds,
        [int]$TargetMinSeconds = 900,
        [int]$MaxSeconds = 1800
    )
    $runSubmittedAt = Convert-FirstRunTimestamp $Run.submittedAt
    $runStartedAt = Convert-FirstRunTimestamp $Run.startedAt
    $runFinishedAt = Convert-FirstRunTimestamp $Run.finishedAt
    $waitStartedAt = Convert-FirstRunTimestamp $WaitProof.waitStartedAt
    $waitFinishedAt = Convert-FirstRunTimestamp $WaitProof.waitFinishedAt
    $runDurationSeconds = Get-FirstRunDurationSeconds $runSubmittedAt $runFinishedAt
    $executionDurationSeconds = Get-FirstRunDurationSeconds $runStartedAt $runFinishedAt
    $queueDurationSeconds = Get-FirstRunDurationSeconds $runSubmittedAt $runStartedAt
    $localWaitDurationSeconds = Get-FirstRunDurationSeconds $waitStartedAt $waitFinishedAt
    $proofDurationSeconds = [math]::Round(($ProofFinishedAt - $ProofStartedAt).TotalSeconds, 3)
    $observedDurationSeconds = $runDurationSeconds
    $durationSource = "runner-run-timestamps"
    if ($null -eq $observedDurationSeconds) {
        $observedDurationSeconds = $localWaitDurationSeconds
        $durationSource = "local-wait-window"
    }
    $timeoutBudgetSeconds = [math]::Min($RunTimeoutSeconds, $MaxSeconds)
    $completedWithinTimeout = ($null -ne $observedDurationSeconds -and $observedDurationSeconds -le $timeoutBudgetSeconds)
    return [ordered]@{
        schemaVersion = "h2ometa.first-run.timing-proof.v1"
        proofStartedAt = Format-UtcIso $ProofStartedAt
        proofFinishedAt = Format-UtcIso $ProofFinishedAt
        proofDurationSeconds = $proofDurationSeconds
        runSubmittedAt = $runSubmittedAt
        runStartedAt = $runStartedAt
        runFinishedAt = $runFinishedAt
        runDurationSeconds = $runDurationSeconds
        queueDurationSeconds = $queueDurationSeconds
        executionDurationSeconds = $executionDurationSeconds
        localWaitStartedAt = $waitStartedAt
        localWaitFinishedAt = $waitFinishedAt
        localWaitDurationSeconds = $localWaitDurationSeconds
        observedDurationSeconds = $observedDurationSeconds
        durationSource = $durationSource
        timeoutBudgetSeconds = $timeoutBudgetSeconds
        durationWindowSeconds = [ordered]@{
            targetMinSeconds = $TargetMinSeconds
            maxSeconds = $timeoutBudgetSeconds
            lowerBoundRequired = $false
        }
        completedWithinTimeout = $completedWithinTimeout
        withinExpectedDurationWindow = $completedWithinTimeout
        metTargetLowerBound = ($null -ne $observedDurationSeconds -and $observedDurationSeconds -ge $TargetMinSeconds)
    }
}
