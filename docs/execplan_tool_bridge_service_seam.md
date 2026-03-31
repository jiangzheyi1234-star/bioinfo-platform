# ToolBridge Service Seam ExecPlan

## Goal

将 `core/execution/tool_bridge_service.py` 中残留的两类重逻辑外移：

- 执行编排：`execute_tool()`
- 统一结果构建：`_build_result_view_for_execution()` 及其 single-tool/workflow builders

保持 `ToolBridgeService` 的对外接口、结果 schema、执行语义不变。

## Milestones

### M1. Result View Seam

- 新建 `core/execution/tool_bridge_result_views.py`
- 迁出 unified result dispatch、通用 artifact/table builders、single-tool/workflow builders
- `ToolBridgeService` 仅保留薄 wrapper 或绑定入口

Verify:

- `pytest tests/test_single_tool_results.py`
- `pytest tests/test_ui_smoke.py -k "tool_bridge or results"`

### M2. Execution Orchestration Seam

- 新建 `core/execution/tool_bridge_execution_orchestrator.py`
- 迁出 `execute_tool()` 的 orchestration 流程
- `ToolBridgeService.execute_tool` 直接绑定新模块实现

Verify:

- `pytest tests/test_tool_bridge_database_paths.py tests/test_execution_backend.py`

### M3. Documentation And Guardrails

- 更新 `docs/SYSTEM_ARCHITECTURE.md`
- 新增 seam 归属测试，防止实现回流进 `tool_bridge_service.py`

Verify:

- `pytest tests/test_execution_query_service.py tests/test_task_history_delete.py tests/test_tool_bridge_remote_status.py`

## Rollback

如果任一 milestone 回归失败：

1. 先恢复对应 wrapper/绑定点，不带失败进入下一阶段。
2. 保留新模块草案，缩小迁移范围后重新接入。
