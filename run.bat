@echo off
setlocal
chcp 65001 >nul
title H2OMeta Desktop

set "REPO_ROOT=%~dp0"
set "DESKTOP_EXE=%REPO_ROOT%apps\desktop\src-tauri\target\debug\h2ometa-desktop.exe"

if /I "%~1"=="--check" (
    if exist "%DESKTOP_EXE%" (
        echo [OK] Desktop shell binary found: %DESKTOP_EXE%
        endlocal & exit /b 0
    )
    echo [ERROR] Desktop shell binary not found: %DESKTOP_EXE%
    echo Run:
    echo   cd apps\desktop
    echo   npm run build:debug:no-bundle:win-gnu
    endlocal & exit /b 1
)

if not exist "%DESKTOP_EXE%" (
    echo [ERROR] Desktop shell binary not found: %DESKTOP_EXE%
    echo Please build desktop shell first:
    echo   cd apps\desktop
    echo   npm run build:debug:no-bundle:win-gnu
    pause
    endlocal & exit /b 1
)

set "H2OMETA_WORKDIR=%REPO_ROOT%"
set "H2OMETA_PYTHON=py"

"%DESKTOP_EXE%"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Desktop app exited with code %APP_EXIT%.
    pause
)

endlocal & exit /b %APP_EXIT%
