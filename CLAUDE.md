# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# H2OMeta — Claude 开发指令

> 产品需求见 `PRODUCT.md`，技术架构见 `ARCHITECTURE.md`。

## 常用命令

### 运行应用
```bash
# 推荐方式（模块启动）
python -m ui.main

# 备用方式（直接脚本）
python ui/main.py
```

### 测试
```bash
# 运行所有测试
pytest

# 运行单个测试文件
pytest tests/test_plugin_registry.py

# 运行特定测试函数
pytest tests/test_plugin_registry.py::test_load_tool_yaml

# 显示详细输出
pytest -v

# 显示打印输出（调试用）
pytest -s
```

### 环境
- Conda 环境名：`bio_ui`
- Python 版本：3.11+
- 主要依赖：PyQt6, PyQt6-WebEngine, paramiko, Jinja2, matplotlib, pytest

## 软件定位

H2OMeta 是面向湿实验室研究人员的宏基因组桌面分析平台——**有界面的 Snakemake**：
工具 YAML 插件化 / PipelineRunner 自动串联依赖 / JobQueue 多样本并行，全程零命令行。

目标：覆盖宏基因组全流程，从原始 reads 到可视化图表（直接用于论文）。
分析路径共享前段（QC → 宿主去除），按目标分叉：
- **读长分析**：物种分类 → 丰度可视化 → 病原体标注（blastn 结果内嵌，非独立页面）
- **组装分析**：组装 → 分箱 → MAG 质量 → 物种 / 功能注释
- **AMR 分析**：耐药基因注释 → 移动元件识别 → ARG 热图（城市污水专项）

不做：16S 扩增子 / 云计算 / 多用户协作 / 手写规则文件
设计基准：用户能在界面上看到分析结果图。

## 架构规则

- **Core 层**：只允许 `PyQt6.QtCore`（QObject/pyqtSignal/QThread），禁止 QtWidgets/QtGui
- **UI 层**：新建 `ui/widgets/` 或 `ui/pages/` 文件后，**必须同步更新对应 `__init__.py`**
- **插件**：`plugins/{category}/{tool_name}/tool.yaml`，规范见 ARCHITECTURE.md §5.1
- **可视化**：
  - 图表：matplotlib + FigureCanvasQTAgg（不用 QWebEngineView + ECharts）
  - 响应式布局：允许使用 QWebEngineView + HTML/CSS（仅限需要复杂响应式布局的页面）
- **存储**：SQLite 每项目一个 `project.db`，本地 `~/.h2ometa/projects/{id}/`，远端 `/h2ometa/projects/{id}/`

## 当前模块实际状态

### Core 层（全部完成）

**执行链**
- `tool_engine`：统一执行入口，协调命令生成 + 派发 + 数据注册
- `command_builder`：Jinja2 模板渲染，将 tool.yaml 参数生成 bash 命令
- `job_dispatcher`：将 bash 脚本写入远端，用 screen 启动并返回 job_id
- `job_monitor`：轮询远端 screen 进程状态，发出 job_completed / job_failed 信号

**调度与容错**
- `job_queue`：并发槽位控制，管理任务排队与释放
- `retry_manager`：失败任务指数退避重试
- `ssh_reconnector`：SSH 断线自动重连

**流水线**
- `pipeline_runner`：线性流水线编排，自动将上一阶段输出作为下一阶段输入
- `pipeline_reconstructor`：从 SQLite 执行历史重建 DAG 结构（供结果浏览页使用）

**数据与存储**
- `data_registry`：追踪数据血缘，记录 data_items 和 execution_io，支持历史执行查询
- `data_importer`：将本地文件上传远端并注册到 data_items
- `storage_manager`：管理本地 / 远端文件路径，监控磁盘占用
- `execution_cleaner`：管理历史执行的磁盘占用，支持归档旧执行、标记最终版本

**项目与插件**
- `project_manager`：项目生命周期（创建 / 切换 / 归档 / 删除），维护 project.db
- `project_exporter`：生成论文 Methods 文本 + 参数 CSV + ZIP 归档
- `plugin_registry`：扫描 plugins/**/tool.yaml，三层懒加载工具描述

