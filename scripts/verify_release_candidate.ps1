param(
    [string]$EvidenceRoot = "release-evidence",
    [string]$CiRunUrl = "",
    [switch]$AllowDirty,
    [switch]$DevelopmentOnly,
    [switch]$RunNpmCi,
    [switch]$RunLocalWebSmoke,
    [switch]$StartLocalWeb,
    [switch]$UseUserAppStateForLocalWeb,
    [switch]$RunWebE2E,
    [ValidateRange(1, 10)]
    [int]$WebE2ERepeat = 1,
    [string]$ApiBase = $(if ($env:H2OMETA_API_BASE) { $env:H2OMETA_API_BASE } else { "http://127.0.0.1:8765" }),
    [string]$WebBase = $(if ($env:H2OMETA_WEB_BASE) { $env:H2OMETA_WEB_BASE } else { "http://127.0.0.1:3765" }),
    [string]$DesktopStartupEvidence = "",
    [string]$ReleaseGateEvidence = "",
    [switch]$RequireReleaseGateEvidence,
    [switch]$RequireRuntimeManifestArtifacts,
    [switch]$RequireRuntimeSupplyChain,
    [string]$ReleaseTag = "", [string]$SecurityAnalysisRunUrl = "", [string]$SecurityAnalysisUnavailableReason = ""
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Invoke-Native {
    param(
        [string]$File,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )
    Push-Location -LiteralPath $WorkingDirectory
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $File @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                $_.ToString()
            } else {
                $_
            }
        }
        $exitCode = $LASTEXITCODE
        if ($null -ne $exitCode -and $exitCode -ne 0) {
            throw "$File exited with code $exitCode"
        }
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
}

function Invoke-NativeWithRetry {
    param(
        [string]$File,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Invoke-Native $File $Arguments $WorkingDirectory
            return
        } catch {
            if ($attempt -ge $Attempts) {
                throw
            }
            Write-Host "$File attempt $attempt/$Attempts failed: $($_.Exception.Message)"
            Start-Sleep -Seconds (5 * $attempt)
        }
    }
}

function Restore-EnvironmentValue {
    param(
        [string]$Name,
        [bool]$Exists,
        [string]$Value
    )
    if ($Exists) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    } else {
        [Environment]::SetEnvironmentVariable($Name, $null, "Process")
    }
}

function Invoke-WithWebEnvironment {
    param(
        [string]$ApiBase,
        [string]$WebBase,
        [scriptblock]$Body
    )

    $names = @("H2OMETA_API_BASE", "H2OMETA_WEB_BASE", "E2E_API_BASE", "E2E_WEB_BASE")
    $previous = @{}
    foreach ($name in $names) {
        $previous[$name] = [ordered]@{
            exists = Test-Path -LiteralPath "Env:\$name"
            value = [Environment]::GetEnvironmentVariable($name, "Process")
        }
    }

    try {
        $env:H2OMETA_API_BASE = $ApiBase
        $env:H2OMETA_WEB_BASE = $WebBase
        $env:E2E_API_BASE = $ApiBase
        $env:E2E_WEB_BASE = $WebBase
        & $Body
    } finally {
        foreach ($name in $names) {
            Restore-EnvironmentValue -Name $name -Exists $previous[$name].exists -Value $previous[$name].value
        }
    }
}

function Invoke-WithLocalWebAppState {
    param(
        [bool]$UseUserAppState,
        [string]$OriginalAppData,
        [string]$OriginalLocalAppData,
        [scriptblock]$Body
    )

    if (-not $UseUserAppState) {
        & $Body
        return
    }

    $hadAppData = Test-Path -LiteralPath "Env:\APPDATA"
    $hadLocalAppData = Test-Path -LiteralPath "Env:\LOCALAPPDATA"
    $currentAppData = [Environment]::GetEnvironmentVariable("APPDATA", "Process")
    $currentLocalAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA", "Process")
    try {
        if ($OriginalAppData) {
            $env:APPDATA = $OriginalAppData
        }
        if ($OriginalLocalAppData) {
            $env:LOCALAPPDATA = $OriginalLocalAppData
        }
        & $Body
    } finally {
        Restore-EnvironmentValue -Name "APPDATA" -Exists $hadAppData -Value $currentAppData
        Restore-EnvironmentValue -Name "LOCALAPPDATA" -Exists $hadLocalAppData -Value $currentLocalAppData
    }
}

