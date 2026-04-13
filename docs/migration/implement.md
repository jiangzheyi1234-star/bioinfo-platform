# H2OMeta Workflow-First Migration Implement

## Execution Rules

- 以 `docs/migration/plan.md` 为当前执行事实源。
- 严格按 milestone 推进：`Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat`。
- 每完成一个 milestone，必须先验证并修复失败，再进入下一步。
- 新主线必须围绕 workflow/run 建模，不允许继续扩展 tool-centric 主执行路径。
- 当目标文件已超过 600 行时，优先提取相邻新模块，原文件只保留门面和绑定点。
- 保持 diff scoped，不在同一提交里同时混入 UI 重设计、API 大改和后端远端执行重写。

## Architecture Rules

- `apps/desktop` 只做壳、资源、sidecar 生命周期和权限收敛。
- `apps/web` 只做静态 UI，不再承载业务后端逻辑。
- `apps/api` 是唯一控制面后端。
- `core/` 必须拆成：
  - domain
  - compiler
  - runtime
  - backends
  - registry
- 远端 workflow 主路径不用 `screen/tmux` 作为执行器；单机 Linux 首期使用 `nextflow run ... -bg`。

## Verification Rules

- 每个 milestone 至少补一条静态验证。
- 影响 API 或 bundle 输出时，优先加最小 smoke path，再扩 UI。
- 影响 profile/launcher 时，必须检查错误是否显式暴露，禁止 silent fallback。

## Documentation Rules

- `prompt.md`：目标、约束、done when
- `plan.md`：milestones、验证、gate
- `documentation.md`：当前状态、决策、已知问题
- 每次 milestone 完成后立即更新 `documentation.md`
