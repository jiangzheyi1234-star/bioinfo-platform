# H2OMeta Workflow-First Migration Plan

## Milestones

1. Freeze workflow-first contract and data model
2. Add workflow/run domain types and API skeleton
3. Implement minimal Nextflow bundle compiler
4. Implement single-node Linux launcher backend
5. Add run monitoring and artifact collection
6. Switch UI/API naming and entrypoints to workflow/run
7. Retire legacy single-tool execution path
8. Final validation on workflow-first path

## Acceptance Rules

- 每个 milestone 完成后必须先验证，再进入下一步。
- 验证失败时先修复，不允许带失败推进。
- 新模型与旧模型并存期间，必须明确谁是主线、谁是 legacy。
- 不允许引入“tool execution / workflow run”双真相。
- 文档更新与代码提交必须同步。

## Validation Commands

- `python3 -m py_compile apps/api/main.py apps/api/models.py core/app_runtime/service.py core/service_locator.py`
- `python3 -m py_compile core/pipeline/project_exporter.py core/pipeline/pipeline_reconstructor.py`
- `cd apps/web && npx tsc --noEmit`
- `npm --prefix apps/web run build`
- Windows: `powershell -ExecutionPolicy Bypass -File .\scripts\m6_windows_regression.ps1`

## Milestone Gates

### M1 Freeze workflow-first contract

- 文档明确新的主线、边界、确定性 profile 默认值。
- `docs/migration/*.md` 全部改成 workflow-first 事实源。

### M2 Add domain types and API skeleton

- 新增 `WorkflowSpec`、`ToolSpec`、`ServerProfile`、`LaunchSpec`、`RunRecord`、`DoctorReport`。
- 新增 workflow/run API 路由骨架，不要求首轮全部接好远端执行。

### M3 Implement minimal bundle compiler

- 能从最小 workflow 输入生成：
  - `main.nf`
  - `nextflow.config`
  - `resolved.config`
  - `params/run.yaml`
  - `params.schema.json`
  - `manifest.json`
- 当前实现要求 compiler 必须读取真实 `tool.yaml`，并使用 `command_template + inputs + outputs + runtime metadata` 编译 process。
- 非法 graph、缺失 runtime 元数据、旧 `~/.h2ometa/conda/envs/...` 硬编码必须直接失败，不允许占位 bundle 或 silent fallback。

### M4 Implement single-node Linux launcher

- 完成 `SSHLocalBackend`。
- 能上传 bundle，并通过后台 launcher 提交一次运行。
- `resume` 必须由 `LaunchSpec.resume` 控制，禁止提交脚本永远写死 `-resume`。
- `doctor` 能完成个人服务器 profile 归类：`personal_docker` / `personal_podman` / `personal_conda`，并保留 `slurm` executor 形状。

### M5 Add monitoring and artifacts

- 能读取并持久化：
  - `.nextflow.log`
  - `trace.txt`
  - `report.html`
  - `timeline.html`
  - `dag.html`
- `RunRecord` 状态和 artifacts API 可用。
- `resolved.config` 路径必须进入 `RunRecord` 并通过 API 可读。

### M6 Switch UI/API to workflow/run

- 新 UI 主导航切到：
  - Workflows
  - Runs
  - Artifacts
  - Settings
- 若导航已收口为单工作台形态，也允许以 `/workspace` 作为统一 workflow/run 主入口，只要新执行不再从 legacy tool execution UI 发起。
- 参数面板改为 JSON Schema 驱动。
- UI 文案不再以 tool execution 为主轴。
- doctor 返回必须包含可直接提交的 `recommended_profile_details`，前端禁止再推断 executor / packaging mode。

### M7 Retire legacy single-tool execution

- `ToolEngine.execute()` 不再接受新执行请求。
- 旧工具 UI、工具目录、descriptor、workbench 配置/历史/result 对外接口全部删除。
- 公开产品面只允许 workflow runs；legacy execution/history 不再作为对外读取语义保留。
- 内部 legacy runtime 若暂时保留，不允许再被任何公开 UI、公开 API、文档主线引用。

### M8 Final validation

- Web build、静态检查、Windows 桌面回归继续通过。
- 单机 Linux workflow bundle 提交、监控、artifact 收集闭环跑通。
