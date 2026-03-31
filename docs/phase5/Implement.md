# Phase 5 Implementation Guide

## Working Rules

- 只实现 `docs/phase5/Plan.md` 中定义的 milestone。
- 先核对 Phase 4 稳定基线，再进入任何 backend 或 metadata 改造。
- 每完成一个 milestone，立即运行该 milestone 对应验证。
- 验证失败先修复，不允许带着失败进入下一 milestone。
- 全程持续更新 `docs/phase5/Documentation.md`。
- 所有结论优先用可观测行为表述，而不是类名、函数名或“抽象更好了”。

## Change Strategy

1. 先分离责任，再加抽象：
   先明确现有 command execution 事实职责，再建立 `ExecutionBackend` 接口。
2. 默认实现先显式化：
   先把 `CommandBackend` 变成显式默认实现，再考虑其他 backend。
3. metadata 先增量：
   richer typed artifact metadata 先增量扩展，不删旧字段。
4. 新入口后置：
   单独 execution detail 页面只能在 backend seam 和 metadata 稳定后再评估。
5. 失败必须显式：
   capability 不足、metadata 缺失、backend 不支持时必须显式报错，禁止 silent fallback。

## Required Inventory Before Editing

开始 Phase 5 前，至少盘点并记录到 `Documentation.md`：

- 当前 execution 提交、查询、结果目录定位分别落在哪些服务
- 当前 artifact manifest 与前后端消费的关键字段
- 结果工作台哪些行为依赖现有 command-style execution 假设
- 哪些点未来可能切换到 `NextflowBackend`，哪些点绝不能提前动

## Preferred Edit Order

建议按以下顺序实施：

1. Phase 4 稳定性复验
2. `ExecutionBackend` seam 设计与默认实现落点
3. richer typed artifact metadata 扩展
4. backend adapter capability 边界
5. execution detail 入口评估
6. 补充或更新契约测试与 smoke 护栏

## Explicit Non-Goals

以下内容不在 Phase 5 默认范围内，不要顺手扩 scope：

- 重写现有 UI 旅程
- 重做 server
- 引入 agent 自动编排层
- 新增 execution 持久化状态但不带迁移
- 绕开 `SSHService.run()` 或线程安全基线
- 把 `NextflowBackend` 直接设为默认执行路径

## Validation Discipline

- 基线核对后先跑 Phase 4 定向回归，再开始 Phase 5 实施。
- 每个 milestone 完成后立刻执行对应验证。
- 若新增 backend 契约测试，必须覆盖：
  - 默认 `CommandBackend` 行为不变
  - capability 不足显式报错
  - 结果工作台主通路不回归
- 最终提交前至少复跑：
  - `pytest tests/test_ui_smoke.py tests/test_single_tool_results.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`
  - 以及 Phase 5 新增的 backend / metadata 契约测试

## Documentation Discipline

`docs/phase5/Documentation.md` 必须持续更新，至少记录：

- 当前正在执行哪个 milestone
- 为什么做出当前抽象或 metadata 决策
- 跑了哪些验证
- 失败点是什么
- 如何修复
- 是否已复验通过
- 哪些项被明确 defer，为什么 defer
