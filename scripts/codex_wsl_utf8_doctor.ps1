param(
    [switch]$FixCurrentSession
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CodePage {
    $line = (cmd /c chcp) 2>$null | Select-Object -First 1
    if (-not $line) {
        return "unknown"
    }
    return ($line -replace "[^\d]", "")
}

function Get-EncodingSnapshot {
    function Read-Env([string]$name) {
        $v = [Environment]::GetEnvironmentVariable($name, "Process")
        if ($null -eq $v) {
            return ""
        }
        return $v
    }

    $consoleIn = [Console]::InputEncoding.WebName
    $consoleOut = [Console]::OutputEncoding.WebName
    $outputEncoding = if ($null -ne $OutputEncoding) { $OutputEncoding.WebName } else { "null" }
    return [ordered]@{
        code_page = Get-CodePage
        console_input = $consoleIn
        console_output = $consoleOut
        powershell_output = $outputEncoding
        WSL_UTF8 = (Read-Env "WSL_UTF8")
        PYTHONUTF8 = (Read-Env "PYTHONUTF8")
        PYTHONIOENCODING = (Read-Env "PYTHONIOENCODING")
        LANG = (Read-Env "LANG")
        LC_ALL = (Read-Env "LC_ALL")
    }
}

function Test-WslChannel {
    $statusOutput = ""
    $statusCode = 0
    try {
        $statusOutput = (& wsl --status 2>&1 | Out-String).Trim()
        $statusCode = $LASTEXITCODE
    } catch {
        $statusOutput = $_.Exception.Message
        $statusCode = 1
    }
    $statusOutput = $statusOutput -replace "`0", ""

    $probeOutput = ""
    $probeCode = 0
    $probeCmd = 'printf "UTF8_PROBE_HEX=\xE4\xB8\xAD\xE6\x96\x87\n"; locale 2>/dev/null | grep -E "^(LANG|LC_ALL)=" || true'
    try {
        $probeOutput = (& wsl -e bash -lc $probeCmd 2>&1 | Out-String).Trim()
        $probeCode = $LASTEXITCODE
    } catch {
        $probeOutput = $_.Exception.Message
        $probeCode = 1
    }
    $probeOutput = $probeOutput -replace "`0", ""

    return [ordered]@{
        wsl_status_exit = $statusCode
        wsl_status_output = $statusOutput
        wsl_probe_exit = $probeCode
        wsl_probe_output = $probeOutput
    }
}

function Apply-FixCurrentSession {
    cmd /c chcp 65001 > $null
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $script:OutputEncoding = [System.Text.UTF8Encoding]::new($false)

    $env:WSL_UTF8 = "1"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:LANG = "C.UTF-8"
    $env:LC_ALL = "C.UTF-8"
}

function Print-Section([string]$title, [hashtable]$data) {
    Write-Host ""
    Write-Host "=== $title ==="
    foreach ($k in $data.Keys) {
        Write-Host ("{0}: {1}" -f $k, $data[$k])
    }
}

$before = Get-EncodingSnapshot
$wslBefore = Test-WslChannel

if ($FixCurrentSession) {
    Apply-FixCurrentSession
}

$after = Get-EncodingSnapshot
$wslAfter = Test-WslChannel

Print-Section -title "Before" -data $before
Print-Section -title "Before WSL" -data $wslBefore
Print-Section -title "After" -data $after
Print-Section -title "After WSL" -data $wslAfter

Write-Host ""
Write-Host "Recommendation:"
Write-Host "1) Keep UTF-8 session defaults in your PowerShell profile."
Write-Host "2) Add WSL_UTF8=1 to Codex shell environment policy."
Write-Host "3) If WSL still returns E_ACCESSDENIED, fix WSL service/permission first."
