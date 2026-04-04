# Detection Workspace V2 Plan

## M1: Workspace Shell + Run Detail First
- [x] 增加工作区结构：主视图切换 + 底部运行面板 + 详情抽屉壳。
- [x] 将历史/结果 tab 嵌入工作区挂载点。
- [x] 建立兼容映射：旧 `switchTab('history'|'integrated')` -> 工作区行为。
- [x] 打通“提交运行 -> 保持工具视图 -> 打开底部面板”链路。

### M1 Verification
- `node --check ui/pages/detection_page_assets/app_galaxy.js`
- `node --check ui/pages/detection_page_assets/render/tool_panel.js`
- `node --check ui/pages/detection_page_assets/render/run_modal.js`
- `node --check ui/pages/detection_page_assets/results/history_result_loader.js`

## M2: Run List Enhancement
- [x] 增强 run 列表筛选、排序与状态聚焦。
- [x] 列表选中与底部详情联动优化。

### M2 Verification
- `node --check ui/pages/detection_page_assets/app_galaxy.js`
- `node --check ui/pages/detection_page_assets/render/history_panel.js`
- `node --check ui/pages/detection_page_assets/results/history_result_loader.js`
- `node --check ui/pages/detection_page_assets/render/tool_panel.js`

## M3: Legacy Result Page Removal
- [x] 完全下线独立“结果工作台”导航入口。
- [x] 清理旧路由与重复渲染链。

### M3 Verification
- `node --check ui/pages/detection_page_assets/app_galaxy.js`
- `node --check ui/pages/detection_page_assets/render/run_modal.js`
- `node --check ui/pages/detection_page_assets/render/tool_panel.js`
- `node --check ui/pages/detection_page_assets/results/workbench_state_manager.js`
- `node --check ui/pages/detection_page_assets/results/history_result_loader.js`

## Rollback Notes
- 顶部 legacy 入口已下线，回退需恢复 `index_galaxy.html` 的 legacy 顶部按钮与独立 tab-content 结构。
