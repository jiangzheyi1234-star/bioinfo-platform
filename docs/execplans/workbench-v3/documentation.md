# Workbench V3 Documentation

## Status (2026-04-05)
- M1 完成：页面结构改为双分区侧边栏 + 头部运行入口。
- M2 完成：前端渲染器支持分析/历史分流；历史交互保持可用。
- M3 完成：结果 tabs 与默认切换策略迁移到 `table/chart/artifacts/provenance`。
- M4 完成：后端功能顺序稳定化、UI smoke 断言同步、隐藏 tabs 的样式冲突修复。
- V3.1 视觉对齐完成：切换为“顶部横排 KPI + 单栏主内容”布局，新增头部状态芯片渲染与 tab 样式对齐。
- V3.2 窄宽度抽屉完成：`<=1280px` 侧栏改为可展开抽屉，新增“功能列表”按钮与遮罩关闭交互。
- V3.3 侧栏语言切换：分析功能改为一行导航；历史结果分组支持 VSCode 风格折叠（默认折叠，tab 切换记忆），历史项操作改为仅选中项显示图标。
- V3.4 Primer 紧凑风格完成：Header 扁平化、KPI 改为 inline stat strip、tabs 与内容卡片降噪，移除结果页渐变叠层。

## Key Decisions
- 使用 `integrated-header-run-btn` 统一承接启动/重跑动作，减少页面内重复入口。
- 把历史结果和分析功能分开渲染，避免“临时结果”污染分析功能导航。
- 后端在 `get_integrated_workbench_config()` 返回前执行统一排序，消除插入路径引起的顺序漂移。

## Verification Notes
- 前端通过 `node --check` 校验语法。
- Python 通过 `compileall` 做语法级校验。
- `pytest` 按仓库约定由用户侧环境执行。
- UI smoke 增加 `integrated-header-status-chip` 断言，覆盖新头部状态元素。

## Follow-ups
- 若继续做视觉对齐，可基于 demo zip 做一轮 spacing/字号精修（不影响本次结构改造）。
