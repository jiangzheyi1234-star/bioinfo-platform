# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# H2OMeta — Claude 开发指令

> 产品需求见 `PRODUCT.md`，技术架构见 `ARCHITECTURE.md`。

## 常用命令

```bash
python -m ui.main          # 启动应用
pytest                      # 运行全部 414 个测试
pytest tests/test_xxx.py -v # 单文件测试
```

环境：Conda `bio_ui`，Python 3.11+，依赖 PyQt6/PyQt6-WebEngine/paramiko/Jinja2/matplotlib

## 软件定位

宏基因组桌面分析平台（有界面的 Snakemake）：YAML 插件化 / PipelineRunner 串联 / JobQueue 并行，零命令行。
三条路径：读长分析 · 组装分析 · AMR 分析。不做：16S / 云计算 / 多用户 / 手写规则。

## 架构规则

- **Core 层**：只允许 `PyQt6.QtCore`，禁止 QtWidgets/QtGui
- **UI 层**：新建 widget/page 后**必须同步更新 `__init__.py`**
- **插件**：`plugins/{category}/{tool_name}/tool.yaml`
- **可视化**：图表用 matplotlib；复杂布局允许 QWebEngineView
- **存储**：SQLite `project.db`，本地 `~/.h2ometa/projects/{id}/`，远端 `/h2ometa/projects/{id}/`
- **编码**：Python 3.11+，类型注解，中文注释/UI，PascalCase 类，snake_case 方法

## 已完成模块

### Core 层（✅ 全部完成）
执行链：`tool_engine` → `command_builder` → `job_dispatcher` → `job_monitor`
调度：`job_queue`（并发控制）· `retry_manager`（退避重试）· `ssh_reconnector`（断线重连，携带新 client）
流水线：`pipeline_runner`（线性编排）· `pipeline_reconstructor`（DAG 重建）
数据：`data_registry`（血缘追踪）· `data_importer` · `storage_manager`（磁盘监控）· `execution_cleaner`
项目：`project_manager` · `project_exporter`（Methods + CSV + ZIP）· `plugin_registry`（YAML 三层懒加载）
总线：`service_locator` · `chart_data_parser`
旧模块保留：`ssh_service` · `task_manager`（task_history_card 仍在使用）

### UI 页面（✅ 6 页全部完成）
| 页面 | 功能 |
|------|------|
| `project_page` | 项目创建/切换/归档/删除/导出 |
| `analysis_page` | YAML 驱动读长分析，阶段状态实时更新 |
| `assembly_page` | YAML 驱动组装分析（7阶段），PipelineRunner 执行 |
| `detection_page_web` | 插件工作台（QWebEngineView + Galaxy 风格双栏） |
| `settings_page` | SSH（分步诊断+密钥认证+自动重连）/ NCBI 配置 |
| `home_page` | 样本管理中心（统计头/卡片/最近执行/增删样本） |

### 插件 YAML（✅ 16 个 tool.yaml + 2 个声明式）
fastp · hostile · kraken2 · megahit · metaspades · metabat2 · maxbin2 · concoct · das_tool · checkm2 · busco · gtdbtk · prokka · bakta · eggnog · blastn
声明式：`analysis_paths.yaml` · `databases.yaml`

每个 tool.yaml 含以下关键字段：
- `conda_env`: 工具专属 conda 环境名（如 `fastp_env`）
- `install_cmd`: conda create 安装命令（如 `conda create -n fastp_env -c bioconda fastp -y`）
- `databases`: 工具所需数据库声明（`id` + `param_name`）

### 工具环境管理（✅ 已完成）
`LinuxSettingsCard` 支持完整的"检测 + 安装"闭环：
- **一键检测**：SSH `conda env list --json` 逐个比对，❌ 工具行显示「安装」按钮
- **点击安装**：`EnvInstallDialog` 弹出，SSH 执行 `conda create`，输出实时滚动
- **数据库提示**：安装需要数据库的工具后，自动弹出提示引导填写路径
- **安装完成**：自动重新触发全量检测，更新 ✅/❌ 状态

## 待完成功能（每次开发前先 Review）

### P1 — 阻断（流程能跑但结果看不到）
- [ ] `ChartWidget` / `ResultsPanel` 未加入 `ui/widgets/__init__.py`
- [ ] `analysis_page._on_pipeline_completed()` 未调用 `ResultsPanel.load_results()`
- [ ] 结果文件下载逻辑缺失：远端文件需 `ssh.download()` 到本地

### P2 — 核心功能缺失
- [ ] 结果浏览页（`results_page.py`）
- [ ] 数据库管理页（`database_page.py`）— 工具环境已可安装，下一步需要数据库下载 UI
- [ ] AMR 分析页（`amr_page.py`）— 污水研究核心
- [ ] DAG 视图（`dag_widget.py`）
- [ ] `ResultSyncManager`（任务完成自动同步 result 文件）
- [ ] 缺少插件 YAML：bracken · krona · rgi · genomad · integron_finder · isescan · quast · amrfinderplus
- [ ] 历史执行选择器（analysis_page / assembly_page 切换同一工具多次执行结果）

## SQLite Schema

```sql
CREATE TABLE samples (sample_id TEXT PRIMARY KEY, name TEXT, source TEXT, metadata TEXT);
CREATE TABLE executions (
    execution_id TEXT PRIMARY KEY, sample_id TEXT, tool_id TEXT,
    parameters TEXT, status TEXT, triggered_by TEXT,
    created_at REAL, completed_at REAL, error TEXT,
    retry_count INTEGER DEFAULT 0, retry_of TEXT, remote_job_id TEXT,
    is_final_version INTEGER DEFAULT 0, archived_at REAL);
CREATE TABLE data_items (
    data_id TEXT PRIMARY KEY, sample_id TEXT, file_path TEXT,
    data_type TEXT, tier TEXT, produced_by TEXT, created_at REAL, metadata TEXT);
CREATE TABLE execution_io (execution_id TEXT, data_id TEXT, direction TEXT,
    PRIMARY KEY (execution_id, data_id, direction));
```

## 服务器环境

服务器 `192.168.0.152`，用户 `zyserver`，远端 `/h2ometa/projects/{project_id}/`
输出目录：`/h2ometa/projects/{id}/intermediate/{sample_id}/{tool_id}_{execution_id}/`（每次执行独立目录）

## 开发规则

1. **Core 和 UI 同步完成** — 以用户能在界面上看到为验收标准
2. **新建 widget 立即更新 `__init__.py`**
3. **不留死控件** — 暂不实现用 `setEnabled(False)` + 提示文字
4. **完成后更新待完成列表** — `[x]` 已完成，`[ ]` 新问题
5. **响应式布局** — 避免固定宽度，用弹性布局
