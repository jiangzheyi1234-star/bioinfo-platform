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

set "PATH=%USERPROFILE%\.cargo\bin;C:\msys64\ucrt64\bin;%PATH%"

cd /d "%H2OMETA_WORKDIR%\apps\desktop"
npm run dev
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Desktop dev exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
