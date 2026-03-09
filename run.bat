@echo off
chcp 65001 >nul
title H2OMeta

:: 激活 conda 环境并启动应用
call conda activate bio_ui 2>nul
if errorlevel 1 (
    echo [错误] conda 环境 bio_ui 未找到，请先运行: conda create -n bio_ui python=3.11
    pause
    exit /b 1
)

python -m ui.main
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，按任意键退出
    pause >nul
)
