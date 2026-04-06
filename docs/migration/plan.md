# H2OMeta New-Architecture Cutover Plan

## Milestones

1. Freeze cutover contract
2. Remove old config compatibility
3. Remove old workflow aliases
4. Continue UI cutover and shell cleanup
5. Delete confirmed-dead legacy docs and assets
6. Final validation on new-architecture-only path

## Acceptance Rules

- 每个 milestone 完成后必须先验证，再进入下一步。
- 验证失败时先修复，不允许带失败推进。
- 仅删除已迁移且无运行时引用的旧入口/旧文档/旧测试夹具。
- 旧 config / 旧 workflow alias 不允许继续以任何 silent fallback 形式存活。

## Validation Commands

- `python3 -m py_compile config.py core/execution/tool_bridge_specs.py core/execution/tool_bridge_service.py core/execution/tool_bridge_workbench_ops.py tests/test_config_security.py tests/test_single_tool_results.py`
- `cd apps/web && npx tsc --noEmit`
- `npm --prefix apps/web run build`
- Windows: `powershell -ExecutionPolicy Bypass -File .\scripts\m6_windows_regression.ps1`

## Milestone Gates

### M1 Freeze cutover contract
- 文档明确：only v2 config / only new workflow names / only new desktop-web entry。

### M2 Remove old config compatibility
- `normalize_config()` 不再接受旧 schema。
- 旧配置输入直接报错。

### M3 Remove old workflow aliases
- 删除 `legacy_workflow` 与旧 `workflow` 参数映射。
- 新执行与 live view 不再读取 `unknown_detection` 之类旧别名。

### M4 Continue UI cutover
- `projects / runs / history / databases / settings / workbench` 继续作为唯一一级导航。
- 页面结构进一步收敛，不再保留旧控制台术语。
- 当前 M4 子任务执行事实源：
  - `docs/migration/ui-notion-alignment.md`
  - `docs/migration/project-centric-workspace-plan.md`

### M5 Delete confirmed-dead assets
- 只删已无引用、无入口、非 runtime 桥接的旧资产。

### M6 Final validation
- Web build、Windows regression、desktop build 全部继续通过。
