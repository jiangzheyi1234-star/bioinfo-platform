# Desktop Cutover Finalization

Date: 2026-04-06

## Goal

完成桌面迁移收尾，使 Tauri + Next + FastAPI 成为唯一运行路径，并移除 PyQt6 相关代码与依赖。

## Completed Milestones

1. Core 去 Qt 运行时依赖：
   - 新增 `core/qt_compat.py`。
   - `core/` 中原 `PyQt6.QtCore` 引用切换到兼容层。
2. Web UI 壳层重构：
   - 四页结构统一为左侧边栏布局。
   - 视觉切换为浅色极简风格。
   - 增加 Alt+1/2/3/4 页面快捷键。
3. 旧路径清理：
   - 删除 `ui/` 目录与 `run_pyqt6.bat`。
   - 删除 PyInstaller 旧 spec 与 Qt hook 文件。
   - 删除 Qt/UI 专属测试文件。
4. 依赖与文档收敛：
   - 移除 `requirements` / `environment.yml` 中 Qt 依赖。
   - 架构文档更新为 Tauri + Web + API。

## Validation Checklist

- Web build: `npm --prefix apps/web run build`
- Desktop build: `npm --prefix apps/desktop run build:debug:no-bundle:win-gnu`
- API health: `iwr http://127.0.0.1:8765/health`
- Windows回归脚本: `powershell -ExecutionPolicy Bypass -File .\scripts\m6_windows_regression.ps1`

## Cutover Result

- 默认入口：`run.bat`
- 不再保留 PyQt6 回退入口。
