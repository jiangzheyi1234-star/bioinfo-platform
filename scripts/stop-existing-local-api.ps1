param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$listeners = @(Get-NetTCPConnection -LocalAddress $HostAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -eq 0) {
    Write-Host "[INFO] No existing API listener found."
    exit 0
}

$pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $pids) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host ("[INFO] Existing API listener PID {0}: {1}" -f $processId, $proc.CommandLine)
    } else {
        Write-Host ("[INFO] Existing API listener PID {0}" -f $processId)
    }
    Stop-Process -Id $processId -Force -ErrorAction Stop
    Write-Host ("[INFO] Stopped stale local API PID {0}." -f $processId)
}

Start-Sleep -Milliseconds 500
$remaining = @(Get-NetTCPConnection -LocalAddress $HostAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($remaining.Count -gt 0) {
    Write-Host ("[ERROR] {0}:{1} is still in use after stop attempt." -f $HostAddress, $Port)
    exit 1
}

exit 0
