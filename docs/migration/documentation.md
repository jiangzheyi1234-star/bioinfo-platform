# H2OMeta New-Architecture Cutover Documentation

## Current Status

- 已完成：6 页工作台、桌面壳、项目/执行/历史/数据库/workbench 主链路。
- 已完成：SSH 生命周期 API、设置页 SSH 面板、工作台壳层拆分。
- 本轮新增：旧 config 兼容删除、旧 workflow alias 删除、靶向测序 live view 不再读取旧 `workflow=unknown_detection` 参数。
- 明确保留：仍被 runtime/API 复用的桥接层，例如 `core/qt_compat.py`。

## Decisions

- 新 UI 采用 Notion 风浅色左侧边栏。
- 功能迁移按新信息架构重组，不按旧 PyQt6 页面逐一复刻。
- 新系统只接受 v2 config schema。
- 新系统只接受新 workflow/tool 名称，历史记录允许展示旧值，但新请求不再兼容旧 alias。
- SSH 配置保存与连接动作分离，避免隐式副作用。

## Follow-ups

- 继续拆分 `workbench_panel*.tsx`，降低复杂度并清理旧控制台残留命名。
- 在 Windows 侧复跑桌面构建与回归。
- 继续审计可安全删除的旧文档和失效测试夹具。
