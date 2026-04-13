# H2OMeta Workflow-First Migration Documentation

## Current Status

- 已冻结新的产品主线：`Tauri + static Next.js + FastAPI sidecar + Python core + SSH launcher backend`
- 已冻结新的执行模型：`WorkflowSpec -> Nextflow bundle -> run monitor`
- 已冻结新的确定性 profile 顺序：
  - 个人服务器：`Docker -> Podman -> micromamba/conda`
  - HPC：`Apptainer -> micromamba/conda`
- 首期目标固定为：跑通单机 Linux / 个人服务器 workflow bundle 主线
- 已新增 workflow-first 代码骨架：
  - `core/workflow/` 领域模型与最小 bundle 编译器
  - workflow/run API 契约与 FastAPI 路由骨架
  - `RuntimeService` 的 compile/list/get/create/cancel/artifacts/doctor skeleton
- 已接上单机 Linux 最小 launcher 闭环：
  - bundle 本地落盘
  - SSH 上传 bundle
  - 远端 detached wrapper 提交，并由 wrapper 持有真实 Nextflow pid
  - `status/exit_code/heartbeat/task.log/nextflow.pid` 查询
  - `trace/report/timeline/dag` artifact 下载
  - run 记录本地持久化后可重新加载

## Decisions

- 桌面端只做控制面，不承担 workflow 执行面。
- Nextflow 是首期唯一执行标准；WDL/CWL 只做未来导出预留。
- 业务工具不再做服务器级预装，统一交给 workflow 的 `container` / `conda` directive。
- 参数面板必须以 JSON Schema 为唯一真相源。
- 现有 `ToolEngine` / 单工具执行系统不再承载新执行，将逐步退役。
- 首期继续允许桌面端统一中转输入数据，后续再收敛到远端路径/对象存储优先。

## Current Milestone

- `M1 Freeze workflow-first contract` 已完成。
- `M2 Add domain types and API skeleton` 已完成最小骨架，下一步进入 `M3 Implement minimal bundle compiler` 到 `M4 Implement single-node Linux launcher` 的衔接阶段。
- `M3 Implement minimal bundle compiler` 已从内存 preview 提升到项目目录下的真实 bundle 落盘。
- `M4 Implement single-node Linux launcher` 已有最小可提交/可查询/可取消闭环，但真实 Nextflow 成功判定细节、artifact 完整性仍需继续打磨。
- `M6 Switch UI/API to workflow/run` 已完成首轮主导航与页面切换，并已继续收口为单工作台：
  - 主导航已收口为 `连接 / 工作台 / Settings`
  - `/workflows`、`/runs`、`/artifacts` 仅保留兼容跳转，统一导向 `/workspace`
  - 工作台默认聚焦当前 run，workflow 规格与 artifacts 退为次级折叠区
  - starter workflow、compile preview、submit run、run detail、artifacts 已统一进单控制台
- `M7 Retire legacy single-tool execution` 已完成主 UI 退场：
  - 侧栏不再默认加载 legacy execution 摘要
  - 主页面不再暴露单工具运行入口
- 当前优先级：
  - 打磨单机 Linux launcher 的状态/失败判定与结束态分类
  - 打磨工作台首屏的信息层级、日志可读性与 artifacts 预览
  - 再决定 API 层何时彻底封禁 legacy 单工具提交入口

## Known Risks

- 当前仓库明显是 tool-centric，迁移时最容易出现“双真相”并存。
- 现有 UI、API、runtime、service locator 都围绕单工具执行设计，切主线时必须分阶段替换。
- 桌面端统一中转大文件不是长期最优生产方案，但当前作为产品要求暂时保留。

## Follow-ups

- 增补新的 workflow/run API 契约文档。
- 审计哪些旧 `executions` / `tasks` / `workbench` 结构可复用，哪些需要迁移或隔离成 legacy。
- 在单机 Linux 闭环跑通后，再决定 HPC scheduler adapter 的落地顺序。
