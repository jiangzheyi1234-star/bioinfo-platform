@echo off
setlocal
chcp 65001 >nul
title H2OMeta Desktop Launcher

cd /d "%~dp0"

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "ENSURE_WEB_DEV=%REPO_ROOT%\scripts\ensure-web-dev.cjs"
set "ENSURE_DESKTOP_DEV=%REPO_ROOT%\scripts\ensure-desktop-dev.cjs"
set "RUN_DESKTOP_DEV=%REPO_ROOT%\scripts\run-desktop-dev.bat"

set "APPDATA=%REPO_ROOT%\.tmp_appdata"
set "LOCALAPPDATA=%REPO_ROOT%\.tmp_localappdata"
set "UV_CACHE_DIR=%REPO_ROOT%\.uv-cache-local"
set "UV_PYTHON=python"
set "UV_PYTHON_INSTALL_DIR=%REPO_ROOT%\.codex-uv-python"
set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"
set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "H2OMETA_ALLOW_REPO_BACKEND=1"
set "H2OMETA_CARGO_TARGET_DIR=%LOCALAPPDATA%\H2OMeta\dev-cache\cargo-target\bio_ui"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765"
set "H2OMETA_CONDA_ENV=bio_ui"
set "H2OMETA_CONDA_EXE=C:\Users\Administrator\miniconda3\Scripts\conda.exe"

echo [INFO] Launch mode: desktop dev
echo [INFO] Repo root: %REPO_ROOT%
echo.

if not exist "%APPDATA%" mkdir "%APPDATA%" >nul 2>nul
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%" >nul 2>nul

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found in PATH.
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

echo [INFO] Checking Desktop dependencies...
node "%ENSURE_DESKTOP_DEV%"
if errorlevel 1 (
    echo [ERROR] Desktop dependency bootstrap failed.
    pause
    endlocal & exit /b 1
)

echo [INFO] Starting desktop app...
call "%RUN_DESKTOP_DEV%"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Desktop app exited with code %APP_EXIT%.
    pause
)

endlocal & exit /b %APP_EXIT%
