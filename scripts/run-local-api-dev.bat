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
call "%H2OMETA_CONDA_EXE%" run -n "%H2OMETA_CONDA_ENV%" python -m apps.api.run
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Local API exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
