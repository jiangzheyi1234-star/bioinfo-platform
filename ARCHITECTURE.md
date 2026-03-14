# H2OMeta — 架构决策速查

> 日常开发看 `CLAUDE.md` 即可；本文件维护当前代码结构与边界约束。

---

## 12 条核心架构决策

| # | 决策 | 选择 | 原因 |
|---|------|------|------|
| 1 | GUI 框架 | PyQt6 | 跨平台、成熟、原生性能 |
| 2 | 远端执行 | SSH + screen + conda | 无需在服务器部署 agent |
| 3 | 插件系统 | YAML 声明式 | 新增工具不改代码，product-safe |
| 4 | 工作流引擎 | 自建 PipelineRunner | 无需 Snakemake 依赖，轻量可控 |
| 5 | 项目隔离 | Galaxy History 模型 | 每项目独立 SQLite + 目录 |
| 6 | 数据关联 | 手动确认 + 智能推荐 | 避免自动关联出错 |
| 7 | 分析入口 | 向导 + 自由模式双轨 | 新手向导，专家自由 |
| 8 | 图表渲染 | matplotlib（QWebEngineView 仅限复杂布局） | 无浏览器依赖，响应快 |
| 9 | DAG 视图 | 只读状态视图，不支持拖拽 | 降低复杂度，够用 |
| 10 | 存储分层 | raw / intermediate / result 三层 | 磁盘可按层清理 |
| 11 | 可追溯性 | Methods 自动生成 + Snakefile 导出 | 论文复现友好 |
| 12 | 数据库管理 | 国内镜像优先，UI 一键安装 | 生信数据库普遍被墙 |

---

## 执行链路

```
UI 点击 / 向导
    │
    ▼
ToolEngine.execute()
    ├─ PluginRegistry.get_descriptor(tool_id)   # 加载 tool.yaml
    ├─ DataRegistry.get_item()                   # 解析输入路径
    ├─ CommandBuilder.build()                    # Jinja2 渲染命令
    ├─ SQLite INSERT executions                  # 写执行记录
    └─ JobQueue.submit()                         # 排队
            │
            ▼ job_started 信号
    ServiceLocator._on_dispatch()
            │
            ├─ CommandBuilder.wrap()             # 生成 bash 包装脚本（心跳+trap+日志）
            └─ JobDispatcher.submit()            # SSH 写 run.sh + screen -dmS
                        │
                        ▼ （轮询）
            JobMonitor   ←── SSH 读 status.txt / heartbeat.txt
                        │
            ┌───────────┴──────────┐
     job_completed              job_failed
            │                      │
    ToolEngine.on_job_completed   RetryManager
    DataRegistry.register_output
    SQLite UPDATE status=completed
```

---

## 插件 YAML 结构

```yaml
id: fastp
name: fastp
version: "0.23.4"
category: qc
conda_env: fastp_env
install_cmd: "conda create -n fastp_env -c bioconda -c conda-forge fastp -y"

inputs:   [{name, type, required}]
outputs:  [{name, type, tier, pattern, sync_to_local}]
parameters: [{name, type, default, label}]
databases:  [{id, param_name, required}]    # 空列表 = 不需要数据库

command_template: |                         # Jinja2 模板
  fastp -i {{ reads_1 }} ...

detection:
  command: "fastp --version"
  version_regex: "fastp (\\d+\\.\\d+\\.\\d+)"
```

---

## 目录结构（关键路径）

```
bio_ui/
├── core/                    # 纯逻辑层，禁 QtWidgets
│   ├── __init__.py          # 子包汇总
│   ├── service_locator.py   # 服务总线（根级）
│   ├── execution/           # 执行链（7 个模块）
│   │   ├── tool_engine.py   # 统一执行入口
│   │   ├── tool_bridge_service.py # UI→Core 桥接服务
│   │   ├── command_builder.py  # Jinja2 命令渲染
│   │   ├── job_dispatcher.py   # SSH + screen 投递
│   │   ├── job_monitor.py      # 状态轮询（fallback）
│   │   ├── job_queue.py        # 并发控制
│   │   └── retry_manager.py    # 自动重试
│   ├── data/                # 数据管理（5 个模块）
│   │   ├── data_registry.py    # 血缘追踪
│   │   ├── data_importer.py    # 数据导入
│   │   ├── project_manager.py  # 项目管理
│   │   ├── sample_service.py   # 样本 CRUD 服务
│   │   └── execution_cleaner.py # 归档清理
│   ├── remote/              # SSH 连接（4 个模块）
│   │   ├── ssh_service.py      # SSH 封装
│   │   ├── ssh_connector.py    # 连接/诊断服务
│   │   ├── ssh_reconnector.py  # 自动重连
│   │   └── storage_manager.py  # 远端存储
│   ├── pipeline/            # 流程编排（4 个模块）
│   │   ├── pipeline_runner.py     # 线性流水线
│   │   ├── pipeline_reconstructor.py  # DAG 重建
│   │   ├── chart_data_parser.py   # 结果解析
│   │   └── project_exporter.py    # 项目导出
│   ├── environment/         # 环境管理（4 个模块）
│   │   ├── env_detector.py      # conda 检测
│   │   ├── env_installer.py     # conda 安装
│   │   ├── env_batch_checker.py # 批量环境状态检查
│   │   └── container_detector.py # 容器检测（预留）
│   └── plugins/             # 插件系统（2 个模块）
│       ├── plugin_registry.py   # YAML 三层懒加载
│       └── task_manager.py      # 任务管理（legacy）
├── ui/
│   ├── pages/               # 6 个页面
│   ├── widgets/             # 可复用控件
│   │   ├── *_components.py  # 子卡片/弹窗组件
│   │   └── ...
│   ├── controllers/         # 跨页面编排
│   └── main_window.py
├── plugins/
│   ├── {category}/{tool}/tool.yaml
│   ├── databases.yaml       # 数据库清单
│   └── analysis_paths.yaml  # 分析路径声明
├── tests/                   # 单元测试 + 集成测试
└── config.py                # V2 配置模型
```

---

## 三阶段路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | Core 骨架（Plugin + Project + DataRegistry + ToolEngine） | ✅ 完成 |
| Phase 2 | ServiceLocator + PipelineRunner + 6 个 UI 页面全部接通 | ✅ 完成 |
| Phase 3 | 结果可视化 + 数据库管理页 + AMR 分析路径 | 🚧 进行中 |

---

## Code Placement Rules

| What you're adding | Where it goes |
|---|---|
| New dialog / sub-card | `ui/widgets/*_components.py` |
| Cross-page orchestration | `ui/controllers/*_controller.py` |
| Query / aggregation / execution logic | `core/*/*_service.py` |
| Shared utility functions | `core/utils.py` |
| Worker pure logic (IO, computation) | `core/` (UI layer = signal shell only) |
| New tool | `plugins/{category}/{tool_name}/tool.yaml` |

**Layer boundaries**:
- `ui/` — rendering, signal binding, state display. No SQL, SSH, file I/O, data parsing.
- `core/` — business logic, remote execution, data management. Only `PyQt6.QtCore` allowed.
- `plugins/` — YAML static declarations only.

**Size limits**: UI page ≤ 400 lines, complex card ≤ 500 lines, must split before adding features if > 600 lines. Evaluate splitting any function > 40 lines.
