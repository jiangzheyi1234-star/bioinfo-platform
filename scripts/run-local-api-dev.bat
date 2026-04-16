@echo off
setlocal
chcp 65001 >nul

if "%H2OMETA_WORKDIR%"=="" (
    echo [ERROR] H2OMETA_WORKDIR is not set.
    endlocal & exit /b 1
)

if "%H2OMETA_CONDA_EXE%"=="" (
    echo [ERROR] H2OMETA_CONDA_EXE is not set.
    endlocal & exit /b 1
)

if "%H2OMETA_CONDA_ENV%"=="" (
    echo [ERROR] H2OMETA_CONDA_ENV is not set.
    endlocal & exit /b 1
)

cd /d "%H2OMETA_WORKDIR%"
where uv >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    call uv run --isolated --no-project --with-requirements apps/api/requirements.txt python -m apps.api.run
    set "APP_EXIT=%ERRORLEVEL%"
    goto after_run
)

call "%H2OMETA_CONDA_EXE%" run --no-capture-output -n "%H2OMETA_CONDA_ENV%" python -m apps.api.run
set "APP_EXIT=%ERRORLEVEL%"
:after_run
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Local API exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
