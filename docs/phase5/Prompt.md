# Phase 5 Prompt

先阅读：

- `AGENTS.md`
- `docs/结果工作台2026分阶段改造方案.md`
- `docs/phase5/Prompt.md`
- `docs/phase5/Plan.md`
- `docs/phase5/Implement.md`
- `docs/phase5/Documentation.md`

这次请严格按 ExecPlan / 长时程任务方式执行：

- 以 `docs/phase5/Plan.md` 为唯一事实来源。
- 以 `docs/phase5/Implement.md` 作为执行手册。
- 持续更新 `docs/phase5/Documentation.md`，作为状态、决策、发现、验证、复盘的共享记忆。
- 每完成一个 milestone，必须立刻运行该 milestone 对应验证。
- 验证失败必须先修复，不允许带着失败进入下一 milestone。
- 保持 diff 收敛，禁止把多个可选增强揉成一次大改。
- 所有验收必须用可观测行为表述，不要只汇报“改了什么代码”。

当前状态：

- Phase 1 已完成。
- Phase 2 已完成。
- Phase 3 已完成。
- Phase 4 已完成并通过结果工作台定向回归。
- 当前准备进入 Phase 5：后续可选增强。

本次目标：

- 严格基于 `docs/结果工作台2026分阶段改造方案.md` 执行 Phase 5。
- 先确认 Phase 4 已稳定，再开始 Phase 5。
- 第一优先级是建立 `ExecutionBackend` 抽象的落点与迁移边界。
- 第二优先级是 richer typed artifact metadata 的最小落地。
- `CommandBackend / NextflowBackend` 只在抽象边界稳定后再接入。
- 单独 execution detail 页面仅在前面两项稳定后再评估。

硬边界：

- 不把当前 UI 自洽问题转嫁到“换 backend”“接 agent”“重做 server”上。
- 不在同一个 milestone 同时做 backend 抽象、metadata 扩展、独立详情页三件事。
- 不新增 execution 持久化状态，除非计划和迁移明确写入并先被接受。
- 不 silent fallback。
- 不绕开 `SSHService.run()`、`JobDispatcher`、现有线程安全约束。
- 不破坏现有 `history -> completed -> results` 主通路。

Phase 5 验收重点：

- `ExecutionBackend` 抽象存在明确接口与 CommandBackend 落点。
- richer typed artifact metadata 不破坏现有结果协议消费。
- 新 backend 或 metadata 失败时显式报错，不 silent fallback。
- 任何新入口都建立在 Phase 1-4 已稳定的 execution 旅程之上。

交付要求：

- 先汇报当前基线是否满足进入 Phase 5。
- 实施过程中持续更新 `docs/phase5/Documentation.md`。
- 最终汇报：通过了哪些 milestone、执行了哪些验证、还有哪些已知问题。
