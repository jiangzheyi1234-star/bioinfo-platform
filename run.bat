@echo off
setlocal
chcp 65001 >nul
title H2OMeta Launcher

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "DESKTOP_EXE=%REPO_ROOT%\apps\desktop\src-tauri\target\debug\h2ometa-desktop.exe"
set "API_URL=http://127.0.0.1:8765"
set "WEB_URL=http://127.0.0.1:3100"

set "MODE=%~1"
if "%MODE%"=="" (
    if exist "%DESKTOP_EXE%" (
        set "MODE=--desktop"
    ) else (
        set "MODE=--web"
    )
)

if /I "%MODE%"=="--help" goto :help
if /I "%MODE%"=="-h" goto :help
if /I "%MODE%"=="--check" goto :check
if /I "%MODE%"=="--desktop" goto :desktop
if /I "%MODE%"=="--web" goto :web

echo [ERROR] Unknown option: %MODE%
echo.
goto :help

:help
echo H2OMeta launcher
echo.
echo Usage:
echo   run.bat --web      Start FastAPI + Next.js dev servers in two windows.
echo   run.bat --desktop  Run the built desktop shell executable.
echo   run.bat --check    Check whether the desktop executable exists.
echo   run.bat --help     Show this help.
echo.
echo Default:
echo   run.bat            Prefer --desktop if built, otherwise fall back to --web.
echo.
echo URLs:
echo   API: %API_URL%
echo   Web: %WEB_URL%
endlocal & exit /b 0

:check
if exist "%DESKTOP_EXE%" (
    echo [OK] Desktop shell binary found: %DESKTOP_EXE%
    endlocal & exit /b 0
)
echo [ERROR] Desktop shell binary not found: %DESKTOP_EXE%
echo Build it with:
echo   cd apps\desktop
echo   npm run build:debug:no-bundle:win-gnu
endlocal & exit /b 1

:desktop
echo [INFO] Launch mode: desktop shell
if not exist "%DESKTOP_EXE%" (
    echo [ERROR] Desktop shell binary not found: %DESKTOP_EXE%
    echo Build it with:
    echo   cd apps\desktop
    echo   npm run build:debug:no-bundle:win-gnu
    pause
    endlocal & exit /b 1
)

set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "H2OMETA_PYTHON=py"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"

"%DESKTOP_EXE%"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Desktop app exited with code %APP_EXIT%.
    pause
)
endlocal & exit /b %APP_EXIT%

:web
echo [INFO] Launch mode: web dev
echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Starting API at %API_URL%
echo [INFO] Starting Web at %WEB_URL%

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher "py" not found in PATH.
    pause
    endlocal & exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found in PATH.
    pause
    endlocal & exit /b 1
)

start "H2OMeta API" cmd /k "cd /d %REPO_ROOT% && set WSL_UTF8=1 && set PYTHONUTF8=1 && py -m apps.api.run"
if errorlevel 1 (
    echo [ERROR] Failed to open API terminal window.
    pause
    endlocal & exit /b 1
)

start "H2OMeta Web" cmd /k "cd /d %REPO_ROOT%\apps\web && set NEXT_PUBLIC_API_BASE=%API_URL% && npm run dev"
if errorlevel 1 (
    echo [ERROR] Failed to open web terminal window.
    pause
    endlocal & exit /b 1
)

start "" "%WEB_URL%"
if errorlevel 1 (
    echo [ERROR] Failed to open browser for %WEB_URL%
    pause
    endlocal & exit /b 1
)

echo.
echo [OK] Launch commands submitted.
echo API health: %API_URL%/health
echo Web UI: %WEB_URL%
echo.
echo Close the two spawned terminal windows to stop the dev servers.
endlocal & exit /b 0
