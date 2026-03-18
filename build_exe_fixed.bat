@echo off
chcp 65001 >nul
echo ==========================================
echo H2OMeta 打包工具 (修复版)
echo ==========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [步骤 1/5] 清理旧的构建文件...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
echo ✓ 清理完成

echo.
echo [步骤 2/5] 安装/更新 PyInstaller...
pip install --upgrade pyinstaller
echo ✓ PyInstaller 准备完成

echo.
echo [步骤 3/5] 确保所有依赖已安装...
pip install -r requirements.txt
echo ✓ 依赖检查完成

echo.
echo [步骤 4/5] 执行打包...
echo 注意: 这可能需要几分钟时间...
echo.

REM 执行打包 (使用修复后的 spec 文件)
pyinstaller bio_ui.spec --clean --noconfirm --log-level=WARN

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！
    echo 请检查上方的错误信息
    pause
    exit /b 1
)

echo.
echo [步骤 5/5] 复制额外资源...

REM 确保资源文件正确复制
if exist "dist\H2OMeta\ui" (
    echo ✓ UI 资源已包含
) else (
    echo → 复制 UI 资源...
    xcopy /E /I /Y "ui" "dist\H2OMeta\ui" >nul 2>&1
)

REM 复制 plugins 目录
if exist "plugins" (
    echo → 复制插件目录...
    xcopy /E /I /Y "plugins" "dist\H2OMeta\plugins" >nul 2>&1
)

echo.
echo ==========================================
echo [成功] 打包完成！
echo ==========================================
echo.
echo 可执行文件位置:
echo   dist\H2OMeta\H2OMeta.exe
echo.
echo 使用说明:
echo   1. 将整个 dist\H2OMeta 文件夹复制到目标位置
echo   2. 运行 H2OMeta.exe 启动应用
echo.
echo 调试模式:
echo   如果遇到问题，先尝试在命令行运行查看错误信息
echo.
pause
