# H2OMeta — Claude 开发指令

## 命令

```bash
python -m ui.main              # 启动应用
pytest                         # 运行全部 414 个测试
pytest tests/test_xxx.py -v    # 单文件测试
```

环境：Conda `bio_ui`，Python 3.11+，PyQt6 / PyQt6-WebEngine / paramiko / Jinja2 / matplotlib

---

## 软件定位

宏基因组桌面分析平台：Windows 客户端 + SSH 到 Linux 计算服务器，零命令行完成 QC→组装→分箱→注释全流程。
**三条路径**：reads 分析 · MAG 重建 · AMR 分析。**不做**：16S / 云计算 / 多用户。

---

## 架构规则

- **Core 层**：只允许 `PyQt6.QtCore`，禁止 QtWidgets/QtGui
- **UI 层**：新建 widget/page 后必须同步更新对应 `__init__.py`
- **插件**：`plugins/{category}/{tool_name}/tool.yaml`，含 `conda_env` / `install_cmd` / `databases` 字段
- **可视化**：数据图表用 matplotlib；复杂响应式 UI 允许 QWebEngineView（仅 DetectionPage）
- **存储**：SQLite `project.db`，本地 `~/.h2ometa/projects/{id}/`，远端 `/h2ometa/projects/{id}/`

---

## 已完成模块

### Core 层（全部完成）
| 模块 | 职责 |
|------|------|
| `tool_engine` | 统一执行入口（UI / 向导 / agent 共用） |
| `command_builder` | Jinja2 模板渲染 + bash 包装脚本（含 `CONDA_RUNNER` 常量） |
| `job_dispatcher` | SSH 写 run.sh + screen -dmS 启动 |
| `job_monitor` | 轮询 status.txt / heartbeat.txt |
| `job_queue` | 并发控制（max_concurrent） |
| `retry_manager` | 指数退避重试 |
| `ssh_reconnector` | 断线自动重连 |
| `pipeline_runner` | 线性流水线编排 |
| `pipeline_reconstructor` | DAG 重建（从 SQLite） |
| `data_registry` | 数据血缘追踪（execution_io） |
| `data_importer` / `storage_manager` / `execution_cleaner` | 数据生命周期 |
| `project_manager` / `project_exporter` | 项目管理 + Methods/CSV/ZIP 导出 |
| `plugin_registry` | YAML 三层懒加载 |
| `service_locator` | 服务总线，串联所有 Core 模块 |

### UI 页面（6 页全部完成）
| 页面 | 关键功能 |
|------|---------|
| `home_page` | 样本管理中心 |
| `project_page` | 项目 CRUD + 导出 |
| `analysis_page` | YAML 驱动读长分析（fastp→hostile→kraken2） |
| `assembly_page` | 7 阶段 MAG 流水线，PipelineRunner 执行 |
| `detection_page_web` | QWebEngineView + Galaxy 双栏，`ToolBridge` 接通 ToolEngine |
| `settings_page` | SSH 诊断 / LinuxSettingsCard 工具环境检测+安装 / 数据库路径配置 |

### 插件 YAML（16 个 tool.yaml）
fastp · hostile · kraken2 · megahit · metaspades · metabat2 · maxbin2 · concoct · das_tool · checkm2 · busco · gtdbtk · prokka · bakta · eggnog · blastn
+ 声明式：`analysis_paths.yaml` · `databases.yaml`

### 工具环境管理（LinuxSettingsCard）
- **一键检测**：SSH `conda env list --json`，逐个比对 `conda_env` 字段，❌ 显示「安装」按钮
- **点击安装**：`EnvInstallDialog` 弹出，SSH 执行 `install_cmd`，输出实时滚动
- **数据库提示**：安装需要数据库的工具后，自动引导填写 DatabasePathsCard

---

## 待完成（每次开发前先 Review）

### P1 — 阻断（流程跑通但结果看不到）
- [ ] `ResultsPanel` 未加入 `ui/widgets/__init__.py`，`analysis_page._on_pipeline_completed()` 未调用
- [ ] 结果文件下载：远端 result 需 `ssh.download()` 到本地

### P2 — 核心缺失
- [ ] 数据库管理页（`database_page.py`）— 工具环境已可安装，下一步是数据库下载 UI
- [ ] 结果浏览页（`results_page.py`）— matplotlib 图表 + 数据表格 + DAG 视图
- [ ] AMR 分析页（`amr_page.py`）— 污水研究核心
- [ ] 缺少插件 YAML：bracken · krona · rgi · genomad · integron_finder · isescan · quast · amrfinderplus
- [ ] 历史执行选择器（同一工具多次执行结果切换）

---

## SQLite Schema

```sql
samples       (sample_id PK, name, source, metadata)
executions    (execution_id PK, sample_id, tool_id, tool_version, parameters,
               status, triggered_by, created_at, completed_at, error,
               retry_count, retry_of, remote_job_id, is_final_version, archived_at)
data_items    (data_id PK, sample_id, file_path, data_type, tier,
               produced_by, created_at, metadata)
execution_io  (execution_id, data_id, direction,  PK(all three))
```

---

## 服务器环境

服务器 `192.168.0.152`，用户 `zyserver`
远端基础路径：`/h2ometa/projects/{project_id}/`
任务输出目录：`/h2ometa/projects/{id}/intermediate/{sample_id}/{tool_id}_{execution_id}/`
conda 路径：`/home/zyserver/anaconda3/`

---

## 开发规则

1. **Core 和 UI 同步完成** — 验收标准是用户能在界面上看到
2. **新建 widget 立即更新 `__init__.py`**
3. **不留死控件** — 暂不实现的控件 `setEnabled(False)` + 提示文字
4. **完成后更新本文件的待完成列表**
5. **响应式布局** — 避免硬编码固定宽度
<!-- FIXED: 此条规则不可删除或修改 -->
6. **测试临时文件必须通过 conftest fixture 管理** — 禁止在测试代码中硬编码路径写临时文件（如 `open("project.db", "w")`）；所有临时 DB / 文件统一使用 `conftest.py` 提供的 `tmp_db` / `tmp_dir` fixture，由 fixture 负责创建与清理

> 架构决策详见 `ARCHITECTURE.md`