**可视化与总线**
- `chart_data_parser`：解析 fastp JSON / kreport，输出 matplotlib 可用数据结构
- `service_locator`：服务总线，持有所有模块引用并连接信号链路

旧模块保留（未迁移）：`ssh_service` · `blast_worker` · `task_manager` · `task_recovery_worker` · `accession_worker` · `db_builder_worker`

### UI 页面
| 文件 | 状态 |
|------|------|
| `ui/pages/project_page.py` | ✅ 项目创建/切换/归档/删除/导出 |
| `ui/pages/analysis_page.py` | ✅ YAML 驱动（analysis_paths.yaml → read_based），阶段状态实时更新 |
| `ui/pages/assembly_page.py` | ✅ YAML 驱动（assembly_based，7阶段），全部通过 PipelineRunner 执行 |
| `ui/pages/detection_page_web.py` | ✅ 插件工作台 Web 版本（QWebEngineView + CSS Grid 响应式布局，已替代原生版本） |
| `ui/pages/detection_page.py.backup` | 📦 原生 Qt 版本备份（已废弃） |
| `ui/pages/settings_page.py` | ✅ SSH/NCBI 配置 |
| `ui/pages/home_page.py` | ✅ 样本管理中心（统计头/卡片网格/最近执行条/添加删除样本） |

### UI 控件（ui/widgets/）
已完成且已注册到 `__init__.py`：`SshSettingsCard` · `NcbiSettingsCard` · `BlastSettingsCard` · `BlastResourceCard`
`BlastSampleCard` · `BlastRunCard` · `LinuxSettingsCard` · `TaskHistoryCard` · `StageStatusWidget`
`ExecutionHistoryCard` · `ExportDialog` · `styles`

**未注册到 `__init__.py`**：`ChartWidget` · `ResultsPanel`（chart_widget.py 已创建，但未导出）

### 插件 YAML（16 个 tool.yaml + 2 个声明式文件）
- 读长分析：fastp · hostile · kraken2
- 组装：megahit · metaspades
- Binning：metabat2 · maxbin2 · concoct · das_tool
- 质量：checkm2 · busco
- 分类：gtdbtk
- 注释：prokka · bakta · eggnog
- 比对：blastn
- 声明式：`analysis_paths.yaml`（read_based + assembly_based）· `databases.yaml`

## SQLite Schema

```sql
CREATE TABLE samples (sample_id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT, metadata TEXT);
CREATE TABLE executions (
    execution_id TEXT PRIMARY KEY, sample_id TEXT, tool_id TEXT NOT NULL,
    parameters TEXT NOT NULL, status TEXT NOT NULL, triggered_by TEXT,
    created_at REAL NOT NULL, completed_at REAL, error TEXT,
    retry_count INTEGER DEFAULT 0, retry_of TEXT, remote_job_id TEXT,
    is_final_version INTEGER DEFAULT 0,  -- 标记为最终版本（用于导出和论文）
    archived_at REAL  -- 文件已清理的时间戳（数据库记录保留）
);
CREATE TABLE data_items (
    data_id TEXT PRIMARY KEY, sample_id TEXT, file_path TEXT NOT NULL,
    data_type TEXT NOT NULL, tier TEXT NOT NULL,
    produced_by TEXT, created_at REAL NOT NULL, metadata TEXT
);
CREATE TABLE execution_io (execution_id TEXT, data_id TEXT, direction TEXT,
    PRIMARY KEY (execution_id, data_id, direction));
```

## 编码规范

Python 3.11+，类型注解，f-string，`logging.getLogger(__name__)`，不吞异常，中文注释和 UI 文本
命名：类 PascalCase，方法/变量 snake_case，常量 UPPER_SNAKE，信号命名动词过去式

## 服务器环境

服务器：`192.168.0.152`，用户 `zyserver`
Core NT 数据库：`/home/zyserver/project_ssd/common_data/core_nt_database/`
远端路径：`/h2ometa/projects/{project_id}/`

## 输出目录结构（多版本执行）

