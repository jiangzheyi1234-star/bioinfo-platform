# H2OMeta UI Notion Alignment ExecPlan

## Goal

- 补齐当前 Web UI 对后端 API 的 3 个缺口能力：
  - `GET/POST /api/v1/projects/{project_id}/samples`
  - `GET /api/v1/events/executions`
  - `GET /api/v1/logs/app`
- 在补齐能力的同时，把桌面 Web 工作台整体体验向 Notion Desktop 收敛：
  - 更轻的侧栏
  - 更强的列表/详情结构
  - 更稳定的上下文条与观测面板

## Non-goals

- 不修改后端 API 协议或新增端点。
- 不实现样本编辑/删除。
- 不实现真 SSE；当前后端返回 JSON，前端按轮询处理。
- 不做命令面板、多窗口、拖拽树等超出本次范围的重构。

## Hard Constraints

- 不允许 silent fallback。
- 不保留已删除字段或旧入口的兜底引用。
- 超大文件优先拆分到相邻模块，不继续把新逻辑堆进 `globals.css`。
- 以当前 API/runtime 边界为准，不绕开现有工作台底座。

## Deliverables

- 新增 `/samples` 页面。
- `workbench` 内新增 Observability 区块，包含 `Events` 与 `App Logs`。
- 共享 shell 和全局工作台样式拆分到新样式文件，并统一页面层级与交互语言。

## Milestones

### M1 Shell and style foundation
- 扩展主导航，加入 `samples`。
- 引入新的 workspace 样式文件，承接 Notion-like shell/list/detail/dock 风格。
- 保持现有页面可用，不回归。

### M2 Samples page
- 新增 `Sample` 类型、解析器、页面状态和创建表单。
- 使用共享 shell 承载样本列表与详情/创建双栏。

### M3 Workbench observability
- 新增 `Events` / `App Logs` 观测面板。
- 事件采用增量轮询；日志支持 `tail_lines` 刷新。

### M4 Polish and consistency
- 收敛样本页、工作台和主 shell 的排版、空态、筛选区、选中态和提示信息。

## Acceptance Criteria

### M1
- 侧栏显示 `projects / samples / runs / history / databases / settings / workbench`
- 快捷键与侧栏顺序一致
- 新样式不破坏现有页面路由

### M2
- 可以在已选项目下加载样本列表
- 可以创建样本并在当前页看到刷新结果
- metadata JSON 非法时明确报错

### M3
- `Events` 可加载、增量刷新、过滤失败事件
- `App Logs` 可加载、切换 tail 行数、处理空日志
- workbench 既有 config/history/result 流程不回归

### M4
- 样式语言在样本页和工作台中保持一致
- 空态、错误态、过滤栏、列表选中态统一

## Validation Checks

- `cd apps/web && npx tsc --noEmit`
- `npm --prefix apps/web run build`
- 手工检查以下路由：
  - `/projects`
  - `/samples`
  - `/runs`
  - `/history`
  - `/databases`
  - `/settings`
  - `/workbench`

## Stop-and-fix Rule

- 每完成一个 milestone，先做对应验证。
- 验证失败先修复，不允许带着失败推进。

## Decisions Made

- `samples` 使用独立一级页面。
- `events` 与 `logs` 不新增一级导航，统一并入 `workbench` 观测层。
- “向 Notion Desktop 对齐” 的范围限定为结构、视觉与关键交互，不复制品牌资产。
- 当前 `events` 端点按 JSON polling 处理，不假设已升级为真正 SSE。

## Current Status

- 2026-04-06: Plan frozen，开始执行 M1。
- 2026-04-06: M1-M4 code landed。
- 2026-04-06: `cd apps/web && npx tsc --noEmit` 通过。
- 2026-04-06: `npm --prefix apps/web run build` 通过。

## Known Follow-ups

- 若后端未来把 `events` 升级为真正 SSE，可把 polling 改为 EventSource。
- 若后端新增样本编辑/删除 API，再扩展样本页的详情操作区。
