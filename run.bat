@echo off
setlocal
chcp 65001 >nul
title H2OMeta Launcher

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
set "API_URL=http://127.0.0.1:8765"
set "WEB_URL=http://127.0.0.1:3765"
set "DESKTOP_DEV_DIR=%REPO_ROOT%\apps\desktop"
set "ENSURE_WEB_DEV=%REPO_ROOT%\scripts\ensure-web-dev.cjs"
set "ENSURE_DESKTOP_DEV=%REPO_ROOT%\scripts\ensure-desktop-dev.cjs"
set "RUN_LOCAL_API_DEV=%REPO_ROOT%\scripts\run-local-api-dev.bat"
set "RUN_DESKTOP_DEV=%REPO_ROOT%\scripts\run-desktop-dev.bat"
set "RUN_WEB_DEV=%REPO_ROOT%\scripts\run-web-dev.bat"
set "STOP_EXISTING_LOCAL_API=%REPO_ROOT%\scripts\stop-existing-local-api.ps1"
set "RELEASE_MANIFEST_PATH=%REPO_ROOT%\config\remote-runner-release-manifest.json"
set "DEFAULT_DEV_CACHE_ROOT=%LOCALAPPDATA%\H2OMeta\dev-cache"

set "MODE=%~1"
if "%MODE%"=="" (
    set "MODE=--desktop"
)

if "%H2OMETA_DEV_CACHE_ROOT%"=="" set "H2OMETA_DEV_CACHE_ROOT=%DEFAULT_DEV_CACHE_ROOT%"
if "%H2OMETA_UV_CACHE_DIR%"=="" (
    if not "%UV_CACHE_DIR%"=="" (
        set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"
    )
)
if "%H2OMETA_UV_CACHE_DIR%"=="" set "H2OMETA_UV_CACHE_DIR=%H2OMETA_DEV_CACHE_ROOT%\uv-cache"
set "UV_CACHE_DIR=%H2OMETA_UV_CACHE_DIR%"
if "%H2OMETA_CARGO_TARGET_DIR%"=="" set "H2OMETA_CARGO_TARGET_DIR=%H2OMETA_DEV_CACHE_ROOT%\cargo-target\bio_ui"
if "%H2OMETA_ARTIFACT_CACHE_DIR%"=="" set "H2OMETA_ARTIFACT_CACHE_DIR=%H2OMETA_DEV_CACHE_ROOT%\artifacts"
set "DESKTOP_EXE=%H2OMETA_CARGO_TARGET_DIR%\debug\h2ometa-desktop.exe"

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
echo.
echo Dev cache defaults:
echo   UV cache: %H2OMETA_UV_CACHE_DIR%
echo   Cargo target: %H2OMETA_CARGO_TARGET_DIR%
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

echo [INFO] Repo root: %REPO_ROOT%
echo [INFO] Tauri dev URL: %WEB_URL%
echo [INFO] API URL: %API_URL%
echo [INFO] H2OMETA_WORKDIR=%H2OMETA_WORKDIR%
echo [INFO] H2OMETA_UV_CACHE_DIR=%H2OMETA_UV_CACHE_DIR%
echo [INFO] H2OMETA_CARGO_TARGET_DIR=%H2OMETA_CARGO_TARGET_DIR%
echo.

call :build_remote_runner_artifact
if errorlevel 1 (
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
if not exist "%STOP_EXISTING_LOCAL_API%" (
    echo [ERROR] API stop helper not found: %STOP_EXISTING_LOCAL_API%
    pause
    endlocal & exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_EXISTING_LOCAL_API%" -HostAddress 127.0.0.1 -Port 8765
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)
echo [INFO] Checking local Web server on 127.0.0.1:3765...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_EXISTING_LOCAL_API%" -HostAddress 127.0.0.1 -Port 3765
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)

echo [INFO] Desktop dev will launch its own local backend after startup checks...

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
call :build_remote_runner_artifact
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)

