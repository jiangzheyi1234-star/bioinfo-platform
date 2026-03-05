# H2OMeta - 宏基因组分析平台

## 项目概述

H2OMeta 是 PyQt6 桌面端宏基因组分析平台。Windows/Linux 客户端通过 SSH 连接 Linux 计算服务器，执行生物信息学分析流程。

## 架构设计文档

完整架构见 `ARCHITECTURE.md` (v2.1)。**所有开发工作必须遵循该文档的设计决策。**

## 关键架构规则

### Core 层依赖规则
- **允许**: `PyQt6.QtCore`（QObject, pyqtSignal, QThread, pyqtSlot）
- **禁止**: `PyQt6.QtWidgets`, `PyQt6.QtGui` 中的 UI 组件
- Core 层文件位于 `core/` 目录

### UI 层
- UI 层文件位于 `ui/` 目录
- 可使用所有 PyQt6 模块

### 插件系统
- 工具定义使用纯 YAML，位于 `plugins/{category}/{tool_name}/tool.yaml`
- 零 Python 代码修改即可添加新工具

### 数据存储
- 使用 SQLite，每个项目一个 `project.db`
- 四张核心表: `samples`, `executions`, `data_items`, `execution_io`
- 本地存储路径: `~/.h2ometa/projects/{project_id}/`
- 远端存储路径: `/h2ometa/projects/{project_id}/`

## SQLite Schema

```sql
CREATE TABLE samples (
    sample_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE executions (
    execution_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    tool_id TEXT NOT NULL,
    tool_version TEXT,
    parameters TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','retrying')),
    triggered_by TEXT,
    created_at REAL NOT NULL,
    completed_at REAL,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    retry_of TEXT REFERENCES executions(execution_id),
    remote_job_id TEXT
);

CREATE TABLE data_items (
    data_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    file_path TEXT NOT NULL,
    data_type TEXT NOT NULL,  -- 文件格式: fastq, fasta, kreport, tsv, gff...
    tier TEXT NOT NULL CHECK(tier IN ('raw','intermediate','result')),
    produced_by TEXT REFERENCES executions(execution_id),
    created_at REAL NOT NULL,
    metadata TEXT  -- JSON
);

CREATE TABLE execution_io (
    execution_id TEXT REFERENCES executions(execution_id),
    data_id TEXT REFERENCES data_items(data_id),
    direction TEXT CHECK(direction IN ('input','output')),
    PRIMARY KEY (execution_id, data_id, direction)
);
```

## tool.yaml 规范

```yaml
id: "fastp"
name: "fastp"
version: "0.23.4"
category: "qc"
conda_env: "fastp_env"
detection:
  command: "fastp --version"
  version_regex: "fastp (\\d+\\.\\d+\\.\\d+)"

inputs:
  - name: "reads_1"
    type: "fastq"
    required: true
    description: "正向读长文件"
  - name: "reads_2"
    type: "fastq"
    required: false
    description: "反向读长文件（双端测序）"

outputs:
  - name: "clean_1"
    type: "fastq"
    tier: "intermediate"
    pattern: "{output_dir}/{sample_id}.clean.R1.fq.gz"
  - name: "clean_2"
    type: "fastq"
    tier: "intermediate"
    pattern: "{output_dir}/{sample_id}.clean.R2.fq.gz"
  - name: "report_html"
    type: "html"
    tier: "result"
    pattern: "{output_dir}/{sample_id}.fastp.html"
  - name: "report_json"
    type: "json"
    tier: "result"
    pattern: "{output_dir}/{sample_id}.fastp.json"

parameters:
  - name: "qualified_quality_phred"
    type: "int"
    default: 15
    label: "最低质量值"
  - name: "length_required"
    type: "int"
    default: 50
    label: "最短读长"
  - name: "thread"
    type: "int"
    default: 4
    label: "线程数"

command_template: |
  conda run -n {conda_env} fastp \
    -i {reads_1} \
    {%- if reads_2 %} -I {reads_2} {%- endif %} \
    -o {clean_1} \
    {%- if reads_2 %} -O {clean_2} {%- endif %} \
    -h {report_html} \
    -j {report_json} \
    -q {qualified_quality_phred} \
    -l {length_required} \
    -w {thread}

databases: []  # fastp 不需要参考数据库
```

## 编码规范

