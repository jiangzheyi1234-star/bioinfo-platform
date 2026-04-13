# H2OMeta Workflow-First Migration Documentation

## Current Status

- 已冻结新的产品主线：`Tauri + static Next.js + FastAPI sidecar + Python core + SSH launcher backend`
- 已冻结新的执行模型：`WorkflowSpec -> Nextflow bundle -> run monitor`
- 已冻结新的确定性 profile 顺序：
  - 个人服务器：`Docker -> Podman -> micromamba/conda`
  - HPC：`Apptainer -> micromamba/conda`
- 首期目标固定为：跑通单机 Linux / 个人服务器 workflow bundle 主线

## Decisions

- 桌面端只做控制面，不承担 workflow 执行面。
- Nextflow 是首期唯一执行标准；WDL/CWL 只做未来导出预留。
- 业务工具不再做服务器级预装，统一交给 workflow 的 `container` / `conda` directive。
- 参数面板必须以 JSON Schema 为唯一真相源。
- 现有 `ToolEngine` / 单工具执行系统不再承载新执行，将逐步退役。
- 首期继续允许桌面端统一中转输入数据，后续再收敛到远端路径/对象存储优先。

## Current Milestone

- 当前进入 `M1 Freeze workflow-first contract` 到 `M2 Add domain types and API skeleton` 之间的切换阶段。
- 当前优先级：
  - 先立数据模型与 API 骨架
  - 再做 bundle 编译最小闭环
  - 再接单机 Linux launcher

## Known Risks

- 当前仓库明显是 tool-centric，迁移时最容易出现“双真相”并存。
- 现有 UI、API、runtime、service locator 都围绕单工具执行设计，切主线时必须分阶段替换。
- 桌面端统一中转大文件不是长期最优生产方案，但当前作为产品要求暂时保留。

## Follow-ups

- 增补新的 workflow/run API 契约文档。
- 审计哪些旧 `executions` / `tasks` / `workbench` 结构可复用，哪些需要迁移或隔离成 legacy。
- 在单机 Linux 闭环跑通后，再决定 HPC scheduler adapter 的落地顺序。