echo [INFO] Checking local API server on 127.0.0.1:8765...
if not exist "%STOP_EXISTING_LOCAL_API%" (
    echo [ERROR] API stop helper not found: %STOP_EXISTING_LOCAL_API%
    pause
    endlocal & exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_EXISTING_LOCAL_API%" -HostAddress 127.0.0.1 -Port 8765
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)

echo [INFO] Desktop shell will launch its own local backend after startup checks...

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

set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "WSL_UTF8=1"
set "PYTHONUTF8=1"
set "NEXT_PUBLIC_API_BASE=%API_URL%"
set "H2OMETA_RUNTIME_BUILD_ID=terminal-websocket-v1"
set "H2OMETA_BACKEND_SOURCE=run.bat:web"
call :build_remote_runner_artifact
if errorlevel 1 (
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

echo [INFO] Checking local API server on 127.0.0.1:8765...
if not exist "%STOP_EXISTING_LOCAL_API%" (
    echo [ERROR] API stop helper not found: %STOP_EXISTING_LOCAL_API%
    pause
    endlocal & exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_EXISTING_LOCAL_API%" -HostAddress 127.0.0.1 -Port 8765
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)
echo [INFO] Checking local Web server on 127.0.0.1:3765...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%STOP_EXISTING_LOCAL_API%" -HostAddress 127.0.0.1 -Port 3765
if errorlevel 1 (
    pause
    endlocal & exit /b 1
)

if "%H2OMETA_HEADLESS_LAUNCH%"=="1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\start-web-stack-hidden.ps1" -RepoRoot "%REPO_ROOT%" -ApiLauncher "%RUN_LOCAL_API_DEV%" -WebLauncher "%RUN_WEB_DEV%"
    if errorlevel 1 (
        pause
        endlocal & exit /b 1
    )
    echo.
    echo [OK] Hidden launch commands submitted.
    echo API health: %API_URL%/health
    echo Web UI: %WEB_URL%
    endlocal & exit /b 0
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

:build_remote_runner_artifact
echo [INFO] Resolving manifest-declared remote runner artifacts...
if not exist "%RELEASE_MANIFEST_PATH%" (
    echo [ERROR] Remote runner release manifest not found: %RELEASE_MANIFEST_PATH%
    exit /b 1
)
call :prepare_windows_uv_environment
if errorlevel 1 exit /b 1

set "ARTIFACT_ENV_FILE=%TEMP%\h2ometa-release-artifacts-%RANDOM%-%RANDOM%.cmd"
call uv run --frozen python "%REPO_ROOT%\scripts\check_remote_runner_release_artifacts.py" --cmd-env > "%ARTIFACT_ENV_FILE%"
if errorlevel 1 (
    if exist "%ARTIFACT_ENV_FILE%" del "%ARTIFACT_ENV_FILE%" >nul 2>nul
    echo [ERROR] Manifest-declared release artifacts could not be resolved or verified.
    echo [ERROR] The resolver checks explicit bundle env vars, manifest search roots, and the manifest download cache.
    echo [ERROR] For private GitHub releases set H2OMETA_RELEASE_DOWNLOAD_TOKEN, GH_TOKEN, GITHUB_TOKEN, GITHUB_PERSONAL_ACCESS_TOKEN, or configure an H2OMeta GH CLI login.
    exit /b 1
)
call "%ARTIFACT_ENV_FILE%"
if exist "%ARTIFACT_ENV_FILE%" del "%ARTIFACT_ENV_FILE%" >nul 2>nul

if not exist "%H2OMETA_REMOTE_RUNNER_BUNDLE%" (
    echo [ERROR] Prebuilt remote runner artifact not found.
    echo [ERROR] The shared artifact resolver did not set H2OMETA_REMOTE_RUNNER_BUNDLE.
    exit /b 1
)
if not exist "%H2OMETA_REMOTE_RUNNER_BUNDLE%.sha256" (
    echo [ERROR] Prebuilt remote runner artifact checksum not found: %H2OMETA_REMOTE_RUNNER_BUNDLE%.sha256
    exit /b 1
)
echo [INFO] H2OMETA_REMOTE_RUNNER_BUNDLE=%H2OMETA_REMOTE_RUNNER_BUNDLE%

if not exist "%H2OMETA_WORKFLOW_RUNTIME_BUNDLE%" (
    echo [ERROR] Prebuilt workflow runtime artifact not found.
    echo [ERROR] The shared artifact resolver did not set H2OMETA_WORKFLOW_RUNTIME_BUNDLE.
    exit /b 1
)
if not exist "%H2OMETA_WORKFLOW_RUNTIME_BUNDLE%.sha256" (
    echo [ERROR] Prebuilt workflow runtime artifact checksum not found: %H2OMETA_WORKFLOW_RUNTIME_BUNDLE%.sha256
    exit /b 1
)
echo [INFO] H2OMETA_WORKFLOW_RUNTIME_BUNDLE=%H2OMETA_WORKFLOW_RUNTIME_BUNDLE%
exit /b 0

:prepare_windows_uv_environment
where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv is required for release artifact resolution on Windows.
    exit /b 1
)
if "%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"=="" (
    set "H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT=%REPO_ROOT%\.venv-win"
)
set "UV_PYTHON="
set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"
set "UV_PYTHON_INSTALL_DIR=%REPO_ROOT%\.codex-uv-python"
call :validate_windows_uv_project_environment
if errorlevel 1 exit /b 1
echo [INFO] UV project environment: %UV_PROJECT_ENVIRONMENT%
echo [INFO] UV python install dir: %UV_PYTHON_INSTALL_DIR%
exit /b 0

