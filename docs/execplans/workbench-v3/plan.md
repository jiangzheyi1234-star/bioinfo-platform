# Workbench V3 Plan

## Reference
- OpenAI blog: Run long horizon tasks with Codex (agent loop: `Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat`)
- Date locked: 2026-04-05

## M1: Shell Restructure
- [x] 侧边栏拆分为 `分析功能` 与 `历史结果` 两段容器。
- [x] 顶部标题区加入运行按钮 `integrated-header-run-btn`。
- [x] 删除页面内执行入口块（旧 `integrated-run-card`）。

### M1 Verification
- `rg -n "integrated-analysis-feature-list|integrated-history-feature-list|integrated-header-run-btn" ui/pages/detection_page_assets/index_galaxy.html`

## M2: Renderer + State Wiring
- [x] 侧边栏渲染器支持双容器输入。
- [x] 功能列表按“分析/历史”分流。
- [x] 历史项继续支持固定、关闭、激活。

### M2 Verification
- `node --check ui/pages/detection_page_assets/app_galaxy.js`
- `node --check ui/pages/detection_page_assets/render/integrated_sidebar.js`
- `node --check ui/pages/detection_page_assets/render/integrated_workbench_renderer.js`

## M3: Result Tabs + Run Entry
- [x] tabs 改为 `table/chart/artifacts/provenance`。
- [x] 默认 tab 由 viewer strategy 映射（files->artifacts, chart/html->chart, else->table）。
- [x] 运行入口统一走 `openIntegratedRunEntry()`。

### M3 Verification
- `rg -n "data-result-tab=\"table\"|data-result-tab=\"chart\"|data-result-tab=\"artifacts\"|data-result-tab=\"provenance\"" ui/pages/detection_page_assets/index_galaxy.html`

## M4: Stability + Regression Guard
- [x] 后端统一分析功能顺序常量并在返回前重排。
- [x] UI smoke 断言更新到新 DOM 结构与 tab 名称。
- [x] 清理会错误隐藏新 tabs 的样式规则。

### M4 Verification
- `node --check ui/pages/detection_page_assets/render/integrated_workbench_renderer.js`
- `node --check ui/pages/detection_page_assets/render/integrated_sidebar.js`
- `python3 -m compileall core/execution/tool_bridge_specs.py core/execution/tool_bridge_workbench_ops.py`
