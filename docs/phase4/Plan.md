# Phase 4 ExecPlan: Data Cockpit Visual Consolidation

## Summary

本计划只执行 `docs/结果工作台2026分阶段改造方案.md` 中的 Phase 4：Data Cockpit 视觉重设。

- 唯一产品方案来源：`docs/结果工作台2026分阶段改造方案.md`
- 唯一执行计划来源：本文档
- 执行手册：`docs/phase4/Implement.md`
- 共享记忆：`docs/phase4/Documentation.md`

完成定义：

- Phase 4 全部 milestone 完成并记录到 `Documentation.md`
- 每个 milestone 对应验证已执行且通过
- 所有验收使用可观测行为描述
- 未跨入 Phase 5，未触碰硬边界

## Confirmed Baseline

- 主方案已记录 Phase 1、Phase 2、Phase 3 完成。
- typed result UX 已落地，当前结果工作台已存在固定的 `Overview / Result / Files / Provenance` 结构。
- 现有 smoke 已覆盖 integrated shell 基线，包含 history 进入 completed execution 的主通路与结果壳结构。
- Phase 4 主要落点应为：
  - `ui/pages/detection_page_assets/styles_galaxy.css`
  - 必要时轻调 `ui/pages/detection_page_assets/index_galaxy.html`
- 本阶段不应重写 execution 旅程，不应回退 typed result UX，不应变更结果协议或执行链路。

进入 Phase 4 的基线核对必须确认以下行为仍成立：

- `history -> completed -> results` 主通路可用
- completed execution 从 history 进入时仍然以统一结果壳为主
- `Overview / Result / Files / Provenance` 仍为固定结果页结构
- typed result UX 仍按现有 archetype / viewer 语义工作

## Hard Boundaries

- 不改 `ToolEngine.execute()`
- 不改 SSH / `SSHService.run()` / `JobDispatcher`
- 不改 execution 状态枚举或持久化状态
- 不 silent fallback
- 不重写结果协议 / bridge API / `tool.yaml` / artifact manifest
- 不破坏现有 history、completed、results 主通路
- 不把 Phase 4 问题转嫁到 backend、agent、server 重做
- diff 必须收敛在 Phase 4 视觉系统与其必要护栏

## Milestones

### Milestone 0: Phase 3 Baseline Check

目标：

- 确认当前仓库状态满足进入 Phase 4，不在错误基线上做视觉升级。

执行：

- 核对主方案中 Phase 2、Phase 3 的已完成结论。
- 核对 integrated shell、typed result UX、history -> completed -> results 主通路现状。
- 将“当前基线是否满足进入 Phase 4”的结论写入 `Documentation.md`。

可观测验收：

- `Documentation.md` 明确记录：基线满足进入 Phase 4，或明确指出阻塞项。
- 若存在阻塞项，后续 milestone 不启动。

必跑验证：

- 运行结果工作台相关定向测试，至少覆盖：
  - `tests/test_ui_smoke.py`
  - `tests/test_single_tool_results.py`
  - `tests/test_execution_query_service.py`
  - `tests/test_tool_bridge_remote_status.py`

失败处理：

- 若基线测试失败，先修复或明确记录阻塞原因，不允许进入 Milestone 1。

### Milestone 1: Visual Token Inventory And Consolidation

目标：

- 先收口视觉系统，再替换局部样式，避免模块各自漂移。

执行：

- 盘点现有 typography、spacing、state、card、button 的漂移点。
- 定义统一 token 映射与使用规则。
- 优先用 token 化表达新的视觉语言，再进行局部替换。

可观测验收：

- typography scale 有统一来源，不再由各模块各自定义。
- spacing scale 有统一来源，不再出现跨模块明显漂移。
- history、hero、summary 所需状态色与状态层级可由统一 token 表达。
- 新旧混杂 token 若暂时并存，保留清晰迁移边界，不形成新的语义混乱。

必跑验证：

- 运行与资产结构、结果工作台行为相关的 smoke / 定向测试。
- 人工核对关键页面是否仍保持既有结构与交互入口。

失败处理：

- 若 token 收口造成结构或行为回归，保留新命名与新组织，回退局部 token 值，先恢复行为正确性。

### Milestone 2: Shared State Language For History, Hero, Summary

目标：

- 让 history、execution hero、summary cards 使用一致的状态语言与层级。

执行：

- 统一状态 token、状态 badge / chip / card 的层级规则。
- 将 history 从“功能堆叠折叠列表”推进到更清晰的 run list card 表达。
- 保持结果页职责不变，只调整视觉表达与信息节奏。

可观测验收：

- history、hero、summary 共用统一状态 token。
- 同一 execution 状态在不同区域的颜色、强调级别、文字语气保持一致。
- history 更接近 run list card，而不是功能堆叠折叠列表。

必跑验证：

- 运行结果工作台相关定向测试。
- 人工核对 history、hero、summary 的状态表现是否一致。

失败处理：

- 若局部统一导致信息辨识度下降，允许回退视觉细节，但不得回退到多套状态语义并存。

### Milestone 3: Primary Viewer Hierarchy Consolidation

目标：

- 在不改变现有 typed result 语义的前提下，强化主结果 viewer，压低 files / provenance 权重。

执行：

- 重排 primary / supporting / utility 层级的视觉权重。
- 优先强化 execution hero、summary rhythm、main result viewer。
- 让 `files` / `provenance` 清晰退居次级，不与 primary viewer 竞争注意力。

可观测验收：

- 主结果 viewer 优先级清晰。
- `files` / `provenance` 次级化。
- `Overview` 与 `Result` 的主次层级清楚，不引入新的语义混乱。
- 新视觉建立在正确职责划分之上，而不是旧语义换皮。

必跑验证：

- 运行结果工作台相关定向测试。
- 人工核对典型工具视图：
  - `blastn` 表格主视图仍清晰
  - `fastp` summary + chart/html 仍清晰
  - `prokka` summary + table + files 仍清晰

失败处理：

- 若主次重排影响现有 archetype/viewer 语义，优先恢复 viewer 语义正确性，再收敛视觉层级。

### Milestone 4: Regression And Smoke Guardrails

目标：

- 用现有测试与必要新增 smoke 护栏锁住 Phase 4 回归风险。

执行：

- 复用现有结果工作台相关测试作为主回归集合。
- 只在 Phase 4 风险面补充必要的 UI smoke 护栏。
- 将全部验证结果、失败修复、最终状态更新到 `Documentation.md`。

可观测验收：

- 提交前已跑完结果工作台相关定向测试。
- 若新增 smoke，新增内容只覆盖 Phase 4 风险面。
- `Documentation.md` 完整记录每次验证、失败、修复、复验结果。

必跑验证：

- `pytest tests/test_ui_smoke.py tests/test_single_tool_results.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`
- 根据实际改动补充必要的 UI smoke 护栏并执行对应测试。

失败处理：

- 验证失败先修复并复验，不允许以“仅文档记录已知失败”方式结束本计划。

## Recovery And Rollback Rules

- 每完成一个 milestone，立即运行对应验证并更新 `Documentation.md`。
- 若验证失败，先修复当前 milestone 范围内问题，再继续。
- 回退优先级：
  - 先回退局部视觉 token 值
  - 再回退局部视觉层级调整
  - 不回退正确的职责划分与 typed result UX 语义
- 若出现 scope 漂移，立即停止扩展，把未完成项记录到 `Documentation.md` 的 deferred items。
