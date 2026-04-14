@echo off
setlocal
chcp 65001 >nul
title H2OMeta Launcher

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "DESKTOP_EXE=%REPO_ROOT%\apps\desktop\src-tauri\target\debug\h2ometa-desktop.exe"
set "API_URL=http://127.0.0.1:8765"
set "WEB_URL=http://127.0.0.1:3100"
set "DESKTOP_DEV_DIR=%REPO_ROOT%\apps\desktop"
set "ENSURE_WEB_DEV=%REPO_ROOT%\scripts\ensure-web-dev.cjs"
set "ENSURE_DESKTOP_DEV=%REPO_ROOT%\scripts\ensure-desktop-dev.cjs"
set "RUN_LOCAL_API_DEV=%REPO_ROOT%\scripts\run-local-api-dev.bat"
set "RUN_DESKTOP_DEV=%REPO_ROOT%\scripts\run-desktop-dev.bat"
set "RUN_WEB_DEV=%REPO_ROOT%\scripts\run-web-dev.bat"
set "LOCAL_CONDA_ENV=bio_ui"
set "LOCAL_CONDA_EXE=C:\Users\Administrator\miniconda3\Scripts\conda.exe"

set "MODE=%~1"
if "%MODE%"=="" (
    set "MODE=--desktop"
)

if /I "%MODE%"=="--help" goto :help
if /I "%MODE%"=="-h" goto :help
if /I "%MODE%"=="--check" goto :check
if /I "%MODE%"=="--desktop" goto :desktop
if /I "%MODE%"=="--desktop-built" goto :desktop_built
if /I "%MODE%"=="--web" goto :web

echo [ERROR] Unknown option: %MODE%
echo.
goto :help

:help
echo H2OMeta launcher
echo.
echo Usage:
echo   run.bat --web      Start FastAPI + Next.js dev servers in two windows.
echo   run.bat --desktop  Start Tauri desktop dev mode with live frontend changes.
echo   run.bat --desktop-built  Run the built desktop shell executable.
echo   run.bat --check    Check whether the desktop executable exists.
echo   run.bat --help     Show this help.
echo.
echo Default:
echo   run.bat            Prefer live desktop dev mode.
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
echo [INFO] Launch mode: desktop dev
if not exist "%DESKTOP_DEV_DIR%\package.json" (
    echo [ERROR] Desktop source directory not found: %DESKTOP_DEV_DIR%
    pause
    endlocal & exit /b 1
)

set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "H2OMETA_ALLOW_REPO_BACKEND=1"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_BASE=%API_URL%"
set "H2OMETA_CONDA_ENV=%LOCAL_CONDA_ENV%"
set "H2OMETA_CONDA_EXE=%LOCAL_CONDA_EXE%"

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Tauri dev URL: %WEB_URL%
echo [INFO] API URL: %API_URL%
echo [INFO] H2OMETA_WORKDIR=%H2OMETA_WORKDIR%
echo.

if not exist "%LOCAL_CONDA_EXE%" (
    echo [ERROR] Local conda executable not found: %LOCAL_CONDA_EXE%
    pause
    endlocal & exit /b 1
)

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

if not exist "%ENSURE_DESKTOP_DEV%" (
    echo [ERROR] Desktop bootstrap script not found: %ENSURE_DESKTOP_DEV%
    pause
    endlocal & exit /b 1
)

if not exist "%RUN_LOCAL_API_DEV%" (
    echo [ERROR] API launcher script not found: %RUN_LOCAL_API_DEV%
    pause
    endlocal & exit /b 1
)

if not exist "%RUN_DESKTOP_DEV%" (
    echo [ERROR] Desktop launcher script not found: %RUN_DESKTOP_DEV%
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

echo [INFO] Checking local API server on 127.0.0.1:8765...
cmd /c "netstat -ano | findstr :8765 | findstr LISTENING >nul"
if errorlevel 1 (
    echo [INFO] API server not running. Starting local backend window with conda env %LOCAL_CONDA_ENV%...
    ver >nul
    start "H2OMeta API" cmd /k call "%RUN_LOCAL_API_DEV%"
    if errorlevel 1 (
        echo [ERROR] Failed to open API terminal window.
        pause
        endlocal & exit /b 1
    )
) else (
    echo [INFO] Reusing existing API server on %API_URL%
)

ver >nul
start "H2OMeta Desktop Dev" cmd /k call "%RUN_DESKTOP_DEV%"
if errorlevel 1 (
    echo [ERROR] Failed to open desktop dev terminal window.
    pause
    endlocal & exit /b 1
)

echo [OK] Desktop dev launch command submitted.
echo [INFO] Watch the \"H2OMeta Desktop Dev\" window for Tauri build output.
endlocal & exit /b 0

:desktop_built
echo [INFO] Launch mode: desktop built shell
if not exist "%DESKTOP_EXE%" (
    echo [ERROR] Desktop shell binary not found: %DESKTOP_EXE%
    echo Build it with:
    echo   cd apps\desktop
    echo   npm run build:debug:no-bundle:win-gnu
    pause
    endlocal & exit /b 1
)

set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "H2OMETA_ALLOW_REPO_BACKEND=1"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_BASE=%API_URL%"
set "H2OMETA_CONDA_ENV=%LOCAL_CONDA_ENV%"
set "H2OMETA_CONDA_EXE=%LOCAL_CONDA_EXE%"

if not exist "%LOCAL_CONDA_EXE%" (
    echo [ERROR] Local conda executable not found: %LOCAL_CONDA_EXE%
    pause
    endlocal & exit /b 1
)

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

if not exist "%LOCAL_CONDA_EXE%" (
    echo [ERROR] Local conda executable not found: %LOCAL_CONDA_EXE%
    pause
    endlocal & exit /b 1
)

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
start "H2OMeta API" cmd /k call "%RUN_LOCAL_API_DEV%"
if errorlevel 1 (
    echo [ERROR] Failed to open API terminal window.
    pause
    endlocal & exit /b 1
)

ver >nul
start "H2OMeta Web" cmd /k call "%RUN_WEB_DEV%"
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
