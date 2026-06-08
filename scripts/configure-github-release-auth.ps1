param(
    [string]$HostName = "github.com",
    [string]$ConfigDir = "",
    [switch]$UseExistingGhToken,
    [switch]$Reset,
    [switch]$ValidateArtifacts
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is not set; pass -ConfigDir explicitly."
    }
    $ConfigDir = Join-Path $env:LOCALAPPDATA "H2OMeta\gh-cli"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw "GitHub CLI (gh) was not found in PATH. Install it from https://cli.github.com/ first."
}

New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$previousGhConfigDir = $env:GH_CONFIG_DIR
$env:GH_CONFIG_DIR = $ConfigDir
[Environment]::SetEnvironmentVariable("H2OMETA_GH_CONFIG_DIR", $ConfigDir, "User")
$env:H2OMETA_GH_CONFIG_DIR = $ConfigDir

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$SecureValue)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }
}

try {
    if ($Reset) {
        Write-Host "[INFO] Resetting H2OMeta GH CLI auth for $HostName in $ConfigDir"
        $hostsPath = Join-Path $ConfigDir "hosts.yml"
        if (Test-Path -LiteralPath $hostsPath) {
            Remove-Item -LiteralPath $hostsPath -Force
        }
    }

    $token = ""
    if ($UseExistingGhToken) {
        if (-not [string]::IsNullOrWhiteSpace($previousGhConfigDir)) {
            $env:GH_CONFIG_DIR = $previousGhConfigDir
        }
        else {
            Remove-Item Env:GH_CONFIG_DIR -ErrorAction SilentlyContinue
        }
        $token = (& $gh.Source auth token --hostname $HostName 2>$null).Trim()
        $env:GH_CONFIG_DIR = $ConfigDir
        if ([string]::IsNullOrWhiteSpace($token)) {
            throw "No existing gh token was available. Rerun without -UseExistingGhToken and paste a token into the secure prompt."
        }
    }
    else {
        Write-Host "Paste a GitHub token with private release asset access. Input is hidden and is not written to the repo."
        $secureToken = Read-Host "GitHub token" -AsSecureString
        $token = Convert-SecureStringToPlainText $secureToken
    }

    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "GitHub token was empty."
    }

    $token | & $gh.Source auth login --hostname $HostName --with-token
    if ($LASTEXITCODE -ne 0) {
        throw "gh auth login failed."
    }

    & $gh.Source auth status --hostname $HostName
    if ($LASTEXITCODE -ne 0) {
        throw "gh auth status failed after login."
    }

    $configuredToken = (& $gh.Source auth token --hostname $HostName).Trim()
    if ([string]::IsNullOrWhiteSpace($configuredToken)) {
        throw "gh auth token returned an empty token after login."
    }
    Write-Host "[OK] GitHub CLI auth is configured for H2OMeta."
    Write-Host "[OK] GH_CONFIG_DIR=$ConfigDir"
    Write-Host "[OK] H2OMETA_GH_CONFIG_DIR has been saved as a user environment variable."
    Write-Host "[OK] Token is readable by gh auth token. Length=$($configuredToken.Length)"

    if ($ValidateArtifacts) {
        Push-Location $repoRoot
        try {
            uv run --frozen python scripts\check_remote_runner_release_artifacts.py --cmd-env
            if ($LASTEXITCODE -ne 0) {
                throw "Release artifact validation failed."
            }
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    $env:GH_CONFIG_DIR = $ConfigDir
}
