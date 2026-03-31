# Phase 5 ExecPlan: Execution Platform Optional Enhancements

## Summary

本计划只执行 `docs/结果工作台2026分阶段改造方案.md` 中的 Phase 5：后续可选增强。

- 唯一产品方案来源：`docs/结果工作台2026分阶段改造方案.md`
- 唯一执行计划来源：本文档
- 执行手册：`docs/phase5/Implement.md`
- 共享记忆：`docs/phase5/Documentation.md`

完成定义：

- Phase 5 全部已启动的 milestone 完成并记录到 `Documentation.md`
- 每个 milestone 对应验证已执行且通过
- 所有验收使用可观测行为描述
- Phase 5 不回退或污染 Phase 1-4 已稳定的结果工作台旅程

## Confirmed Baseline

- Phase 1-4 已完成，结果工作台当前具备稳定的 execution 路由、统一结果壳、typed result UX 与 Data Cockpit 视觉系统。
- `history -> completed -> results` 是现有唯一主通路，Phase 5 必须建立在这个前提上。
- 当前主方案将 Phase 5 定义为“前 1-4 稳定后再评估”的可选增强，而不是一次性大改。

进入 Phase 5 的基线核对必须确认以下行为仍成立：

- Phase 4 的定向回归仍通过
- 结果协议当前消费者仍全部工作
- 当前执行链路没有新增主线程 SSH 调用
- 当前 execution 状态枚举和持久化状态没有漂移

## Hard Boundaries

- 不把 UI 语义问题转嫁为 backend 重写
- 不在同一 milestone 同时推进多个大主题
- 不 silent fallback
- 不绕开 `SSHService.run()`、`JobDispatcher`、QThread/Worker 约束
- 不破坏现有 `history -> completed -> results` 主通路
- 不新增 execution 持久化状态，除非迁移计划先落文档并单独验收

## Recommended Sequence

- 先做 `ExecutionBackend` 抽象
- 再做 richer typed artifact metadata
- 再做 `CommandBackend` 适配与 `NextflowBackend` 预留
- 最后才评估单独 execution detail 页面或 agent 辅助层

## Milestones

### Milestone 0: Phase 4 Stability Gate

目标：

- 确认仓库仍满足进入 Phase 5，不在回归基线上继续抽象。

执行：

- 复核 Phase 4 文档与结果工作台当前状态。
- 将“是否满足进入 Phase 5”的结论写入 `Documentation.md`。

可观测验收：

- `Documentation.md` 明确记录：Phase 4 稳定、允许进入 Phase 5，或明确阻塞项。

必跑验证：

- `pytest tests/test_ui_smoke.py tests/test_single_tool_results.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`

### Milestone 1: Freeze ExecutionBackend Seam

目标：

- 在不改变现有行为的前提下，定义 execution backend 抽象边界。

执行：

- 盘点当前 command-style execution 行为由哪些服务和 builder 共同承担。
- 定义 `ExecutionBackend` 的最小职责：
  - 提交执行
  - 查询运行态
  - 定位结果目录 / 产物
  - 回传执行错误
- 先让 `CommandBackend` 成为现有链路的显式实现，而不是隐式散落逻辑。

可观测验收：

- backend 抽象存在统一入口，且默认运行行为仍与当前 command execution 一致。
- 结果工作台现有 execution 查询与结果展示行为不变。

必跑验证：

- 执行状态查询与结果桥接相关测试
- 至少一组从提交到结果读取的定向 smoke

### Milestone 2: Richer Typed Artifact Metadata

目标：

- 让 artifact 元数据更可类型化，但不破坏当前协议消费者。

执行：

- 盘点当前 artifact manifest、结果 builder、结果壳前端消费之间的字段关系。
- 为 artifact 增加更明确的类型信息、显示角色或 viewer 提示字段。
- 保持旧字段继续可读，禁止删除仍被前端依赖的字段引用。

可观测验收：

- 结果页能够基于 richer metadata 做更明确的 viewer / utility 区分，且现有工具结果不回归。
- 缺失 metadata 时显式报错或显式降级到已定义的旧字段，不 silent fallback 到不存在字段。

必跑验证：

- `tests/test_single_tool_results.py`
- 与 artifact manifest / bridge service 相关的定向测试

### Milestone 3: Backend Adapter Preparation

目标：

- 在已有 backend seam 上，为 `CommandBackend / NextflowBackend` 建立安全接入点。

执行：

- 保持 `CommandBackend` 为默认实现并补齐契约测试。
- `NextflowBackend` 只建立接口与 capability 边界，不默认接管现有 execution 流程。
- 明确哪些能力在未实现前必须显式报错。

可观测验收：

- 默认 command execution 无行为变化。
- backend capability 不足时返回显式错误，而不是静默切回其他未声明路径。

必跑验证：

- backend 契约测试
- command execution 主通路回归测试

### Milestone 4: Standalone Execution Detail Evaluation

目标：

- 只在前 3 个 milestone 稳定后，再评估是否值得引入独立 execution detail 页面。

执行：

- 先做信息架构评估，不默认落代码。
- 若决定实施，独立详情页只能作为 history / results 的补充入口，不能替换现有主通路。

可观测验收：

- 若不实施，`Documentation.md` 记录明确的 defer 结论。
- 若实施，history / results 主通路仍保持当前优先级。

必跑验证：

- history 导航与 results 主通路 smoke
- 新入口相关的最小 UI smoke

## Recovery And Rollback Rules

- 每完成一个 milestone，立即运行对应验证并更新 `Documentation.md`。
- 若验证失败，先修复当前 milestone 范围内问题，再继续。
- 回退优先级：
  - 先回退新增抽象接线
  - 再回退新增 metadata 字段消费
  - 不回退 Phase 1-4 已稳定的结果壳职责与主通路
- 若 scope 漂移，立即停止扩展，把未完成项记录到 `Documentation.md` 的 deferred items。
