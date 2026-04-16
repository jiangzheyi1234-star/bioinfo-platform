@echo off
setlocal
chcp 65001 >nul

if "%H2OMETA_WORKDIR%"=="" (
    echo [ERROR] H2OMETA_WORKDIR is not set.
    endlocal & exit /b 1
)

cd /d "%H2OMETA_WORKDIR%"
where uv >nul 2>nul
if not "%ERRORLEVEL%"=="0" (
    echo [ERROR] uv is required for local API startup on Windows.
    endlocal & exit /b 1
)

call uv run --isolated --no-project --with-requirements apps/api/requirements.txt python -m apps.api.run
set "APP_EXIT=%ERRORLEVEL%"
:after_run
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Local API exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
