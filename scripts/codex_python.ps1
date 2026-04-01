param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$PythonArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PythonExe = "C:\Users\Administrator\miniconda3\envs\bio_ui\python.exe"
$RepoRoot = (Get-Location).Path

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repository path not found: $RepoRoot"
}

$repoFullPath = (Resolve-Path -LiteralPath $RepoRoot).Path

$env:WSL_UTF8 = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:HOME = "C:\Users\Administrator"
$env:USERPROFILE = "C:\Users\Administrator"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonExe
$psi.WorkingDirectory = $repoFullPath
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
$psi.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)

foreach ($arg in $PythonArgs) {
    [void]$psi.ArgumentList.Add($arg)
}

$process = [System.Diagnostics.Process]::Start($psi)
if ($null -eq $process) {
    throw "Failed to start python process."
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
