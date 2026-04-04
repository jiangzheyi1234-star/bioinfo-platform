# Detection Workspace V2 Prompt

## Goal
将病原检测从“工具/运行历史/结果工作台”并列页面，重构为单模块工作区：
- 左侧工具栏
- 中央主视图（工具配置 / Run 列表）
- 底部可折叠 Run 面板（状态/日志/结果）
- 右侧按需详情抽屉

## Non-goals
- 不改 Python bridge API 签名
- 不改数据库状态枚举
- 不在本阶段实现跨模块任务中心

## Success Criteria
1. 用户在病原检测模块内完成“配置 -> 运行 -> 查看结果”主链路，无需跳到独立结果页。
2. 运行历史作为主区视图，结果消费以单次 run 详情为中心。
3. 自动刷新静默，手动刷新可感知。
4. 1366x768 与 1920x1080 视窗下结构不拥挤、不重叠。

## Constraints
- 保持现有 `pending/running/completed/failed/retrying` 状态集合不变。
- 保持现有 `ToolBridge` 槽函数兼容。
- 优先复用现有前端渲染器（HistoryPanelRenderer/IntegratedWorkbenchRenderer）。
