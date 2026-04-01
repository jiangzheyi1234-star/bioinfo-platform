param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$env:QT_QPA_PLATFORM = "offscreen"
$env:CODEX_ASYNCIO_FALLBACK = "1"

$supportDir = Join-Path $PSScriptRoot "test_support"
$existingPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
    $env:PYTHONPATH = $supportDir
} else {
    $env:PYTHONPATH = "$supportDir;$existingPythonPath"
}

$argsToRun = @("-m", "pytest")
if ($PytestArgs) {
    $argsToRun += $PytestArgs
}

& "$PSScriptRoot\codex_python.ps1" @argsToRun
exit $LASTEXITCODE
