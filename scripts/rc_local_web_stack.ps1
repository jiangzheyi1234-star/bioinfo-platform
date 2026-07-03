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
