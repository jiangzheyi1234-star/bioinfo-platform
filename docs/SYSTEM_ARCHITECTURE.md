# H2OMeta 当前系统架构总览

本文档描述当前仓库已经落地的系统架构，用于回答“整个项目现在是怎么组织和运行的”。

与 [ARCHITECTURE.md](/E:/code/bio_ui/ARCHITECTURE.md) 的区别：

- `ARCHITECTURE.md` 偏架构决策速查与边界约束
- 本文档偏当前系统全貌、模块分工、主数据流和运行方式

## 1. 系统目标

H2OMeta 当前系统围绕 4 个核心目标组织：

- 提供桌面端生信分析工作台，统一项目、样本、工具执行和结果查看
- 通过插件化 `tool.yaml` 驱动工具接入，降低新增工具的代码改动成本
- 通过 SSH + `screen` + `conda run -p` 在远端 Linux 环境执行分析任务
- 用项目级 SQLite 与结果缓存维持 execution、数据血缘和结果可追溯性

## 2. 顶层分层

```text
PyQt6 UI
  -> controllers / pages / widgets
  -> ToolBridgeService
  -> ServiceLocator
  -> core services
  -> Project SQLite + local result cache
  -> SSHService
  -> remote Linux runtime (screen / conda / workflow files / results)
```

当前架构按职责主要分为 5 层：

1. UI 层
   - 位于 `ui/`
   - 负责页面渲染、信号绑定、状态展示
   - 不直接做 SQL、SSH、耗时 IO、结果解析

2. 编排与桥接层
   - `core/service_locator.py`
   - `core/execution/tool_bridge_service.py`
   - 负责把 UI 请求转成可执行的 core 行为，并连接执行生命周期

3. 领域核心层
   - `core/data/`
   - `core/execution/`
   - `core/pipeline/`
   - `core/environment/`
   - `core/plugins/`
   - 负责项目、执行、结果、环境、插件、导出和查询逻辑

4. 本地持久化层
   - 项目目录 `~/.h2ometa/projects/<project_id>/`
   - SQLite `project.db`
   - 本地结果缓存 `results/<execution_id>/`

5. 远端运行层
   - 远端 Linux 主机
   - `SSHService.run()` 单队列
   - `screen` detached 任务
   - 受控 conda 前缀和 workflow/task 目录

## 3. 顶层组件与职责

### 3.1 UI 层

主要页面位于 `ui/pages/`：

- `home_page.py`：首页与总览入口
- `project_page.py`：项目相关入口
- `detection_page_web.py`：工具工作台、history、results 主界面
- `database_page.py`：数据库管理
- `settings_page.py`：配置与环境设置
- `log_page.py`：日志与运行状态

主要控制器位于 `ui/controllers/`：

- `main_window_project_controller.py`：项目切换与项目态编排
- `main_window_ssh_controller.py`：SSH 连接与连接状态
- `main_window_reconcile_controller.py`：远端执行状态对账
- `main_window_log_controller.py`：执行日志与状态更新
- `install_task_controller.py` / `install_workflow.py`：安装任务生命周期

UI 只负责发起动作、接收信号、更新页面。耗时操作必须下沉到 worker/core，不在主线程直接执行 SSH 或阻塞流程。

### 3.2 ServiceLocator

`core/service_locator.py` 是当前运行时的服务总线，负责：

- 持有 `ProjectManager`、`PluginRegistry`、`JobQueue`、`JobDispatcher`、`RetryManager`
- 创建并接线 `ToolEngine`
- 管理 `ExecutionPreparer` 与后台 `TaskRunner`
- 维护 execution context 和 task dir
- 在主线程完成 `JobDispatcher.start_waiting()` 接线

它是 UI 和 core 执行链之间最重要的运行时装配点。

### 3.3 ToolBridgeService

`core/execution/tool_bridge_service.py` 是工作台后端桥接层，负责：

- 接收 UI 的工具执行请求
- 查询 execution history
- 为 completed execution 构建统一 results payload
- 读取本地 artifact cache，解析单工具和 workflow 结果
- 提供 integrated workbench 所需的结构化 view

