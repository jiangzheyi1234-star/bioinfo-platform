@echo off
setlocal
chcp 65001 >nul
title H2OMeta Web Launcher

cd /d "%~dp0"

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "API_URL=http://127.0.0.1:8765"
set "WEB_URL=http://127.0.0.1:3765"
set "ENSURE_WEB_DEV=%REPO_ROOT%\scripts\ensure-web-dev.cjs"
set "RUN_LOCAL_API_DEV=%REPO_ROOT%\scripts\run-local-api-dev.bat"
set "RUN_WEB_DEV=%REPO_ROOT%\scripts\run-web-dev.bat"

set "APPDATA=%REPO_ROOT%\.tmp_appdata"
set "LOCALAPPDATA=%REPO_ROOT%\.tmp_localappdata"
set "UV_CACHE_DIR=%~dp0.uv-cache-local"
set "UV_PYTHON=python"
set "UV_PYTHON_INSTALL_DIR=%~dp0.codex-uv-python"
set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"
set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_BASE=%API_URL%"
set "H2OMETA_RUNTIME_BUILD_ID=terminal-websocket-v1"
set "H2OMETA_BACKEND_SOURCE=run-web.bat"
set "H2OMETA_CONDA_ENV=bio_ui"
set "H2OMETA_CONDA_EXE=C:\Users\Administrator\miniconda3\Scripts\conda.exe"

echo [INFO] Launch mode: local web dev
echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Starting API at %API_URL%
echo [INFO] Starting Web at %WEB_URL%
echo.

if not exist "%APPDATA%" mkdir "%APPDATA%" >nul 2>nul
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%" >nul 2>nul

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found in PATH.
    pause
    endlocal & exit /b 1
)

if not exist "%ENSURE_WEB_DEV%" (
    echo [ERROR] Web bootstrap script not found: %ENSURE_WEB_DEV%
    pause
    endlocal & exit /b 1
)

if not exist "%RUN_LOCAL_API_DEV%" (
    echo [ERROR] API launcher script not found: %RUN_LOCAL_API_DEV%
    pause
    endlocal & exit /b 1
)

if not exist "%RUN_WEB_DEV%" (
    echo [ERROR] Web launcher script not found: %RUN_WEB_DEV%
    pause
    endlocal & exit /b 1
)

echo [INFO] Checking Web dependencies...
node "%ENSURE_WEB_DEV%"
if errorlevel 1 (
    echo [ERROR] Web dependency bootstrap failed.
    pause
    endlocal & exit /b 1
)

ver >nul
start "H2OMeta API" cmd /k ""%RUN_LOCAL_API_DEV%""
if errorlevel 1 (
    echo [ERROR] Failed to open API terminal window.
    pause
    endlocal & exit /b 1
)

ver >nul
start "H2OMeta Web" cmd /k ""%RUN_WEB_DEV%""
if errorlevel 1 (
    echo [ERROR] Failed to open Web terminal window.
    pause
    endlocal & exit /b 1
)

echo [INFO] Waiting for Web UI to become ready...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $url='%WEB_URL%'; $ready=$false; for($i=0; $i -lt 60; $i++){ try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ $ready=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if($ready){ exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [WARN] Web UI did not respond yet. Opening browser anyway: %WEB_URL%
) else (
    echo [OK] Web UI is ready.
)

start "" "%WEB_URL%"

echo.
echo [OK] Launch commands submitted.
echo API health: %API_URL%/health
echo Web UI: %WEB_URL%
echo.
echo Close the two spawned terminal windows to stop the dev servers.
endlocal & exit /b 0