- Python 3.11+
- 类型注解: 所有公开方法加 type hints
- 字符串: 使用 f-string
- 导入: 标准库 → 第三方 → 项目内，各组用空行分隔
- 命名: 类 PascalCase，方法/变量 snake_case，常量 UPPER_SNAKE
- 信号命名: 动词过去式 (task_completed, data_imported)
- 错误处理: 不吞异常，至少 logging.error()
- logging: 使用 `logging.getLogger(__name__)`
- 中文注释和 UI 文本

## 模块清单

### Phase 1 新建模块（已完成）
- `core/plugin_registry.py` — 三层懒加载插件注册表 (scan → descriptor → full)
- `core/project_manager.py` — 项目生命周期管理 + SQLite schema 创建
- `core/data_registry.py` — 数据血缘注册表，递归 CTE 查询祖先链
- `core/command_builder.py` — Jinja2 模板渲染 + conda env 包装 + 心跳脚本
- `core/job_dispatcher.py` — screen -dmS 远程提交，4步流程 (mkdir/write/chmod/screen)
- `core/job_monitor.py` — QThread 轮询监控，心跳超时 + screen 存活检测
- `core/data_importer.py` — SSH 上传 + DataRegistry 注册
- `core/tool_engine.py` — 12步 execute() 流程，Protocol 解耦依赖
- `core/job_queue.py` — deque + max_concurrent 并发控制
- `core/retry_manager.py` — 瞬态/永久错误分类，自动重试 ≤2 次
- `core/ssh_reconnector.py` — 指数退避重连 (2/4/8/16/32/60s)

### Phase 1 新建 UI
- `ui/pages/project_page.py` — 卡片式项目列表，创建/打开/归档
- `ui/widgets/input_data_selector.py` — 数据选择器，recommended_input_from 排序
- `ui/widgets/environment_status_bar.py` — SSH/项目/任务状态指示 (绿/黄/红)

### 插件 YAML
- `plugins/qc/fastp/tool.yaml`
- `plugins/taxonomy/kraken2/tool.yaml`
- `plugins/host_removal/hostile/tool.yaml`
- `plugins/blast/blastn/tool.yaml`

### 旧模块（仍在使用，Phase 2 迁移）
- `core/ssh_service.py` — SSH 封装（已增强：is_connected, connection_status_changed 信号）
- `core/blast_worker.py` — BLAST 异步任务 → 被 detection_page.py 引用
- `core/task_manager.py` — 任务记录 JSON 持久化 → 被 blast_worker, task_recovery_worker, task_history_card 引用
- `core/task_recovery_worker.py` — 任务恢复 → 被 detection_page.py 引用
- `core/accession_worker.py` — NCBI API 检索 → 被 home_page.py 引用
- `core/db_builder_worker.py` — 数据库构建 → 被 home_page.py 引用
- `ui/main_window.py` — 主窗口（已更新：项目切换器 + 环境状态栏）
- `ui/pages/` — detection_page, home_page, settings_page
- `ui/widgets/` — blast 相关卡片, ssh/ncbi/linux 设置卡片, styles
- `config.py` — 全局配置（将迁移为 settings.yaml）

## 服务器环境

- 服务器: `192.168.0.152`，用户 `zyserver`
- 旧版脚本路径: `/home/zyserver/project/lzc_project/project/h2oapp/`
- Core NT 数据库: `/home/zyserver/project_ssd/common_data/core_nt_database/`
- 新架构远端路径: `/h2ometa/projects/{project_id}/`

## 开发阶段

**Phase 1: 基础架构** — ✅ 已完成 (2026-03-06)

已达成里程碑:
- 插件注册表 + 4个 tool.yaml (fastp, kraken2, hostile, blastn)
- ToolEngine 12步执行流程
- SQLite 项目数据存储 + 数据血缘
- SSH 断线重连 + 任务重试
- 任务队列并发控制
- 308 个单元测试全部通过

**下一步: Phase 2 — 流程串联与 UI 迁移**
> 将旧 detection_page/home_page 迁移到新架构，实现 fastp → hostile → kraken2 → blastn 完整流水线。

## 测试

- 使用 pytest，运行于 `bio_ui` conda 环境 (Python 3.11)
- 测试文件放在 `tests/` 目录
- 命名: `test_{module_name}.py`
- Core 层模块必须有单元测试
- 当前测试文件: 11 个测试模块 + conftest.py，共 308 个测试用例
