# Detection Workspace V2 Documentation

## Status
- Phase: M3 (completed)
- Date: 2026-04-05

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
11. M3 清理：删除独立 legacy `history/integrated` 顶部入口与独立 tab-content 页面，历史与结果改为 workspace 原生内嵌结构。
12. `switchTab('history'|'integrated')` 仅保留 workspace 行为映射，不再依赖 legacy DOM 挂载迁移。
13. 新增工具栏折叠能力与持久化状态，提升主工作区可用空间。
14. 顶部导航视觉降权，减少与 workspace 主切换的层级冲突。
15. run 面板内结果区改为单列阅读流（侧栏上置），并修复长文本 `break-all` 导致的逐字竖排观感问题。

## Verification
- JS checks passed for:
  - `app_galaxy.js`
  - `render/run_modal.js`
  - `render/tool_panel.js`
  - `results/workbench_state_manager.js`
  - `results/history_result_loader.js`
  - `render/history_panel.js`

## Risks / Follow-ups
1. 详情抽屉仍是壳层，后续如接入需定义与 run panel 的职责边界，避免重复入口。
2. 已移除 legacy 独立页结构，如需回滚需整体恢复 `index_galaxy.html` 结构而非切换 class。
3. 尚未执行完整手工 UI 冒烟（需用户侧验证窗口行为）。