:validate_windows_uv_project_environment
if "%UV_PROJECT_ENVIRONMENT%"=="" (
    echo [ERROR] UV_PROJECT_ENVIRONMENT is not set.
    exit /b 1
)
if /I "%UV_PROJECT_ENVIRONMENT%"=="%REPO_ROOT%\.venv" (
    echo [ERROR] Refusing to use repo-local .venv from Windows. Use .venv-win for Windows-owned uv work.
    exit /b 1
)
echo %UV_PROJECT_ENVIRONMENT% | findstr /I /C:"%REPO_ROOT%\\.venv\\" >nul 2>nul
if not "%ERRORLEVEL%"=="1" (
    echo [ERROR] Refusing to use repo-local .venv from Windows. Use .venv-win for Windows-owned uv work.
    exit /b 1
)
if /I "%UV_PROJECT_ENVIRONMENT%"=="%REPO_ROOT%\.venv-wsl-codex" (
    echo [ERROR] Refusing to use WSL-owned .venv-wsl-codex from Windows.
    exit /b 1
)
echo %UV_PROJECT_ENVIRONMENT% | findstr /I /C:"%REPO_ROOT%\\.venv-wsl-codex\\" >nul 2>nul
if not "%ERRORLEVEL%"=="1" (
    echo [ERROR] Refusing to use WSL-owned .venv-wsl-codex from Windows.
    exit /b 1
)
echo %UV_PROJECT_ENVIRONMENT% | findstr /I /C:"/mnt/" >nul 2>nul
if not "%ERRORLEVEL%"=="1" (
    echo [ERROR] Refusing to use a WSL /mnt/... uv environment from Windows: %UV_PROJECT_ENVIRONMENT%
    exit /b 1
)
echo %UV_PROJECT_ENVIRONMENT% | findstr /I /C:"\\wsl" >nul 2>nul
if not "%ERRORLEVEL%"=="1" (
    echo [ERROR] Refusing to use a WSL UNC uv environment from Windows: %UV_PROJECT_ENVIRONMENT%
    exit /b 1
)
if exist "%UV_PROJECT_ENVIRONMENT%\bin" (
    echo [ERROR] Refusing uv environment with Linux-style bin directory: %UV_PROJECT_ENVIRONMENT%
    exit /b 1
)
if exist "%UV_PROJECT_ENVIRONMENT%\lib64" (
    echo [ERROR] Refusing uv environment with Linux-style lib64 directory: %UV_PROJECT_ENVIRONMENT%
    exit /b 1
)
exit /b 0
