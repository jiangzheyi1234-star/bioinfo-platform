# Detection Workspace V2 Documentation

## Status
- Phase: M2 (completed)
- Date: 2026-04-04

## Implemented
1. 引入工作区容器：左栏 + 主视图切换 + 底部运行面板。
2. 历史与结果从顶层 tab 改为嵌入式挂载（兼容现有渲染器）。
3. `switchTab('history'|'integrated')` 兼容为工作区行为。
4. 新提交任务默认保持工具主视图，同时打开底部运行面板。
5. 新增布局状态持久化（主视图、底部面板开关）。
6. 历史列表新增状态筛选（全部/运行中/失败/已完成）并与搜索叠加。
7. 历史列表固定按 `created_at desc` 排序，强化运行态聚焦（`running/retrying`）。
8. 列表行点击与“查看状态/查看结果”统一走 execution 联动入口：自动展开底部面板并定位 execution。
9. 新增历史筛选空态文案（区分无数据 / 筛选为空 / 搜索为空）。
10. 历史筛选状态持久化（workspace 内恢复）。

## Verification
- JS checks passed for:
  - `app_galaxy.js`
  - `render/history_panel.js`
  - `render/tool_panel.js`
  - `results/history_result_loader.js`

## Risks / Follow-ups
1. 详情抽屉仍是壳层，后续如接入需定义与 run panel 的职责边界，避免重复入口。
2. M3 尚未执行：独立“结果工作台”导航入口与旧路由渲染链仍保留。
3. 尚未执行完整手工 UI 冒烟（需用户侧验证窗口行为）。
