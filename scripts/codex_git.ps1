param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$GitArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GitExe = "C:\Program Files\Git\bin\git.exe"
$RepoRoot = (Get-Location).Path

if (-not (Test-Path -LiteralPath $GitExe)) {
    throw "Git executable not found: $GitExe"
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repository path not found: $RepoRoot"
}

$repoFullPath = (Resolve-Path -LiteralPath $RepoRoot).Path
$repoGitPath = $repoFullPath -replace "\\", "/"

$env:WSL_UTF8 = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$quotedArgs = foreach ($arg in $GitArgs) {
    if ($arg -match '[\s"]') {
        '"' + ($arg -replace '"', '\"') + '"'
    } else {
        $arg
    }
}

$allArgs = @("-c", "safe.directory=$repoGitPath") + $quotedArgs

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $GitExe
$psi.WorkingDirectory = $repoFullPath
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
$psi.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)

foreach ($arg in $allArgs) {
    [void]$psi.ArgumentList.Add($arg)
}

$process = [System.Diagnostics.Process]::Start($psi)
if ($null -eq $process) {
    throw "Failed to start git process."
}

$stdout = $process.StandardOutput.ReadToEnd()
$stderr = $process.StandardError.ReadToEnd()
$process.WaitForExit()

if ($stdout) {
    [Console]::Out.Write($stdout)
}

if ($stderr) {
    [Console]::Error.Write($stderr)
}

exit $process.ExitCode
