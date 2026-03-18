@echo off
chcp 65001 >nul
echo ==========================================
echo H2OMeta Packager (Fixed)
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+ first.
    pause
    exit /b 1
)

echo [Step 1/5] Cleaning previous build artifacts...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
echo [OK] Clean completed.

echo.
echo [Step 2/5] Installing/updating PyInstaller...
pip install --upgrade pyinstaller
echo [OK] PyInstaller is ready.

echo.
echo [Step 3/5] Ensuring dependencies are installed...
pip install -r requirements.txt
echo [OK] Dependency check completed.

echo.
echo [Step 4/5] Building executable...
echo Note: This may take several minutes.
echo.

REM Use canonical spec file. bio_ui.spec remains as compatibility shim.
pyinstaller h2ometa.spec --clean --noconfirm --log-level=WARN

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    echo Please review the error output above.
    pause
    exit /b 1
)

echo.
echo [Step 5/5] Copying extra resources...

REM Ensure UI assets exist in dist folder.
if exist "dist\H2OMeta\ui" (
    echo [OK] UI assets included.
) else (
    echo [INFO] Copying UI assets...
    xcopy /E /I /Y "ui" "dist\H2OMeta\ui" >nul 2>&1
)

REM Copy plugins folder if present.
if exist "plugins" (
    echo [INFO] Copying plugins...
    xcopy /E /I /Y "plugins" "dist\H2OMeta\plugins" >nul 2>&1
)

echo.
echo ==========================================
echo [SUCCESS] Packaging completed.
echo ==========================================
echo.
echo Executable path:
echo   dist\H2OMeta\H2OMeta.exe
echo.
echo Usage:
echo   1. Copy the whole dist\H2OMeta folder to the target machine.
echo   2. Run H2OMeta.exe to start the app.
echo.
echo Debug tip:
echo   If startup fails, run from cmd to inspect error output.
echo.
pause
