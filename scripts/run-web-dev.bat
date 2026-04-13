@echo off
setlocal
chcp 65001 >nul

if "%H2OMETA_WORKDIR%"=="" (
    echo [ERROR] H2OMETA_WORKDIR is not set.
    endlocal & exit /b 1
)

cd /d "%H2OMETA_WORKDIR%\apps\web"
npm run dev
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] Web dev exited with code %APP_EXIT%.
)

endlocal & exit /b %APP_EXIT%
