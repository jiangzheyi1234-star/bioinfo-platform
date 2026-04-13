# H2OMeta Workflow-First Migration Prompt

## Goal

完成执行主线迁移，使 H2OMeta 从当前的单工具远端执行器切换为：

- `Tauri` 桌面壳
- 静态导出的 `Next.js` UI
- 本地 `FastAPI` sidecar
- 纯 Python `core/`
- 远端 `SSH launcher backend`
- `WorkflowSpec -> Nextflow bundle -> run monitor` 主线

首期目标是跑通 **个人服务器 / 单机 Linux** 的 workflow bundle 编译、上传、启动、监控和结果收集闭环，同时把 HPC 形状固化到架构与数据模型中。

## Hard Constraints

- 失败必须大声抛出，禁止 silent fallback。
- SSH 访问必须复用 `core/remote/ssh_service.py`，远程命令只允许走 `SSHService.run(cmd, timeout)`。
- 长任务不能绑在主线程；本地控制面和远端 launcher 都必须通过既有线程/后台机制执行。
- 桌面端只做控制面，不承担 workflow 执行面。
- Nextflow 自身安装优先 self-install 或 standalone，不以 Conda 作为主安装路径。
- 服务器 bootstrap 只安装运行时，不安装业务工具。
- 业务工具依赖统一由 workflow 的 `container` / `conda` directive 决定。
- 同一 run 只允许一种 packaging mode，不混用 container 与 conda。
- 参数面板必须以 JSON Schema 为唯一真相源。
- 现有 `ToolEngine`/单工具执行系统不再承载新执行，只允许作为迁移期 legacy 读取来源。

## Deterministic Defaults

- 个人服务器 profile 顺序固定为：`Docker -> Podman -> micromamba/conda`
- HPC profile 顺序固定为：`Apptainer -> micromamba/conda`
- 首期远端目标环境：`单机 Linux`
- 首期执行标准：`Nextflow`
- 首期数据上传策略：桌面端继续允许统一中转输入数据

## Deliverables

- 一组新的 workflow-first 领域模型：
  - `WorkflowSpec`
  - `ToolSpec`
  - `ServerProfile`
  - `LaunchSpec`
  - `RunRecord`
  - `DoctorReport`
- 一条新的 bundle 编译链：
  - `WorkflowSpec -> Nextflow bundle`
- 一组新的 workflow/run API：
  - doctor / compile / submit / query / cancel / artifacts / resolved-config
- 一条新的单机 Linux launcher 主线：
  - upload bundle
  - `nextflow run ... -bg`
  - 读取 `.nextflow.log`、`trace.txt`、`report/timeline/dag`
- 一套新的 UI 主线：
  - Workflows
  - Runs
  - Artifacts
  - Settings
- 文档事实源与迁移实际状态一致

## Done When

- 能从最小 `WorkflowSpec` 编译出完整 Nextflow bundle。
- 能对单机 Linux 成功执行一次 `nextflow run`。
- 能持久化 `RunRecord` 并展示运行状态。
- 能读取 `.nextflow.log`、`trace.txt`、`report.html`、`timeline.html`、`dag.html`。
- 参数面板来自 `params.schema.json`，不再手写定义。
- 新执行不再走 `ToolEngine.execute()` 主路径。
- 文档、API 和 UI 命名全部围绕 workflow/run，而不是 tool execution。