它不直接承担线程调度，而是把“工作台行为”翻译为 core 服务调用和结果视图数据。

### 3.4 项目与数据层

`core/data/` 负责项目级持久化与数据血缘：

- `project_manager.py`
  - 项目生命周期
  - 项目索引
  - SQLite 初始化与连接
- `data_registry.py`
  - 样本、数据项、execution 输入输出关系
  - `raw / intermediate / result` 分层
- `execution_query_service.py`
  - execution 列表查询和 history 视图所需聚合
- 其他服务
  - 数据导入、数据库服务、清理/归档

当前数据库核心表包括：

- `samples`
- `executions`
- `data_items`
- `execution_io`

execution 持久化状态固定为：

- `pending`
- `running`
- `completed`
- `failed`
- `retrying`

### 3.5 插件层

插件系统位于 `plugins/` 与 `core/plugins/plugin_registry.py`，采用声明式 YAML：

- 每个工具以 `plugins/{category}/{tool}/tool.yaml` 描述
- 描述内容包括输入、输出、参数、环境、检测命令和命令模板
- `PluginRegistry` 负责扫描、索引、懒加载和描述符读取

这使得新增工具主要是“新增声明”，而不是改执行框架。

### 3.6 执行层

`core/execution/` 是系统最关键的执行子系统，主要模块包括：

- `tool_engine.py`
  - execution 统一入口
  - 记录 DB、写 execution、安排 preparation
- `execution_preparer.py`
  - 在后台完成远端目录准备、workflow 上传和命令构建
- `execution_backend.py`
  - 当前 backend seam
  - 默认 `CommandBackend`
  - `NextflowBackend` 仅保留 capability boundary
- `command_builder.py`
  - 根据 `tool.yaml` 和参数构建最终命令
- `job_queue.py`
  - 排队与并发控制
- `job_dispatcher.py`
  - 通过 SSH 提交 `screen` 任务并等待结果
- `job_monitor.py`
  - 轮询 `status.txt` / `heartbeat.txt` / `exit_code.txt`
- `retry_manager.py`
  - 失败后的自动重试决策
- `artifact_store.py`
  - 本地 artifact manifest 和缓存持久化
- `tool_bridge_service.py` / `single_tool_view_builder.py`
  - 结果构建与 typed view 组装

### 3.7 远端与环境层

`core/remote/` 与 `core/environment/` 一起提供运行基线：

- `SSHService`
  - 远端命令、上传、下载统一入口
  - 代码必须走 `SSHService.run(cmd, timeout)`，不允许绕开单队列
- `storage_manager.py`
  - 远端存储相关能力
- `env_installer.py`
  - conda/工具安装，长耗时任务走 detached `screen`
- `h2o_env_paths.py`
  - 受控 conda 路径规则
- `miniforge_condarc.py`
  - 统一 condarc 模板来源

远端运行基线是：

- 默认远端环境通过 `H2O_CONDA_EXE` 或 `~/.h2ometa/conda/bin/conda`
- 工具执行与安装使用 `conda run -p ...`
- 所有 SSH 命令通过 `SSHService.run()`
- 长时任务通过 `screen` 启动并由状态文件驱动回传

## 4. 当前主执行链路

当前执行链路是“主线程轻量 + 后台 preparation + 后台 dispatch + 主线程 waiter handoff”：

```text
UI / ToolBridgeService
  -> ToolEngine.execute()
  -> 写 executions(status=pending)
  -> 发出 PreparationRequest
  -> ExecutionPreparer.prepare() 后台执行
  -> 创建远端输出目录 / 上传 workflow / 构建命令
  -> ServiceLocator._on_preparation_succeeded()
  -> JobQueue.submit()
  -> ToolEngine.mark_execution_running()
  -> TaskRunner 提交 _dispatch_job()
  -> CommandBackend.dispatch()
  -> JobDispatcher.submit() 远端 screen -dmS
  -> ServiceLocator._on_dispatch_submitted()
  -> JobDispatcher.start_waiting() 主线程接线
  -> waiter 轮询状态文件
  -> ToolEngine.on_job_completed() / on_job_failed()
  -> ToolBridgeService.get_results_for_execution()
  -> results workbench
```

