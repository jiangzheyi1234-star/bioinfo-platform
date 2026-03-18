@echo off
setlocal
chcp 65001 >nul
title H2OMeta

set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"
if not exist "%CONDA_BAT%" (
    for /f "delims=" %%I in ('where conda.bat 2^>nul') do (
        set "CONDA_BAT=%%I"
        goto :conda_found
    )
    echo [ERROR] Cannot find conda.bat. Please install Miniconda/Anaconda first.
    pause
    exit /b 1
)

:conda_found
call "%CONDA_BAT%" activate bio_ui
if errorlevel 1 (
    echo [ERROR] Cannot activate conda env "bio_ui".
    echo Run: conda create -n bio_ui python=3.12
    pause
    exit /b 1
)

if /I "%~1"=="--check" (
    echo [OK] Conda env "bio_ui" activated.
    endlocal & exit /b 0
)

set "PYTHONUNBUFFERED=1"
python -m ui.main
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] App exited with code %APP_EXIT%.
    pause
)

endlocal & exit /b %APP_EXIT%
