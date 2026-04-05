# Workbench V3 Implement Rules

1. `plan.md` 是本任务唯一执行事实来源，按 milestone 逐段推进。
2. 每段改动后先做静态校验；失败必须先修复再进入下一段。
3. 默认流程固定为：`Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs`。
4. 运行入口与结果展示必须分离；禁止恢复旧执行卡片兜底。
5. 保持历史结果操作闭环：打开、固定、取消固定、关闭、清理未固定。
6. 统一结果壳层字段优先，禁止静默 fallback 到已删除字段。
7. 测试约束遵循仓库 AGENTS：不在当前环境执行 `pytest`。
