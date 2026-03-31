# Phase 5 Working Memory

## Current Status

- State: Phase 5 milestones 0-4 completed for the scoped optional enhancements in this round.
- Plan owner: `docs/phase5/Plan.md`
- Product source of truth: `docs/结果工作台2026分阶段改造方案.md`
- Execution guide: `docs/phase5/Implement.md`
- Shared memory file: this document

## Completed Milestones

- Milestone 0: Phase 4 Stability Gate + Inventory.
- Milestone 1: Freeze `ExecutionBackend` seam.
- Milestone 2: Richer typed artifact metadata.
- Milestone 3: Backend adapter preparation.
- Milestone 4: Standalone execution detail evaluation.

## Decisions Made

- Phase 5 only covers optional enhancements defined by the canonical 2026 results-workbench plan.
- Phase 5 must start from a proven-stable Phase 4 baseline.
- The recommended order is:
  - `ExecutionBackend` seam
  - richer typed artifact metadata
  - backend adapter preparation
  - standalone execution detail evaluation
- `CommandBackend` remains the default path until a later milestone explicitly proves otherwise.
- `NextflowBackend` must not silently take over the existing execution journey.
- `ToolEngine.execute()` external behavior, execution status enum, `SSHService.run()` queue discipline, and `history -> completed -> results` remain frozen boundaries for Phase 5.
- `ExecutionBackend` seam will only cover execution substrate behavior: prepare, dispatch, waiter handoff, and result-location description.
- Richer artifact metadata must be additive only; existing artifact consumers keep reading the current five core fields.
- `CommandBackend` is now the explicit default backend implementation for the current command-style execution journey.
- `NextflowBackend` is introduced only as a capability placeholder and loudly rejects unsupported operations.
- Artifact metadata now supports additive typed fields:
  - `artifact_type`
  - `display_role`
  - `viewer_hint`
- Artifact metadata validation is strict:
  - missing typed metadata is normalized from filename heuristics
  - invalid typed metadata raises explicit errors instead of silently falling back
- Standalone execution detail page is deferred because the current `history -> completed -> results` journey already covers the supported Phase 5 scope without introducing a parallel page model.

## Validation Log

- Milestone 0 / Phase 4 stability gate:
  - Command: `pytest tests/test_ui_smoke.py tests/test_single_tool_results.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`
  - Result: `80 passed`
  - Observable acceptance:
    - 当前结果工作台仍能从 `history` 将 `completed execution` 打开到统一结果壳。
    - 现有 typed result UX 与 Phase 4 Data Cockpit 视觉回归仍成立。
    - `get_results_for_execution()` 与 history/status 主通路未出现行为漂移。
- Milestone 1-3 execution/backend + artifact regression:
  - Command: `pytest tests/test_execution_backend.py tests/test_tool_engine.py tests/test_service_locator.py tests/test_job_dispatcher.py tests/test_artifact_store.py tests/test_single_tool_results.py tests/test_ui_smoke.py tests/test_execution_query_service.py tests/test_tool_bridge_remote_status.py`
  - Result: `152 passed`
  - Observable acceptance:
    - 提交 execution 后仍沿用同一条 `history -> completed -> results` 旅程，没有因为 backend seam 改造丢失结果壳入口。
    - 默认 command execution 仍通过原有 prepare / dispatch / waiter handoff 完成提交，`JobDispatcher.start_waiting()` 仍由 `ServiceLocator` 的主线程接线点收口。
    - completed execution 仍能加载统一结果壳，Phase 1-4 的结果协议消费没有回归。
    - richer artifact metadata 存在时会被标准化为显式 viewer / role 信息；metadata 非法时会显式报错，不会静默改走未声明路径。
    - `NextflowBackend` 当前不会接管默认执行链路，未实现能力会直接返回显式不支持错误。
- Post-milestone metadata persistence repair:
  - Issue: `persist_execution_artifacts()` rebuilt manifest items without carrying explicit `artifact_type` / `display_role` / `viewer_hint`, which could rewrite persisted metadata back to filename heuristics after reload.
  - Repair: persisted manifest items now preserve explicit typed metadata before writing `artifacts_manifest.json`.
  - Command: `pytest tests/test_artifact_store.py`
  - Result: `5 passed`
  - Observable acceptance:
    - 调用方显式提供 richer typed artifact metadata 后，execution manifest reload 仍保持同一组 metadata。
    - artifact 排序与 viewer 选择不会在 reload 后被静默改写回启发式默认值。

## Inventory

- Execution submit journey:
  - `ToolEngine.execute()` merges parameters, writes `pending` execution record, and emits a `PreparationRequest`.
  - `ServiceLocator._schedule_preparation()` delegates async preparation to `ExecutionPreparer.prepare()`.
  - `prepare_execution()` creates remote output dir, uploads workflow assets when needed, and builds the command payload.
  - `ServiceLocator._dispatch_job()` currently wraps command execution and calls `JobDispatcher.submit()`.
  - `ServiceLocator._on_dispatch_submitted()` currently performs the main-thread `JobDispatcher.start_waiting()` handoff.
- Execution query journey:
  - `ExecutionQueryService` provides history rows for UI consumption.
  - `ToolBridgeService.get_execution_history()` remains the history entrypoint.
  - `ToolBridgeService.get_results_for_execution()` only accepts `completed` executions and loudly returns errors for non-completed or malformed results.
- Result directory and artifact protocol:
  - `ToolEngine._download_execution_artifacts()` writes `results/<execution_id>/artifacts_manifest.json`.
  - `ArtifactStore` and `ToolBridgeService._build_execution_result_context()` currently depend on manifest `output_dir` plus artifact fields `name`, `remote_path`, `local_path`, `available`, and `error`.
- Phase 5 frozen boundaries:
  - Do not change `ToolEngine.execute()` external semantics.
  - Do not bypass `SSHService.run()` or `JobDispatcher`.
  - Do not move `JobDispatcher.start_waiting()` off the current main-thread handoff.
  - Do not add execution persistent states.
  - Do not break the existing `history -> completed -> results` journey.

## Implementation Notes

- Milestone 1:
  - Added an explicit backend seam under `core/execution/execution_backend.py`.
  - `ExecutionPreparer` now delegates preparation work through the configured backend.
  - `ServiceLocator` now routes dispatch and waiter handoff through `CommandBackend`, while preserving the current thread and signal model.
- Milestone 2:
  - `ArtifactStore.normalize_artifacts()` now preserves the existing five core fields and normalizes additive typed metadata.
  - `ToolEngine._download_execution_artifacts()` now persists typed metadata into the execution manifest.
  - Results UI artifact ordering now prefers explicit typed metadata when deciding which files should surface first.
- Milestone 3:
  - Added backend contract tests for `CommandBackend`.
  - Added a loud-fail `NextflowBackend` placeholder to establish capability boundaries without changing the default execution path.
- Milestone 4:
  - Decision: `defer`.
  - Reason: current history/results journey already covers the supported execution detail needs, and adding a standalone detail page now would expand scope beyond the validated backend seam + metadata work.

## Known Issues / Deferred Items

- Standalone execution detail page remains deferred after evaluation in this round.
- Any future agent-assist layer is explicitly post-Phase-5 and should not be pulled into backend work by default.
- `NextflowBackend` is intentionally not production-ready in this round; only its capability boundary is established.

## Recovery Notes

- If a milestone fails validation, stop progression and repair within the current milestone scope.
- Prefer rolling back new abstraction wiring before undoing already-stable Phase 1-4 behavior.
- Do not recover by introducing silent fallback or by weakening current result-shell semantics.