function Invoke-HeadlessLocalWebLaunch {
    param([string]$RepoRoot)

    $launcher = Join-Path $RepoRoot "run.bat"
    $launcherOut = Join-Path ([System.IO.Path]::GetTempPath()) "h2ometa-run-bat-$PID-$([guid]::NewGuid()).out.log"
    $launcherErr = Join-Path ([System.IO.Path]::GetTempPath()) "h2ometa-run-bat-$PID-$([guid]::NewGuid()).err.log"
    $hadHeadlessFlag = Test-Path -LiteralPath "Env:\H2OMETA_HEADLESS_LAUNCH"
    $previousHeadlessFlag = [Environment]::GetEnvironmentVariable("H2OMETA_HEADLESS_LAUNCH", "Process")
    try {
        $env:H2OMETA_HEADLESS_LAUNCH = "1"
        $process = Start-Process `
            -FilePath "cmd.exe" `
            -ArgumentList @("/c", "`"$launcher`" --web") `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $launcherOut `
            -RedirectStandardError $launcherErr `
            -WindowStyle Hidden `
            -PassThru
        if (-not $process.WaitForExit(120000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "run.bat --web did not exit within 120 seconds"
        }
        $process.Refresh()
        if (Test-Path -LiteralPath $launcherOut) {
            Get-Content -LiteralPath $launcherOut | ForEach-Object { Write-Host $_ }
        }
        if (Test-Path -LiteralPath $launcherErr) {
            Get-Content -LiteralPath $launcherErr | ForEach-Object { Write-Host $_ }
        }
        $exitCode = if ($null -eq $process.ExitCode) { 0 } else { [int]$process.ExitCode }
        if ($exitCode -ne 0) {
            throw "$launcher exited with code $exitCode"
        }
    } finally {
        Restore-EnvironmentValue -Name "H2OMETA_HEADLESS_LAUNCH" -Exists $hadHeadlessFlag -Value $previousHeadlessFlag
        Remove-Item -LiteralPath $launcherOut, $launcherErr -Force -ErrorAction SilentlyContinue
    }
}

function Wait-LocalWebStack {
    param(
        [string]$ApiBase,
        [string]$WebBase,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = ""
    do {
        try {
            $health = Invoke-RestMethod -Uri "$ApiBase/health" -TimeoutSec 5
            if ($health.status -ne "ok") {
                throw "API health status was $($health.status)"
            }
            $serviceInfo = Invoke-RestMethod -Uri "$ApiBase/api/v1/service-info" -TimeoutSec 5
            if ($serviceInfo.item.readiness.status -ne "ready") {
                throw "API readiness status was $($serviceInfo.item.readiness.status)"
            }
            $page = Invoke-WebRequest -Uri $WebBase -UseBasicParsing -TimeoutSec 5
            if ($page.StatusCode -ne 200) {
                throw "Web root returned HTTP $($page.StatusCode)"
            }
            Write-Host "apiBase=$ApiBase"
            Write-Host "webBase=$WebBase"
            Write-Host "apiHealthStatus=$($health.status)"
            Write-Host "apiReadinessStatus=$($serviceInfo.item.readiness.status)"
            Write-Host "webStatusCode=$($page.StatusCode)"
            return
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "local web stack did not become ready within $TimeoutSeconds seconds: $lastError"
}

function Stop-LocalWebStack {
    param(
        [int[]]$Ports,
        [string]$RepoRoot = ""
    )

    $processIds = @()
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        Write-Host "Get-NetTCPConnection is unavailable; local web stack cleanup skipped"
    } else {
        foreach ($port in $Ports) {
            $connections = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
            foreach ($connection in $connections) {
                if ($connection.OwningProcess -gt 0) {
                    $processIds += [int]$connection.OwningProcess
                }
            }
        }
    }

    if ($RepoRoot -and (Get-Command Get-CimInstance -ErrorAction SilentlyContinue)) {
        $processes = @(Get-CimInstance Win32_Process | Where-Object {
            $commandLine = [string]$_.CommandLine
            $commandLine -and
                $commandLine.Contains($RepoRoot) -and
                (
                    $commandLine.Contains("scripts\run-local-api-dev.bat") -or
                    $commandLine.Contains("scripts\run-web-dev.bat") -or
                    $commandLine.Contains("apps.api.run") -or
                    $commandLine.Contains("next dev")
                )
        })
        foreach ($process in $processes) {
            if ($process.ProcessId -gt 0) {
                $processIds += [int]$process.ProcessId
            }
        }
    }

    foreach ($processId in ($processIds | Select-Object -Unique)) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "stopped local web stack process $processId"
        } catch {
            Write-Host "failed to stop process ${processId}: $($_.Exception.Message)"
        }
    }
}

function Save-LocalWebStackLogs {
    param(
        [string]$RepoRoot,
        [string]$EvidenceDir
    )

    $logNames = @(
        ".h2ometa-api.out.log",
        ".h2ometa-api.err.log",
        ".h2ometa-web.out.log",
        ".h2ometa-web.err.log"
    )
    foreach ($logName in $logNames) {
        $source = Join-Path $RepoRoot $logName
        if (-not (Test-Path -LiteralPath $source)) {
            continue
        }
        $cleanName = $logName.TrimStart([char]'.')
        $destination = Join-Path $EvidenceDir "local-web-stack-$cleanName"
        $saved = $false
        for ($attempt = 1; $attempt -le 5; $attempt++) {
            try {
                Copy-Item -LiteralPath $source -Destination $destination -Force
                Remove-Item -LiteralPath $source -Force
                Write-Host "saved local web stack log $destination"
                $saved = $true
                break
            } catch {
                if ($attempt -lt 5) {
                    Start-Sleep -Seconds 1
                    continue
                }
                Write-Host "failed to save local web stack log ${source}: $($_.Exception.Message)"
            }
        }
        if (-not $saved -and -not (Test-Path -LiteralPath $source)) {
            Write-Host "local web stack log disappeared before save: $source"
        }
    }
}

function New-StepName {
    param([string]$Name)
    return ($Name -replace "[^A-Za-z0-9_.-]", "_")
}

function Add-StepResult {
    param(
        [System.Collections.Generic.List[object]]$Steps,
        [string]$Name,
        [string]$Status,
        [bool]$Required,
        [string]$LogPath,
        [double]$DurationSeconds,
        [string]$Message = ""
    )
    $Steps.Add([ordered]@{
        name = $Name
        status = $Status
        required = $Required
        logPath = $LogPath
        durationSeconds = [math]::Round($DurationSeconds, 3)
        message = $Message
    }) | Out-Null
}

function Invoke-RcStep {
    param(
        [System.Collections.Generic.List[object]]$Steps,
        [string]$Name,
        [bool]$Required,
        [string]$EvidenceDir,
        [scriptblock]$Body
    )
    $safeName = New-StepName $Name
    $logPath = Join-Path $EvidenceDir "$safeName.log"
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $status = "passed"
    $message = ""
    try {
        Write-Host "[rc] $Name"
        & $Body *>&1 | Out-File -FilePath $logPath -Encoding utf8
    } catch {
        $status = "failed"
        $message = $_.Exception.Message
        "ERROR: $message" | Out-File -FilePath $logPath -Append -Encoding utf8
    } finally {
        $timer.Stop()
        Add-StepResult -Steps $Steps -Name $Name -Status $status -Required $Required -LogPath $logPath -DurationSeconds $timer.Elapsed.TotalSeconds -Message $message
    }
    if ($Required -and $status -ne "passed") {
        throw "RC_STEP_FAILED: $Name :: $message"
    }
}

function Add-SkippedStep {
    param(
        [System.Collections.Generic.List[object]]$Steps,
        [string]$Name,
        [bool]$Required,
        [string]$Message
    )
    $status = if ($Required) { "failed" } else { "skipped" }
    Add-StepResult -Steps $Steps -Name $Name -Status $status -Required $Required -LogPath "" -DurationSeconds 0 -Message $Message
    if ($Required) {
        throw "RC_STEP_FAILED: $Name :: $Message"
    }
}

function Get-RuntimeManifestSourceCommits {
    param([object]$Manifest)

    $commits = New-Object System.Collections.Generic.List[string]
    foreach ($artifactKey in @("remote_runner", "workflow_runtime")) {
        $artifact = $Manifest.artifacts.$artifactKey
        if (-not $artifact -or -not $artifact.source_commits) {
            continue
        }
        foreach ($property in $artifact.source_commits.PSObject.Properties) {
            $value = [string]$property.Value
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $commits.Add($value.Trim()) | Out-Null
            }
        }
    }
    return @($commits | Select-Object -Unique)
}

function Get-RuntimeManifestDrift {
    param(
        [string]$RepoRoot,
        [string]$HeadCommit
    )

    $manifestRelativePath = "config/remote-runner-release-manifest.json"
    $manifestPath = Join-Path $RepoRoot $manifestRelativePath
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $releaseScopePaths = @(
        "apps/remote_runner",
        "core/__init__.py",
        "core/async_boundary.py",
        "core/api_payloads.py",
        "core/api_responses.py",
        "core/logging_config.py",
        "core/problem_responses.py",
        "core/problem_status.py",
        "core/contracts",
        "config/remote-runner-conda-specs",
        "config/remote-runner-release-manifest.json",
        "scripts/build_release_artifacts_in_ci.py",
        "scripts/build_remote_runner_artifact_on_server.py",
        "scripts/build_workflow_runtime_artifact_on_server.py",
        "scripts/check_remote_runner_release_artifacts.py",
        "scripts/check_remote_runner_release_readiness.py",
        "scripts/promote_remote_runner_release.py",
        "scripts/update_remote_runner_release_manifest.py",
        ".github/workflows/release-remote-runner-artifacts.yml"
    )
    $sourceCommits = @(Get-RuntimeManifestSourceCommits -Manifest $manifest)
    $changedCommits = New-Object System.Collections.Generic.List[string]
    $missingCommits = New-Object System.Collections.Generic.List[string]

    foreach ($sourceCommit in $sourceCommits) {
        & git -C $RepoRoot cat-file -e "$sourceCommit^{commit}" *> $null
        if ($LASTEXITCODE -ne 0) {
            $missingCommits.Add($sourceCommit) | Out-Null
            continue
        }
        & git -C $RepoRoot diff --quiet $sourceCommit $HeadCommit -- @releaseScopePaths *> $null
        $diffExitCode = $LASTEXITCODE
        if ($diffExitCode -eq 1) {
            $changedCommits.Add($sourceCommit) | Out-Null
        } elseif ($diffExitCode -ne 0) {
            throw "runtime manifest drift check failed for $sourceCommit"
        }
    }

    $hasMissing = $missingCommits.Count -gt 0
    $hasChanged = $changedCommits.Count -gt 0
    $hasNoSourceCommit = $sourceCommits.Count -eq 0
    $hasDrift = $hasNoSourceCommit -or $hasMissing -or $hasChanged
    $message = if ($hasNoSourceCommit) {
        "runtime manifest has no source commits"
    } elseif ($hasMissing) {
        "runtime manifest source commit is missing from this checkout"
    } elseif ($hasChanged) {
        "release-scoped sources changed after the runtime manifest source commit"
    } else {
        "runtime manifest source commits match release-scoped sources"
    }

    return [ordered]@{
        hasDrift = $hasDrift
        message = $message
        manifestPath = $manifestRelativePath
        sourceCommits = @($sourceCommits)
        changedSourceCommits = @($changedCommits)
        missingSourceCommits = @($missingCommits)
        releaseScopePaths = $releaseScopePaths
    }
}

function Write-RcSummary {
    param(
        [string]$EvidenceDir,
        [object]$Summary
    )
    $jsonPath = Join-Path $EvidenceDir "release-candidate-summary.json"
    $markdownPath = Join-Path $EvidenceDir "release-candidate-summary.md"
    $Summary | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath -Encoding utf8

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Release Candidate Summary") | Out-Null
    $lines.Add("") | Out-Null
    $lines.Add("- Schema: $($Summary.schemaVersion)") | Out-Null
    $lines.Add("- OK: $($Summary.ok)") | Out-Null
    $lines.Add("- Commit: $($Summary.sourceCommit)") | Out-Null
    $lines.Add("- Branch: $($Summary.sourceBranch)") | Out-Null
    if ($Summary.ciRunUrl) {
        $lines.Add("- CI: $($Summary.ciRunUrl)") | Out-Null
    }
    $lines.Add("") | Out-Null
    $lines.Add("## Gates") | Out-Null
    foreach ($step in $Summary.steps) {
        $lines.Add("- $($step.status): $($step.name) $($step.message)") | Out-Null
    }
    $lines.Add("") | Out-Null
    $lines.Add("## Scoped Limits") | Out-Null
    foreach ($limit in $Summary.scopedRuntimeLimits) {
        $lines.Add("- $limit") | Out-Null
    }
    $lines | Set-Content -Path $markdownPath -Encoding utf8
}

$repoRoot = Resolve-RepoRoot
$commit = (& git -C $repoRoot rev-parse HEAD).Trim()
$branch = (& git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
$evidenceDir = Join-Path (Join-Path $repoRoot $EvidenceRoot) $commit
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$originalAppData = $env:APPDATA
$originalLocalAppData = $env:LOCALAPPDATA
$runStateRoot = Join-Path ([System.IO.Path]::GetTempPath()) "h2ometa-rc-$commit"
if (Test-Path -LiteralPath $runStateRoot) {
    Remove-Item -LiteralPath $runStateRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $runStateRoot | Out-Null

$env:UV_CACHE_DIR = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { Join-Path $repoRoot ".uv-cache-local" }
Remove-Item Env:\UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT = if ($env:H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT) { $env:H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT } else { Join-Path $repoRoot ".venv-win" }
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot ".codex-uv-python"
$env:APPDATA = Join-Path $runStateRoot "AppData\Roaming"
$env:LOCALAPPDATA = Join-Path $runStateRoot "AppData\Local"
$env:H2OMETA_DEV_CACHE_ROOT = if ($env:H2OMETA_DEV_CACHE_ROOT) {
    $env:H2OMETA_DEV_CACHE_ROOT
} elseif ($originalLocalAppData) {
    Join-Path $originalLocalAppData "H2OMeta\dev-cache"
} else {
    Join-Path $runStateRoot "dev-cache"
}
New-Item -ItemType Directory -Force -Path $env:APPDATA, $env:LOCALAPPDATA | Out-Null

$steps = New-Object System.Collections.Generic.List[object]
$ok = $true
$failure = ""
$runtimeManifestDrift = [ordered]@{
    hasDrift = $false
    message = "runtime manifest drift check did not run"
    manifestPath = "config/remote-runner-release-manifest.json"
    sourceCommits = @()
    changedSourceCommits = @()
    missingSourceCommits = @()
    releaseScopePaths = @()
}
$runtimeGateRequested = ($RequireReleaseGateEvidence.IsPresent -or $RequireRuntimeManifestArtifacts.IsPresent -or $RequireRuntimeSupplyChain.IsPresent -or [bool]$ReleaseTag)
$runtimeGateRequired = $runtimeGateRequested
$runtimeManifestArtifactsRequired = $RequireRuntimeManifestArtifacts.IsPresent
$runtimeSupplyChainRequired = $RequireRuntimeSupplyChain.IsPresent
$SecurityAnalysisRunUrl = $SecurityAnalysisRunUrl.Trim()
$SecurityAnalysisUnavailableReason = $SecurityAnalysisUnavailableReason.Trim()
$securityAnalysisEvidenceRecorded = $false
$securityAnalysisEvidenceMode = "missing"
$startedLocalWebStack = $false

try {
    Invoke-RcStep -Steps $steps -Name "git-clean-worktree" -Required $true -EvidenceDir $evidenceDir -Body {
        $status = (& git -C $repoRoot status --porcelain=v1)
        if ($status -and -not $AllowDirty) {
            $status | ForEach-Object { Write-Host $_ }
            throw "working tree is dirty; commit or pass -AllowDirty for development proof"
        }
        Write-Host "sourceCommit=$commit"
        Write-Host "sourceBranch=$branch"
        Write-Host "allowDirty=$($AllowDirty.IsPresent)"
    }

    $runtimeManifestDrift = Get-RuntimeManifestDrift -RepoRoot $repoRoot -HeadCommit $commit
    if ($runtimeManifestDrift.hasDrift -and -not $DevelopmentOnly.IsPresent) {
        $runtimeGateRequired = $true
        $runtimeManifestArtifactsRequired = $true
        $runtimeSupplyChainRequired = $true
    }
    Invoke-RcStep -Steps $steps -Name "runtime-manifest-drift" -Required $false -EvidenceDir $evidenceDir -Body {
        Write-Host "hasDrift=$($runtimeManifestDrift.hasDrift)"
        Write-Host "message=$($runtimeManifestDrift.message)"
        Write-Host "manifestPath=$($runtimeManifestDrift.manifestPath)"
        Write-Host "sourceCommits=$($runtimeManifestDrift.sourceCommits -join ',')"
        Write-Host "changedSourceCommits=$($runtimeManifestDrift.changedSourceCommits -join ',')"
        Write-Host "missingSourceCommits=$($runtimeManifestDrift.missingSourceCommits -join ',')"
        if ($runtimeManifestDrift.hasDrift -and -not $DevelopmentOnly.IsPresent) {
            Write-Host "runtime release evidence, manifest artifacts, and supply chain checks are required for production handoff"
        }
    }

    if ($CiRunUrl) {
        Invoke-RcStep -Steps $steps -Name "ci-proof" -Required $true -EvidenceDir $evidenceDir -Body {
            if ($CiRunUrl -notmatch "^https://github\.com/.+/actions/runs/\d+") {
                throw "CiRunUrl must point to a GitHub Actions run URL"
            }
            Write-Host "ciRunUrl=$CiRunUrl"
            Write-Host "requiredCheck=required / ci-green"
            Write-Host "sourceCommit=$commit"
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "ci-proof" -Required (-not $DevelopmentOnly.IsPresent) -Message "production handoff requires -CiRunUrl for green required / ci-green evidence"
    }

    if ($SecurityAnalysisRunUrl -and $SecurityAnalysisUnavailableReason) {
        Invoke-RcStep -Steps $steps -Name "security-analysis-platform-evidence" -Required $true -EvidenceDir $evidenceDir -Body { throw "SecurityAnalysisRunUrl and SecurityAnalysisUnavailableReason are mutually exclusive" }
    } elseif ($SecurityAnalysisRunUrl -and $SecurityAnalysisRunUrl -notmatch "^https://github\.com/.+/actions/runs/\d+") {
        Invoke-RcStep -Steps $steps -Name "security-analysis-platform-evidence" -Required $true -EvidenceDir $evidenceDir -Body { throw "SecurityAnalysisRunUrl must point to a GitHub Actions run URL" }
    } elseif ($SecurityAnalysisRunUrl) {
        $securityAnalysisEvidenceRecorded = $true
        $securityAnalysisEvidenceMode = "green"
        Invoke-RcStep -Steps $steps -Name "security-analysis-platform-evidence" -Required $true -EvidenceDir $evidenceDir -Body {
            Write-Host "securityAnalysisRunUrl=$SecurityAnalysisRunUrl"
            Write-Host "workflow=Security Analysis"
            Write-Host "expectedJobs=security / codeql (python); security / codeql (javascript-typescript); security / scorecard"
            Write-Host "sourceCommit=$commit"
        }
    } elseif ($SecurityAnalysisUnavailableReason) {
        $securityAnalysisEvidenceRecorded = $true
        $securityAnalysisEvidenceMode = "unavailable"
        $message = "Security Analysis unavailable platform gate recorded: $SecurityAnalysisUnavailableReason"
        Add-StepResult -Steps $steps -Name "security-analysis-platform-evidence" -Status "unavailable" -Required $false -LogPath "" -DurationSeconds 0 -Message $message
    } else {
        Add-SkippedStep -Steps $steps -Name "security-analysis-platform-evidence" -Required $false -Message "production handoff requires -SecurityAnalysisRunUrl or -SecurityAnalysisUnavailableReason; handoffEligible will be false"
    }

    Invoke-RcStep -Steps $steps -Name "python-quality" -Required $true -EvidenceDir $evidenceDir -Body {
        Invoke-Native "uv" @("run", "--frozen", "ruff", "check", "apps", "core", "scripts", "tests") $repoRoot
        Invoke-Native "uv" @("run", "--frozen", "python", "-m", "pytest", "-q") $repoRoot
    }

    if ($RunNpmCi) {
        Invoke-RcStep -Steps $steps -Name "clean-install-proof" -Required $true -EvidenceDir $evidenceDir -Body {
            Invoke-Native "npm" @("ci") (Join-Path $repoRoot "apps\web")
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "clean-install-proof" -Required (-not $DevelopmentOnly.IsPresent) -Message "production handoff requires -RunNpmCi to prove lockfile installability"
    }

    Invoke-RcStep -Steps $steps -Name "web-quality" -Required $true -EvidenceDir $evidenceDir -Body {
        $webRoot = Join-Path $repoRoot "apps\web"
        Invoke-Native "npm" @("run", "lint") $webRoot
        Invoke-Native "npm" @("run", "typecheck") $webRoot
        Invoke-Native "npm" @("run", "build") $webRoot
    }

    Invoke-RcStep -Steps $steps -Name "security-audit" -Required $true -EvidenceDir $evidenceDir -Body {
        Invoke-Native "uv" @("run", "--frozen", "python", "scripts\security_governance_audit.py") $repoRoot
        Invoke-NativeWithRetry "npm" @("audit", "--registry=https://registry.npmjs.org", "--audit-level=moderate", "--package-lock-only") $repoRoot
        Invoke-NativeWithRetry "npm" @("audit", "--registry=https://registry.npmjs.org", "--audit-level=moderate", "--package-lock-only") (Join-Path $repoRoot "apps\web")
        Invoke-NativeWithRetry "npm" @("audit", "--registry=https://registry.npmjs.org", "--audit-level=moderate", "--package-lock-only") (Join-Path $repoRoot "apps\desktop")
        $requirements = Join-Path $evidenceDir "requirements-audit.txt"
        Invoke-Native "uv" @("export", "--frozen", "--group", "dev", "--format", "requirements-txt", "--no-emit-project", "--output-file", $requirements) $repoRoot
        Invoke-NativeWithRetry "uvx" @("pip-audit", "-r", $requirements, "--progress-spinner", "off", "--strict", "--ignore-vuln", "CVE-2026-44405") $repoRoot
    }

    Invoke-RcStep -Steps $steps -Name "database-lifecycle-contracts" -Required $true -EvidenceDir $evidenceDir -Body {
        Invoke-Native "uv" @(
            "run", "--frozen", "python", "-m", "pytest", "-q",
            "tests/test_reference_database_pack_lifecycle_docs.py",
            "tests/test_reference_database_pack_catalog.py",
            "tests/test_reference_database_registry_templates.py",
            "tests/test_tool_contract_production_evidence.py"
        ) $repoRoot
    }

    if ($StartLocalWeb) {
        $startedLocalWebStack = $true
        Invoke-RcStep -Steps $steps -Name "local-web-launcher" -Required $true -EvidenceDir $evidenceDir -Body {
            Invoke-WithLocalWebAppState -UseUserAppState $UseUserAppStateForLocalWeb.IsPresent -OriginalAppData $originalAppData -OriginalLocalAppData $originalLocalAppData -Body {
                Invoke-HeadlessLocalWebLaunch -RepoRoot $repoRoot
                Wait-LocalWebStack -ApiBase $ApiBase -WebBase $WebBase
            }
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "local-web-launcher" -Required $false -Message "pass -StartLocalWeb to launch run.bat --web headlessly"
    }

    if ($RunLocalWebSmoke -or $StartLocalWeb) {
        Invoke-RcStep -Steps $steps -Name "local-web-smoke" -Required $true -EvidenceDir $evidenceDir -Body {
            Invoke-WithLocalWebAppState -UseUserAppState $UseUserAppStateForLocalWeb.IsPresent -OriginalAppData $originalAppData -OriginalLocalAppData $originalLocalAppData -Body {
                Invoke-WithWebEnvironment -ApiBase $ApiBase -WebBase $WebBase -Body {
                    Invoke-Native "powershell" @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $repoRoot "scripts\local_web_smoke.ps1")) $repoRoot
                }
            }
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "local-web-smoke" -Required $false -Message "pass -RunLocalWebSmoke after starting run.bat --web"
    }

    if ($RunWebE2E) {
        Invoke-RcStep -Steps $steps -Name "web-e2e" -Required $true -EvidenceDir $evidenceDir -Body {
            Invoke-WithLocalWebAppState -UseUserAppState $UseUserAppStateForLocalWeb.IsPresent -OriginalAppData $originalAppData -OriginalLocalAppData $originalLocalAppData -Body {
                Invoke-WithWebEnvironment -ApiBase $ApiBase -WebBase $WebBase -Body {
                    for ($iteration = 1; $iteration -le $WebE2ERepeat; $iteration++) {
                        Write-Host "webE2EIteration=$iteration/$WebE2ERepeat"
                        Invoke-Native "npm" @("run", "test:e2e") $repoRoot
                    }
                }
            }
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "web-e2e" -Required $false -Message "pass -RunWebE2E to execute Playwright; use -WebE2ERepeat 3 for flaky-test burn-in"
    }

    if ($DesktopStartupEvidence) {
        Invoke-RcStep -Steps $steps -Name "desktop-startup-evidence" -Required $false -EvidenceDir $evidenceDir -Body {
            Write-Host "desktopStartupEvidence=$DesktopStartupEvidence"
            Write-Host "operator must start run.bat --desktop from a real Windows shell before recording this evidence"
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "desktop-startup-evidence" -Required $false -Message "pass -DesktopStartupEvidence after starting run.bat --desktop"
    }

    if ($ReleaseGateEvidence) {
        Invoke-RcStep -Steps $steps -Name "runtime-release-evidence" -Required $true -EvidenceDir $evidenceDir -Body {
            $readinessSummary = Join-Path $evidenceDir "runtime-release-readiness-summary.json"
            $readinessArgs = @(
                "run", "--frozen", "python", "scripts\check_remote_runner_release_readiness.py",
                "--release-gate-evidence", $ReleaseGateEvidence,
                "--output-json", $readinessSummary
            )
            if ($runtimeManifestArtifactsRequired) {
                $readinessArgs += "--require-manifest-artifacts"
            }
            if ($runtimeSupplyChainRequired) {
                $readinessArgs += "--require-supply-chain"
            }
            if ($ReleaseTag) {
                $readinessArgs += @("--release-tag", $ReleaseTag)
            }
            Invoke-Native "uv" $readinessArgs $repoRoot
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "runtime-release-evidence" -Required $runtimeGateRequired -Message "pass -ReleaseGateEvidence for runtime artifact production readiness"
    }
} catch {
    $ok = $false
    $failure = $_.Exception.Message
} finally {
    if ($startedLocalWebStack) {
        Stop-LocalWebStack -Ports @(8765, 3765) -RepoRoot $repoRoot
        Save-LocalWebStackLogs -RepoRoot $repoRoot -EvidenceDir $evidenceDir
    }
    if (Test-Path -LiteralPath $runStateRoot) {
        Remove-Item -LiteralPath $runStateRoot -Recurse -Force
    }
}

if ($steps | Where-Object { $_.required -and $_.status -ne "passed" }) {
    $ok = $false
}

$summary = [ordered]@{
    schemaVersion = "h2ometa-release-candidate-evidence.v1"
    ok = $ok
    sourceCommit = $commit
    sourceBranch = $branch
    generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    scriptPath = "scripts/verify_release_candidate.ps1"
    evidenceDir = $evidenceDir
    ciRunUrl = $CiRunUrl
    allowDirty = $AllowDirty.IsPresent
    developmentOnly = $DevelopmentOnly.IsPresent
    apiBase = $ApiBase
    webBase = $WebBase
    devCacheRoot = $env:H2OMETA_DEV_CACHE_ROOT
    runNpmCi = $RunNpmCi.IsPresent
    startLocalWeb = $StartLocalWeb.IsPresent
    useUserAppStateForLocalWeb = $UseUserAppStateForLocalWeb.IsPresent
    runWebE2E = $RunWebE2E.IsPresent
    webE2ERepeat = $WebE2ERepeat
    securityAnalysisEvidenceRecorded = $securityAnalysisEvidenceRecorded
    securityAnalysisEvidenceMode = $securityAnalysisEvidenceMode
    securityAnalysisRunUrl = $SecurityAnalysisRunUrl
    securityAnalysisUnavailableReason = $SecurityAnalysisUnavailableReason
    handoffEligible = ($ok -and -not $DevelopmentOnly.IsPresent -and [bool]$CiRunUrl -and $RunNpmCi.IsPresent -and $securityAnalysisEvidenceRecorded)
    localSingleUserProofEligible = ($ok -and -not $AllowDirty.IsPresent -and $StartLocalWeb.IsPresent -and $RunWebE2E.IsPresent -and (($RunLocalWebSmoke.IsPresent) -or $StartLocalWeb.IsPresent))
    runtimeManifestDrift = $runtimeManifestDrift
    steps = $steps
    scopedRuntimeLimits = @(
        "Server multi-user mode is not implemented; see docs/security-governance.md.",
        "Runtime release evidence is required when release-scoped sources drift after the runtime manifest source commit.",
        "Paramiko CVE-2026-44405 is scoped to the documented pip-audit ignore until an upstream fixed release is available."
    )
    failure = $failure
}

Write-RcSummary -EvidenceDir $evidenceDir -Summary $summary
Write-Host "RC_EVIDENCE: $evidenceDir"
Write-Host ("RC_SUMMARY: " + (Join-Path $evidenceDir "release-candidate-summary.json"))

if (-not $ok) {
    exit 1
}
