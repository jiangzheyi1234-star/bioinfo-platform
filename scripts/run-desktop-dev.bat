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

if "%H2OMETA_CARGO_TARGET_DIR%"=="" (
    set "H2OMETA_CARGO_TARGET_DIR=%LOCALAPPDATA%\H2OMeta\dev-cache\cargo-target\bio_ui"
)

set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;C:\msys64\ucrt64\bin;%PATH%"
set "CARGO_TARGET_DIR=%H2OMETA_CARGO_TARGET_DIR%"

cd /d "%H2OMETA_WORKDIR%\apps\desktop"
if not exist "%CARGO_TARGET_DIR%" mkdir "%CARGO_TARGET_DIR%" >nul 2>nul
echo [INFO] Cargo target dir: %CARGO_TARGET_DIR%
echo [INFO] Closing stale H2OMeta desktop process if present...
taskkill /IM h2ometa-desktop.exe /F >nul 2>nul
timeout /t 1 /nobreak >nul
npm run dev
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Desktop dev exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
