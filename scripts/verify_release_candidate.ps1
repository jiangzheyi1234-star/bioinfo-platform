param(
    [string]$EvidenceRoot = "release-evidence",
    [string]$CiRunUrl = "",
    [switch]$AllowDirty,
    [switch]$DevelopmentOnly,
    [switch]$RunNpmCi,
    [switch]$RunLocalWebSmoke,
    [string]$DesktopStartupEvidence = "",
    [string]$ReleaseGateEvidence = "",
    [switch]$RequireReleaseGateEvidence,
    [switch]$RequireRuntimeManifestArtifacts,
    [switch]$RequireRuntimeSupplyChain,
    [string]$ReleaseTag = ""
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
New-Item -ItemType Directory -Force -Path $env:APPDATA, $env:LOCALAPPDATA | Out-Null

$steps = New-Object System.Collections.Generic.List[object]
$ok = $true
$failure = ""
$runtimeGateRequired = (
    $RequireReleaseGateEvidence.IsPresent -or
    $RequireRuntimeManifestArtifacts.IsPresent -or
    $RequireRuntimeSupplyChain.IsPresent -or
    [bool]$ReleaseTag
)

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
        Invoke-Native "npm" @("audit", "--registry=https://registry.npmjs.org", "--audit-level=moderate", "--package-lock-only") $repoRoot
        Invoke-Native "npm" @("audit", "--registry=https://registry.npmjs.org", "--audit-level=moderate", "--package-lock-only") (Join-Path $repoRoot "apps\web")
        $requirements = Join-Path $evidenceDir "requirements-audit.txt"
        Invoke-Native "uv" @("export", "--frozen", "--group", "dev", "--format", "requirements-txt", "--no-emit-project", "--output-file", $requirements) $repoRoot
        Invoke-Native "uvx" @("pip-audit", "-r", $requirements, "--progress-spinner", "off", "--strict", "--ignore-vuln", "CVE-2026-44405") $repoRoot
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

    if ($RunLocalWebSmoke) {
        Invoke-RcStep -Steps $steps -Name "local-web-smoke" -Required $true -EvidenceDir $evidenceDir -Body {
            Invoke-Native "powershell" @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $repoRoot "scripts\local_web_smoke.ps1")) $repoRoot
        }
    } else {
        Add-SkippedStep -Steps $steps -Name "local-web-smoke" -Required $false -Message "pass -RunLocalWebSmoke after starting run.bat --web"
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
            if ($RequireRuntimeManifestArtifacts) {
                $readinessArgs += "--require-manifest-artifacts"
            }
            if ($RequireRuntimeSupplyChain) {
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
    runNpmCi = $RunNpmCi.IsPresent
    handoffEligible = ($ok -and -not $DevelopmentOnly.IsPresent -and [bool]$CiRunUrl -and $RunNpmCi.IsPresent)
    steps = $steps
    scopedRuntimeLimits = @(
        "Server multi-user mode is not implemented; see docs/security-governance.md.",
        "Runtime release evidence is optional unless this RC claims remote-runner artifact production readiness.",
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
