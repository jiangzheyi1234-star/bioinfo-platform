@echo off
setlocal
chcp 65001 >nul

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

echo [INFO] Cleaning repo-local dev caches under %REPO_ROOT%

if exist "%REPO_ROOT%\apps\desktop\src-tauri\target" rmdir /s /q "%REPO_ROOT%\apps\desktop\src-tauri\target"
if exist "%REPO_ROOT%\apps\web\.next" rmdir /s /q "%REPO_ROOT%\apps\web\.next"
if exist "%REPO_ROOT%\apps\web\out" rmdir /s /q "%REPO_ROOT%\apps\web\out"
if exist "%REPO_ROOT%\apps\web\dist" rmdir /s /q "%REPO_ROOT%\apps\web\dist"
if exist "%REPO_ROOT%\.uv-cache" rmdir /s /q "%REPO_ROOT%\.uv-cache"

for /d /r "%REPO_ROOT%" %%D in (__pycache__ .pytest_cache .ruff_cache) do (
    if exist "%%~fD" rmdir /s /q "%%~fD"
)

if exist "%REPO_ROOT%\logs\desktop_backend_boot.log" del /f /q "%REPO_ROOT%\logs\desktop_backend_boot.log"

echo [OK] Repo-local caches removed.
endlocal & exit /b 0
