param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$ApiLauncher,
    [Parameter(Mandatory = $true)]
    [string]$WebLauncher
)

$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$apiLauncherPath = (Resolve-Path -LiteralPath $ApiLauncher).Path
$webLauncherPath = (Resolve-Path -LiteralPath $WebLauncher).Path

function Repair-ProcessPathEnvironment {
    $variables = [Environment]::GetEnvironmentVariables("Process")
    $pathKeys = @()
    $pathValue = ""

    foreach ($key in $variables.Keys) {
        $name = [string]$key
        if (-not [string]::Equals($name, "Path", [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $pathKeys += $name
        if (-not $pathValue) {
            $pathValue = [string]$variables[$key]
        }
    }

    foreach ($key in $pathKeys) {
        [Environment]::SetEnvironmentVariable($key, $null, "Process")
    }
    if ($pathValue) {
        [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
    }
}

Repair-ProcessPathEnvironment

$env:H2OMETA_WORKDIR = $resolvedRoot

$apiOut = Join-Path $resolvedRoot ".h2ometa-api.out.log"
$apiErr = Join-Path $resolvedRoot ".h2ometa-api.err.log"
$webOut = Join-Path $resolvedRoot ".h2ometa-web.out.log"
$webErr = Join-Path $resolvedRoot ".h2ometa-web.err.log"
Remove-Item $apiOut, $apiErr, $webOut, $webErr -Force -ErrorAction SilentlyContinue

$apiProcess = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/c", "`"$apiLauncherPath`"") `
    -WorkingDirectory $resolvedRoot `
    -RedirectStandardOutput $apiOut `
    -RedirectStandardError $apiErr `
    -WindowStyle Hidden `
    -PassThru

$webProcess = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/c", "`"$webLauncherPath`"") `
    -WorkingDirectory $resolvedRoot `
    -RedirectStandardOutput $webOut `
    -RedirectStandardError $webErr `
    -WindowStyle Hidden `
    -PassThru

Write-Host ("[INFO] Hidden API PID {0}. Logs: {1}, {2}" -f $apiProcess.Id, $apiOut, $apiErr)
Write-Host ("[INFO] Hidden Web PID {0}. Logs: {1}, {2}" -f $webProcess.Id, $webOut, $webErr)
