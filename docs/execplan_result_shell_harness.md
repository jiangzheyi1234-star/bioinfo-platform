# Result Shell Harness ExecPlan

## Goal

为检测页结果工作台建立一套可扩展的“结果壳”框架，直接复用现有 `get_results_for_execution()` 协议与 integrated workbench，
但把结果展示逻辑提升为：

- `archetype` 驱动的 viewer registry
- 严格 view contract 校验
- 统一 transform/view-model 层
- 可组合 block UI（hero / summary / table / chart / files / provenance / sections）

设计原则参考：

- Galaxy 的 visualization registry / data-provider 思路
- Superset 的 metadata + transformProps + chart component 分层
- Dagster 的 block-based result details
- Anthropic “Harness design for long-running apps” 对长时程任务的壳层/状态反馈思路

## Constraints

- 不新增 silent fallback；缺字段要明确暴露在 UI 中。
- 不继续向 `ui/pages/detection_page_assets/app_galaxy.js` 堆重逻辑。
- 优先新建相邻模块，让原入口文件保留事件绑定与薄壳职责。
- 不改动后端结果 schema，先通过前端 result shell 吸纳现有输出。

## Milestones

### M1. Result Shell Registry

- 新建 `ui/pages/detection_page_assets/result_shell_registry.js`
- 定义 archetype registry、required viewers、tab copy、validation contract
- 提供统一 view-model 计算入口

Verify:

- archetype 缺字段时，UI 明确展示 contract violation
- 现有历史结果仍可正常进入 integrated workbench

### M2. Result Shell UI Override

- 新建 `ui/pages/detection_page_assets/result_shell_overrides.js`
- 接管 integrated 结果区的 hero、summary、provenance、sections、viewer strategy
- 复用现有 chart/table/artifact renderer，避免重复造轮子

Verify:

- taxonomy / qc / html / workflow / artifact archetype 均可渲染
- history -> get_results_for_execution() 路径保持可用

### M3. Visual Theme

- 新建 `ui/pages/detection_page_assets/result_shell_theme.css`
- 提升 integrated workbench 的信息层次、指标卡、hero、错误提示与文件区视觉质量

Verify:

- 桌面和窄宽度下布局不破
- tab 切换与 chart resize 不回归

## Rollback

如果任一阶段造成 integrated workbench 回归：

1. 保留新文件；
2. 从 `index_galaxy.html` 移除新增脚本/样式引用；
3. 回退到原有 `app_galaxy.js` 渲染逻辑，再缩小接管范围后重试。