这里的关键边界是：

- `ToolEngine.execute()` 保持主线程轻量
- `ExecutionPreparer` 负责 SSH preparation，不能回到主线程
- `JobDispatcher.start_waiting()` 保持在主线程接线
- 默认 backend 仍是 `CommandBackend`

## 5. 当前结果系统架构

当前结果系统已经稳定为三段职责：

- tools：配置与提交
- history：execution 列表与状态详情
- results：completed execution 的统一结果页

统一结果页当前固定由以下信息块构成：

- `Overview`
- `Result`
- `Files`
- `Provenance`

结果构建依赖以下核心协议：

- `summary`
- `charts`
- `table`
- `artifacts`
- `provenance`
- `sections`
- `archetype`

当前系统还支持 additive typed artifact metadata：

- `artifact_type`
- `display_role`
- `viewer_hint`

这些字段用于更明确地决定 artifact 的 viewer 和展示角色，但不替代现有核心 artifact 字段。

## 6. 本地与远端数据流

### 6.1 本地项目数据

每个项目是独立目录，包含：

- `project.db`
- 项目元数据
- `results/<execution_id>/` 本地结果缓存

本地数据库负责：

- execution 记录
- 输入输出关系
- 数据血缘
- 查询 history 和结果入口

### 6.2 远端任务数据

远端每次 execution 会关联 task/output 目录，通常包含：

- 命令脚本
- `status.txt`
- `heartbeat.txt`
- `exit_code.txt`
- tool/workflow 输出文件

结果回传时，会把 artifact 下载到本地项目目录并生成：

- `artifacts_manifest.json`

然后由 `ArtifactStore`、`ToolBridgeService` 和 view builder 继续消费。

## 7. 线程与并发模型

当前系统采用“UI 主线程 + worker/background 任务”的保守模型：

- UI 主线程
  - 页面更新
  - 信号接收
  - `JobDispatcher.start_waiting()` 接线
- 后台 worker / thread pool
  - remote preparation
  - dispatch 提交
  - 其他阻塞型任务

硬约束：

- Qt slot / 主线程不能直接跑 SSH
- worker 不能直接操作 Qt Widget
- worker 只能通过 signal 把结果送回主线程
- 不能绕开 `SSHService.run()`

## 8. 当前已建立的兼容性边界

为了让系统可持续演进，当前仓库已经冻结了几条重要兼容性边界：

- 不改变 `ToolEngine.execute()` 的外部语义
- 不新增 execution 持久化状态
- 不改变 `history -> completed -> results` 主通路
- 不以 silent fallback 掩盖结果缺失或 metadata 非法
- 不让 `NextflowBackend` 静默接管默认执行链路

这些边界决定了后续迭代必须是“显式扩展”，而不是隐式替换。

## 9. 当前系统的扩展点

如果未来继续演进，当前较稳定的扩展点包括：

- 新增工具：新增 `tool.yaml`
- 新增结果视图：扩展 single-tool view builder / result parser
- 新增 artifact 表达：在 additive metadata 范围内扩展
- 新 backend：基于 `ExecutionBackend` seam 增加 capability，但不能直接替换默认路径
- 新项目导出/追溯能力：扩展 `pipeline/` 与 `project_exporter.py`

## 10. 读代码建议

如果第一次进入这个仓库，建议阅读顺序：

1. [ARCHITECTURE.md](/E:/code/bio_ui/ARCHITECTURE.md)
2. `core/service_locator.py`
3. `core/execution/tool_engine.py`
4. `core/execution/tool_bridge_service.py`
5. `core/data/project_manager.py`
6. `core/plugins/plugin_registry.py`
7. `ui/pages/detection_page_web.py`

这样可以先理解总线、执行、结果、项目和 UI 主入口，再看具体业务细节。