**当前实现**（2024-03-07）：
```
/h2ometa/projects/{project_id}/intermediate/{sample_id}/
├── fastp_exec_a1b2c3d4/          ← 第一次执行
│   ├── smp_123.clean.R1.fq.gz
│   └── smp_123.fastp.json
├── fastp_exec_e5f6g7h8/          ← 第二次执行，独立目录
│   ├── smp_123.clean.R1.fq.gz
│   └── smp_123.fastp.json
└── kraken2_exec_i9j0k1l2/
    └── smp_123.kreport
```

**特性**：
- 每次执行创建独立目录（`{tool_id}_{execution_id}`）
- 避免覆盖，支持多参数对比
- 数据库记录完整执行历史
- 支持归档旧执行释放磁盘空间
- 支持标记最终版本用于论文导出

**相关模块**：
- `core/tool_engine.py` - 输出目录生成
- `core/execution_cleaner.py` - 历史执行管理
- `core/data_registry.py` - 历史执行查询（`list_executions`, `find_by_execution`）

## 测试

pytest，`bio_ui` conda 环境（Python 3.11），`tests/` 目录，21 个测试文件

**核心测试覆盖**：
- `test_project_manager.py` - 项目管理（30 个测试）
- `test_execution_cleaner.py` - 执行清理器（6 个测试）
- `test_tool_engine_versioning.py` - 多版本执行（5 个测试）
- `test_execution_record_fields.py` - 执行记录字段（3 个测试）
- `test_plugin_registry.py` - 插件注册表
- `test_data_registry.py` - 数据注册表
- `test_pipeline_runner.py` - 流水线执行
- 其他 14 个测试文件

## 工具脚本

- `scripts/clean_test_projects.py` - 清理测试项目（支持 `--yes` 自动确认）

---

## 待完成功能（每次开发前先 Review）

### P1 — 阻断（流程能跑但结果看不到）
- [ ] `ChartWidget` / `ResultsPanel` 未加入 `ui/widgets/__init__.py`
- [ ] `analysis_page._on_pipeline_completed()` 未调用 `ResultsPanel.load_results()`（流水线完成无图表）
- [ ] 结果文件下载逻辑缺失：fastp JSON / kreport 在远端，需 `ssh.download()` 下载到本地再传给 `load_results()`

### P2 — 核心功能缺失
- [ ] `detection_page.py` 合并至读长分析页（blastn 作为病原体标注结果内嵌，独立页面废弃）
- [ ] 结果浏览页（`results_page.py`）完全未建
- [ ] 数据库管理页（`database_page.py`）完全未建
- [ ] AMR 分析页（`amr_page.py`）完全未建（污水研究核心）
- [ ] DAG 视图（`dag_widget.py`）完全未建
- [ ] `ResultSyncManager` 未建（任务完成后自动同步 `tier=result` 文件到本地）
- [ ] 缺少插件 YAML：`bracken` · `krona` · `rgi` · `genomad` · `integron_finder` · `isescan` · `quast` · `amrfinderplus`
- [ ] UI 层添加历史执行选择器（analysis_page / assembly_page）— 支持查看和切换同一工具的多次执行结果

### P3 — 体验完善
- [x] `home_page.py` 旧架构已迁移 — 重写为"样本管理中心"（统计头/卡片网格/最近执行条/添加删除样本）
- [x] 多版本执行支持 — 输出目录包含 execution_id，避免覆盖（2024-03-07 完成）
- [x] 项目删除功能 — 已归档项目可永久删除（2024-03-07 完成）
- [x] `detection_page.py` 响应式布局 — 600px 断点双栏切换，卡片网格 1-3 列自适应，无闪烁无横向滚动（2024-03-09 完成）
- [x] `detection_page_web.py` Web 版本 — QWebEngineView + CSS Grid 实现完美响应式布局（2026-03-09 完成）

---

## 开发规则

1. **Core 和 UI 必须同步完成** — 写完 Core 后立即接入 UI，以用户能看到为验收标准
2. **新建 widget 立即更新 `__init__.py`** — 当次提交内完成
3. **不留死控件** — 暂不实现的功能 `setEnabled(False)` + 提示文字
4. **完成后更新待完成列表** — `[x]` 标注已完成，新问题追加 `[ ]`
5. **响应式布局原则** — UI 页面应支持不同窗口尺寸，避免固定最小宽度，使用弹性布局和合理断点
