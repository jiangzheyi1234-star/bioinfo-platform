@echo off
setlocal
chcp 65001 >nul

if "%H2OMETA_WORKDIR%"=="" (
    echo [ERROR] H2OMETA_WORKDIR is not set.
    endlocal & exit /b 1
)

cd /d "%H2OMETA_WORKDIR%"
if not "%UV_CACHE_DIR%"=="" (
    set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"
)
if "%H2OMETA_UV_CACHE_DIR%"=="" (
    set "H2OMETA_UV_CACHE_DIR=%LOCALAPPDATA%\H2OMeta\dev-cache\uv-cache"
)
set "UV_CACHE_DIR=%H2OMETA_UV_CACHE_DIR%"
where uv >nul 2>nul
if not "%ERRORLEVEL%"=="0" (
    echo [ERROR] uv is required for local API startup on Windows.
    endlocal & exit /b 1
)

if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%" >nul 2>nul
echo [INFO] UV cache dir: %UV_CACHE_DIR%

if "%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"=="" (
    set "H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT=%H2OMETA_WORKDIR%\.venv-win"
)
set "UV_PYTHON="
if not "%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"=="" (
    set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"
)
set "UV_PYTHON_INSTALL_DIR=%H2OMETA_WORKDIR%\.codex-uv-python"
echo [INFO] UV project environment: %UV_PROJECT_ENVIRONMENT%

set "H2OMETA_DEPLOYMENT_MODE=desktop"
set "H2OMETA_API_HOST=127.0.0.1"
call uv run --frozen python -m apps.api.run
set "APP_EXIT=%ERRORLEVEL%"
:after_run
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Local API exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
