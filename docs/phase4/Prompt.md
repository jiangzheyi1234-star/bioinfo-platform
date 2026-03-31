# Phase 4 Prompt

先阅读：

- `AGENTS.md`
- `docs/结果工作台2026分阶段改造方案.md`
- `docs/phase4/Prompt.md`
- `docs/phase4/Plan.md`
- `docs/phase4/Implement.md`
- `docs/phase4/Documentation.md`

这次请严格按 ExecPlan / 长时程任务方式执行：

- 以 `docs/phase4/Plan.md` 为唯一事实来源。
- 以 `docs/phase4/Implement.md` 作为执行手册。
- 持续更新 `docs/phase4/Documentation.md`，作为状态、决策、发现、验证、复盘的共享记忆。
- 每完成一个 milestone，必须立刻运行该 milestone 对应验证。
- 验证失败必须先修复，不允许带着失败进入下一 milestone。
- 保持 diff 收敛，禁止顺手扩 scope。
- 所有验收必须用可观测行为表述，不要只汇报“改了什么代码”。

当前状态：

- Phase 1 已完成。
- Phase 2 已完成。
- Phase 3 已完成。
- typed result UX 已落地。
- 当前进入 Phase 4：Data Cockpit 视觉重设。

本次目标：

- 严格基于 `docs/结果工作台2026分阶段改造方案.md` 执行 Phase 4。
- 不跨到 Phase 5。
- 先核对当前 Phase 3 基线，再实施视觉系统收口。
- 优先建立 typography / spacing / state token / card tier / button system。
- 在现有正确职责划分之上做视觉升级，不重写 execution 旅程。

硬边界：

- 不改 `ToolEngine.execute()`。
- 不改 SSH / `SSHService.run()` / `JobDispatcher`。
- 不改 execution 状态枚举。
- 不改持久化状态。
- 不 silent fallback。
- 不重写结果协议 / bridge API / `tool.yaml` / artifact manifest。
- 不破坏现有 `history -> completed -> results` 主通路。

Phase 4 验收重点：

- `history`、`hero`、`summary` 共用统一状态 token。
- typography / spacing 不再跨模块漂移。
- 主结果 viewer 优先级清晰。
- `files` / `provenance` 次级化。
- 不引入新的语义混乱。

交付要求：

- 先汇报当前基线是否满足进入 Phase 4。
- 实施过程中持续更新 `docs/phase4/Documentation.md`。
- 最终汇报：通过了哪些 milestone、执行了哪些验证、还有哪些已知问题。
