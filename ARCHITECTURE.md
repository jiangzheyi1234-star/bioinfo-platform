# H2OMeta 宏基因组平台 — 架构设计文档

> 版本: v2.2 (Phase 2 进行中)
> 日期: 2026-03-09
> 状态: Phase 1 基础架构已完成，Phase 2 流程串联进行中

---

## 目录

1. [项目定位与目标](#1-项目定位与目标)
2. [现有系统概况](#2-现有系统概况)
3. [架构决策总表](#3-架构决策总表)
4. [系统全景架构](#4-系统全景架构)
5. [核心模块设计](#5-核心模块设计)
   - 5.1 插件系统 (Plugin System)
   - 5.2 项目管理 (Project Manager)
   - 5.3 数据存储 (SQLite)
   - 5.4 数据注册表 (Data Registry)
   - 5.5 数据导入 (Data Importer)
   - 5.6 工具引擎 (Tool Engine)
   - 5.7 任务队列与并发控制 (Job Queue)
   - 5.8 分析向导 (Analysis Wizard)
   - 5.9 数据库管理 (Database Manager)
   - 5.10 环境探测 (Environment Prober)
   - 5.11 结果可视化 (Visualization)
   - 5.12 重试与容错 (Retry & Fault Tolerance)
   - 5.13 存储与导出 (Storage & Export)
6. [目标文件结构](#6-目标文件结构)
7. [数据模型](#7-数据模型)
8. [YAML 配置体系与类型系统](#8-yaml-配置体系与类型系统)
9. [执行模型详解](#9-执行模型详解)
10. [存储策略](#10-存储策略)
11. [UI 设计原则](#11-ui-设计原则)
12. [主流方案对比评估](#12-主流方案对比评估)
13. [三阶段路线图](#13-三阶段路线图)
14. [风险与缓解](#14-风险与缓解)
15. [架构审查记录](#15-架构审查记录)

---

## 1. 项目定位与目标

**H2OMeta** 是面向生物信息学实验室的**桌面端宏基因组分析平台**。

### 核心定位

| 维度 | 定位 |
|------|------|
| 用户画像 | 湿实验室研究人员，具备基础命令行能力 |
| 部署模式 | Windows / Linux (有屏幕) 桌面客户端 + SSH 连接 Linux 计算服务器 |
| 核心价值 | 零命令行完成从原始测序数据到分析报告的全流程 |
| 差异化 | GUI 友好 + 中文界面 + 国内镜像 + 项目化管理 |

### 目标能力

1. **全流程覆盖**: QC → 宿主去除 → 物种分类 → 组装分箱 → 功能注释 → 统计可视化
2. **项目化隔离**: 每个分析项目独立管理，数据不交叉
3. **操作可追溯**: 自动记录每步参数，生成 Methods 文本和可复现配置
4. **容错健壮**: SSH 断线自恢复，任务失败可重试，结果不丢失
5. **扩展友好**: YAML 插件声明式添加新工具，为 Agent 集成预留接口

---

## 2. 现有系统概况

### 已实现功能

| 模块 | 状态 | 文件 |
|------|------|------|
| SSH 远程连接 | ✅ 完成 | `core/ssh_service.py` |
| SSH 指数退避重连 | ✅ 完成 | `core/ssh_reconnector.py` |
| 任务历史管理 | ✅ 完成 | `core/task_manager.py` |
| 系统设置（分步诊断+密钥认证） | ✅ 完成 | `ui/pages/settings_page.py` |

> 已清理的旧模块（2026-03-09）：`blast_worker.py`、`db_builder_worker.py`、`accession_worker.py`、`task_recovery_worker.py` — 功能已被 ToolEngine / JobMonitor / PluginRegistry 替代。

### 现有技术栈

- **GUI**: PyQt6
- **SSH**: Paramiko
- **数据处理**: Pandas
- **HTTP**: Requests
- **异步**: QThread + Screen 远程会话

### 迁移计划

| 现有模块 | 迁移目标 | 状态 |
|----------|----------|------|
| `blast_worker.py` | `plugins/blast/blastn/tool.yaml` + ToolEngine | ✅ 已删除，功能由 ToolEngine 替代 |
| `blast_main.sh` (远端) | 废弃 | ✅ 改为 command_template + JobDispatcher |
| `task_manager.py` | SQLite `executions` 表 | ⏳ task_history_card 仍在使用，保留 |
| `task_recovery_worker.py` | `job_monitor.py` | ✅ 已删除，功能由 JobMonitor 替代 |
| `db_builder_worker.py` | `database_manager.py` | ✅ 已删除 |
| `accession_worker.py` | 独立 NCBI 查询 | ✅ 已删除 |
| `config.py` | 逐步迁移到 `settings.yaml` | ⏳ 兼容过渡中 |

---

## 3. 架构决策总表

经与主流方案（Galaxy、nf-core/mag、QIIME 2、Terra、Anvi'o、bioBakery、ATLAS、CLC、Geneious、UGENE、Biomni）全面对比后，确认以下决策：

| # | 决策 | 方案 | 理由 |
|---|------|------|------|
| 1 | GUI 框架 | **PyQt6 桌面端** | 目标用户需要零部署桌面体验；UGENE/MEGA 同路线 |
| 2 | 远程执行 | **SSH + Screen + Conda** | 复用用户现有服务器，无需额外基础设施 |
| 3 | 插件系统 | **YAML 声明式 + 三层懒加载** | 添加工具不写代码，仅写 YAML |
| 4 | 工作流引擎 | **自建轻量引擎** | 避免 Nextflow/Snakemake 外部依赖 |
| 5 | 项目隔离 | **Project-based 隔离** | 项目作为数据和操作的边界 |
| 6 | 数据关联 | **手动确认 + 智能推荐** | 精确性优先于自动化 |
| 7 | 分析路径 | **向导模式 + 自由模式双轨** | 新手走向导，专家用自由模式 |
| 8 | 图表可视化 | **matplotlib + FigureCanvasQTAgg** | 纯 Python，零前端依赖，与 Qt 原生集成 |
| 8b | 复杂布局页面 | **QWebEngineView + HTML/CSS（仅 DetectionPage）** | 响应式工具列表 + 参数表单无法用 Qt 布局实现 |
| 9 | 工作流可视化 | **只读 DAG 状态视图** | 不做拖拽编辑器 |
| 10 | 存储 | **SQLite + 三层分级** | 事务安全，替代 JSON |
| 11 | 可复现导出 | **Methods 文本 + Snakefile + 参数表** | 论文、复现、归档三场景 |
| 12 | 数据库管理 | **管理中心 + 国内镜像 + 完整性校验** | 国内用户最大痛点 |
| 13 | Core 层边界 | **允许 QtCore，禁止 QtWidgets** | 务实方案，信号槽直接可用 |
| 14 | 类型系统 | **格式匹配 + 推荐排序** | tool.yaml 声明格式，paths 推荐来源 |
| 15 | 并发控制 | **客户端 JobQueue 限制并发数** | 按服务器配置动态调整 |
| 16 | 可视化分层 | **Core 解析数据 + UI 渲染图表** | Core 不依赖 QtWidgets |

---

## 4. 系统全景架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   桌面客户端 (PyQt6, Windows/Linux)                      │
│                                                                          │
│  ┌─── UI 层 (PyQt6.QtWidgets) ───────────────────────────────────────┐  │
│  │  MainWindow (侧边栏导航 + QStackedWidget)                         │  │
│  │  ├── ProjectPage      → 项目管理/切换                             │  │
│  │  ├── AnalysisPage     → 向导模式 + 自由模式                       │  │
│  │  │   ├── AnalysisWizardWidget (引导式分析)                        │  │
│  │  │   ├── ToolBrowserWidget    (工具浏览/自由选择)                  │  │
│  │  │   └── InputDataSelector    (输入数据手动确认)                   │  │
│  │  ├── ResultsPage      → 结果浏览/可视化                           │  │
│  │  │   └── ChartRenderer (QWebEngineView 嵌入)                      │  │
│  │  ├── DatabasePage     → 数据库管理中心                            │  │
│  │  ├── DetectionPage    → 病原体检测 (已有 BLAST)                   │  │
│  │  └── SettingsPage     → 系统设置                                  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              ↕ pyqtSignal                                │
│  ┌─── Core 层 (允许 QtCore，禁止 QtWidgets) ─────────────────────────┐  │
│  │                                                                    │  │
│  │  ToolEngine (QObject)  ← 统一执行入口                             │  │
│  │    ├── PluginRegistry     工具描述符注册 (YAML 懒加载)            │  │
│  │    ├── CommandBuilder     命令行构建 (模板填充)                    │  │
│  │    ├── JobDispatcher      任务分发 (screen 会话管理)              │  │
│  │    ├── JobMonitor (QThread) 状态轮询 + 心跳检测                   │  │
│  │    ├── JobQueue           并发控制 (客户端限制)                    │  │
│  │    └── RetryManager       重试策略                                │  │
│  │                                                                    │  │
│  │  ProjectManager (QObject) 项目生命周期管理                         │  │
│  │  DataRegistry             数据血缘追踪 (SQLite)                   │  │
│  │  DataImporter             本地文件 → 上传 → 注册                  │  │
│  │  AnalysisWizard           向导状态机                               │  │
│  │  DatabaseManager (QObject) 数据库安装/校验                        │  │
│  │  EnvironmentProber        环境批量探测 (从插件动态生成)           │  │
│  │  ResultSyncManager        结果选择性同步                           │  │
│  │  StorageManager           存储分级管理                             │  │
│  │  ProjectExporter          项目导出 (论文/复现/归档)               │  │
│  │  PipelineReconstructor    DAG 重建与溯源                          │  │
│  │  ChartDataParser          可视化数据解析 (纯数据，无 UI)          │  │
│  │                                                                    │  │
│  │  SSHService               SSH 连接封装                             │  │
│  │  SSHReconnector           指数退避重连                             │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                              ↕ Paramiko SSH                              │
└──────────────────────────────────────────────────────────────────────────┘
                               ↕ 网络通信
┌──────────────────────────────────────────────────────────────────────────┐
│                        Linux 计算服务器                                   │
│                                                                          │
│  /h2ometa/                                                               │
│  ├── envs/                    Conda 环境                                │
│  ├── databases/               参考数据库 (.install_ok 标记)             │
│  └── projects/                                                          │
│      └── proj_xxx/                                                      │
│          ├── raw/             原始数据 (永久)                           │
│          ├── intermediate/    中间结果 (可清理)                         │
│          ├── results/         最终结果 (永久，同步到本地)               │
│          └── provenance/      溯源记录                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 分层规则

```
UI 层:  可以导入 PyQt6.QtWidgets + PyQt6.QtCore + core/*
Core 层: 可以导入 PyQt6.QtCore (QObject/pyqtSignal/QThread)
         禁止导入 PyQt6.QtWidgets (QWidget/QPushButton/...)
```

---

## 5. 核心模块设计

### 5.1 插件系统 (Plugin System)

添加新分析工具 **只需编写一个 YAML 文件**，无需修改任何 Python 代码。

#### 三层懒加载

```
Layer 1 — 注册层 (启动时)
  扫描 plugins/**/tool.yaml → 读取 id + name + category → 构建目录索引
  耗时: <100ms

Layer 2 — 描述层 (用户点击工具时)
  加载完整 YAML → 参数定义、输入输出、数据库依赖
  耗时: <50ms

Layer 3 — 执行层 (点击运行时)
  检查环境 → 构建命令 → 分发任务
```

#### tool.yaml 完整规范

```yaml
# plugins/taxonomy/kraken2/tool.yaml
id: kraken2
name: Kraken2
version: "2.1.3"
category: taxonomy
description: "超快速 k-mer 物种分类"
conda_env: kraken2_env

# 输入定义 — type 为文件格式，不是语义类型
inputs:
  - name: reads
    type: fastq                 # 文件格式：fastq / fasta / kreport / contigs / ...
    required: true
    description: "质控后的 FASTQ 文件"

# 输出定义
outputs:
  - name: k2_report
    pattern: "{sample_id}.kreport"
    type: kreport
    tier: result
    sync_to_local: true
  - name: k2_output
    pattern: "{sample_id}.k2output"
    type: k2output
    tier: intermediate

# 参数定义
parameters:
  - name: confidence
    type: float
    default: 0.0
    range: [0.0, 1.0]
    description: "置信度阈值"
  - name: threads
    type: int
    default: 8
    range: [1, 64]
    description: "线程数"

# 命令模板
command_template: >
  kraken2
  --db {db}
  --threads {threads}
  --confidence {confidence}
  --report {output_dir}/{sample_id}.kreport
  --output {output_dir}/{sample_id}.k2output
  {input_reads}

# 数据库依赖
databases:
  - id: kraken2_standard
    param_name: db
    required: true

# 可视化声明
result_views:
  - type: stacked_bar
    title: "物种丰度堆叠图"
    data_source: "{sample_id}.kreport"
    config:
      top_n: 20
  - type: krona
    title: "Krona 交互式分类树"
    data_source: "{sample_id}.kreport"
  - type: table
    title: "分类结果明细"
    data_source: "{sample_id}.kreport"
    config:
      columns: [taxon_id, rank, name, fraction, reads]
      sortable: true

# Methods 模板
methods_template: >
  Taxonomic classification was performed using Kraken2 v{version}
  with the {db_name} database (confidence threshold = {confidence}).

# 环境检测
detection:
  command: "kraken2 --version"
  version_regex: "version (\\d+\\.\\d+\\.\\d+)"
```

#### PluginRegistry

```python
class PluginRegistry:
    """插件注册表 — 管理所有工具描述符"""

    def __init__(self, plugins_dir: str):
        self.plugins_dir = plugins_dir
        self._index: Dict[str, dict] = {}       # Layer 1
        self._descriptors: Dict[str, dict] = {}  # Layer 2

    def scan(self):
        for yaml_path in glob(f"{self.plugins_dir}/**/tool.yaml"):
            header = self._read_header(yaml_path)
            self._index[header['id']] = {
                'name': header['name'],
                'category': header['category'],
                'path': yaml_path,
            }

    def get_descriptor(self, tool_id: str) -> dict:
        if tool_id not in self._descriptors:
            path = self._index[tool_id]['path']
            self._descriptors[tool_id] = yaml.safe_load(open(path))
        return self._descriptors[tool_id]

    def list_by_category(self, category: str) -> List[dict]:
        return [v for v in self._index.values() if v['category'] == category]

    def list_all_ids(self) -> List[str]:
        return list(self._index.keys())
```

---

### 5.2 项目管理 (Project Manager)

参考 Galaxy History 模型：项目是数据和操作的隔离边界。

```python
@dataclass
class Project:
    project_id: str
    name: str
    description: str
    created_at: float
    status: str               # active / archived
    remote_base: str          # /h2ometa/projects/{project_id}

@dataclass
class Sample:
    sample_id: str
    name: str
    source: str               # human / water / soil / ...
    raw_files: List[str]
    metadata: Dict[str, str] = field(default_factory=dict)

class ProjectManager(QObject):
    project_changed = pyqtSignal(str)
    project_created = pyqtSignal(str)

    def create_project(self, name, description="") -> Project: ...
    def switch_project(self, project_id): ...
    def list_projects(self) -> List[Project]: ...
    def archive_project(self, project_id): ...

    @property
    def current(self) -> Optional[Project]: ...

    def _init_remote_dirs(self, project):
        self.ssh.run(f"mkdir -p {project.remote_base}/{{raw,intermediate,results,provenance}}")
```

---

### 5.3 数据存储 (SQLite)

用 SQLite 替代 JSON 文件，单文件事务安全。

每个项目一个数据库文件：`~/.h2ometa/projects/proj_xxx/project.db`

```sql
CREATE TABLE samples (
    sample_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT,
    metadata TEXT     -- JSON
);

CREATE TABLE executions (
    execution_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples,
    tool_id TEXT NOT NULL,
    tool_version TEXT,
    parameters TEXT NOT NULL,    -- JSON
    status TEXT NOT NULL,        -- pending/running/completed/failed/retrying
    triggered_by TEXT,           -- user/wizard/pipeline/agent
    created_at REAL NOT NULL,
    completed_at REAL,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    retry_of TEXT REFERENCES executions,
    remote_job_id TEXT
);

CREATE TABLE data_items (
    data_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples,
    file_path TEXT NOT NULL,     -- 远端绝对路径
    data_type TEXT NOT NULL,     -- 文件格式: fastq/kreport/contigs/...
    tier TEXT NOT NULL,          -- raw/intermediate/result
    produced_by TEXT REFERENCES executions,  -- NULL = 原始上传
    created_at REAL NOT NULL,
    metadata TEXT                -- JSON
);

CREATE TABLE execution_io (
    execution_id TEXT REFERENCES executions,
    data_id TEXT REFERENCES data_items,
    direction TEXT CHECK(direction IN ('input', 'output')),
    PRIMARY KEY (execution_id, data_id, direction)
);
```

血缘查询：
```sql
WITH RECURSIVE lineage AS (
    SELECT d.* FROM data_items d WHERE d.data_id = ?
    UNION ALL
    SELECT d2.*
    FROM lineage l
    JOIN execution_io ei_out ON ei_out.data_id = l.data_id AND ei_out.direction = 'output'
    JOIN execution_io ei_in ON ei_in.execution_id = ei_out.execution_id AND ei_in.direction = 'input'
    JOIN data_items d2 ON d2.data_id = ei_in.data_id
)
SELECT * FROM lineage;
```

---

### 5.4 数据注册表 (Data Registry)

基于 SQLite 的数据血缘追踪。

```python
class DataRegistry:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)

    def register_input(self, file_path, sample_id, data_type) -> str:
        """注册原始上传文件"""
        data_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO data_items VALUES (?,?,?,?,?,?,?,?)",
            (data_id, sample_id, file_path, data_type, "raw", None, time.time(), None)
        )
        self.conn.commit()
        return data_id

    def register_output(self, file_path, data_type, execution_id,
                        sample_id, tier="result") -> str:
        """注册工具输出文件"""
        data_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO data_items VALUES (?,?,?,?,?,?,?,?)",
            (data_id, sample_id, file_path, data_type, tier, execution_id, time.time(), None)
        )
        self.conn.execute(
            "INSERT INTO execution_io VALUES (?,?,?)",
            (execution_id, data_id, "output")
        )
        self.conn.commit()
        return data_id

    def find_compatible(self, sample_id: str, data_type: str) -> List[dict]:
        """按文件格式查找兼容数据"""
        rows = self.conn.execute(
            "SELECT * FROM data_items WHERE sample_id=? AND data_type=?",
            (sample_id, data_type)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_lineage(self, data_id: str) -> List[dict]:
        """递归追溯数据血缘链"""
        # 使用上方的 WITH RECURSIVE SQL
        ...
```

---

### 5.5 数据导入 (Data Importer)

通用的"本地文件 → 上传远端 → 注册到 DataRegistry"流程，**所有工具共用**。

```python
class DataImporter(QObject):
    """本地文件导入器"""
    upload_progress = pyqtSignal(str, int)   # filename, percent
    import_completed = pyqtSignal(str)        # data_id

    def import_file(self, local_path: str, sample_id: str,
                    data_type: str, project: Project) -> str:
        filename = os.path.basename(local_path)
        remote_path = f"{project.remote_base}/raw/{sample_id}/{filename}"

        self.ssh.run(f"mkdir -p {project.remote_base}/raw/{sample_id}")
        self.ssh.upload(local_path, remote_path)

        data_id = self.registry.register_input(
            file_path=remote_path,
            sample_id=sample_id,
            data_type=data_type,
        )
        self.import_completed.emit(data_id)
        return data_id

    def import_batch(self, files: List[dict], project: Project) -> List[str]:
        """批量导入: [{local_path, sample_id, data_type}, ...]"""
        data_ids = []
        for f in files:
            data_id = self.import_file(f['local_path'], f['sample_id'],
                                        f['data_type'], project)
            data_ids.append(data_id)
        return data_ids
```

UI 层调用流程：
```
用户选择文件 → DataImporter.import_file() → 得到 data_id
                                                  ↓
用户点击运行 → ToolEngine.execute(input_data_ids=[data_id], ...)
```

---

### 5.6 工具引擎 (Tool Engine)

**统一执行入口**：UI 直接点击、向导引导、未来 Agent 调用，都通过同一个 `execute()` 方法。

```python
@dataclass
class ExecutionRecord:
    execution_id: str
    project_id: str
    sample_id: str
    tool_id: str
    tool_version: str
    parameters: Dict[str, Any]
    status: str                   # pending/running/completed/failed/retrying
    triggered_by: str             # user/wizard/pipeline/agent
    created_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    retry_of: Optional[str] = None
    remote_job_id: Optional[str] = None

class ToolEngine(QObject):
    execution_started = pyqtSignal(str)
    execution_progress = pyqtSignal(str, str)
    execution_completed = pyqtSignal(str, bool)

    def __init__(self, ssh_service, plugin_registry, project_manager,
                 data_registry, database_manager, retry_manager, job_queue):
        self.ssh = ssh_service
        self.plugins = plugin_registry
        self.projects = project_manager
        self.registry = data_registry
        self.db_manager = database_manager
        self.retry = retry_manager
        self.queue = job_queue

    def execute(self, tool_id: str, input_data_ids: List[str],
                parameters: Dict[str, Any], sample_id: str,
                triggered_by: str = "user") -> str:
        project = self.projects.current
        if not project:
            raise ValueError("请先选择或创建项目")

        descriptor = self.plugins.get_descriptor(tool_id)
        merged_params = self._merge_defaults(descriptor, parameters)
        command = CommandBuilder.build(descriptor, merged_params,
                                       input_data_ids, sample_id, project)

        record = ExecutionRecord(
            execution_id=uuid.uuid4().hex[:12],
            project_id=project.project_id,
            sample_id=sample_id,
            tool_id=tool_id,
            tool_version=descriptor.get('version', 'unknown'),
            parameters=merged_params,
            status="pending",
            triggered_by=triggered_by,
            created_at=time.time(),
        )
        self._save_record(record)

        # 记录输入关系
        for data_id in input_data_ids:
            self.registry.add_execution_io(record.execution_id, data_id, "input")

        # 提交到 JobQueue（由队列控制是否立即执行）
        self.queue.submit(record, command, descriptor)
        return record.execution_id

    def _on_completed(self, execution_id, output_files):
        record = self._get_record(execution_id)
        for output in output_files:
            data_id = self.registry.register_output(
                file_path=output['path'],
                data_type=output['type'],
                execution_id=execution_id,
                sample_id=record.sample_id,
                tier=output.get('tier', 'result'),
            )
        record.status = "completed"
        record.completed_at = time.time()
        self._save_record(record)
        self.execution_completed.emit(execution_id, True)

    def _on_failed(self, execution_id, error):
        self.retry.on_task_failed(execution_id, error)
```

#### CommandBuilder

```python
class CommandBuilder:
    @staticmethod
    def build(descriptor, params, input_data_ids, sample_id, project) -> str:
        template = descriptor['command_template']
        context = {**params, 'sample_id': sample_id}
        context['output_dir'] = f"{project.remote_base}/intermediate/{sample_id}/{descriptor['id']}"

        # 填充输入文件路径
        for i, inp in enumerate(descriptor.get('inputs', [])):
            data_item = registry.get_item(input_data_ids[i])
            context[f"input_{inp['name']}"] = data_item['file_path']

        # 数据库路径
        for db_dep in descriptor.get('databases', []):
            context[db_dep['param_name']] = db_manager.get_path(db_dep['id'])

        cmd = template.format(**context)

        # conda 激活
        conda_env = descriptor.get('conda_env')
        if conda_env:
            cmd = f"conda run -n {conda_env} {cmd}"

        return cmd
```

#### JobDispatcher

```python
class JobDispatcher:
    @staticmethod
    def submit(ssh, command, execution_id) -> str:
        job_id = f"h2o_{execution_id}"

        # 通用包装：退出码 + 心跳 + 日志
        wrapped = (
            f'_hb() {{ while true; do date +%s > /tmp/{job_id}.heartbeat; sleep 60; done; }}; '
            f'_hb & HB_PID=$!; '
            f'trap "kill $HB_PID 2>/dev/null; echo \\$? > /tmp/{job_id}.exit_code" EXIT; '
            f'exec > >(tee /tmp/{job_id}.stdout.log) 2> >(tee /tmp/{job_id}.stderr.log >&2); '
            f'{command}'
        )

        screen_cmd = f"screen -dmS {job_id} bash -c '{wrapped}'"
        rc, _, err = ssh.run(screen_cmd, timeout=15)
        if rc != 0:
            raise RuntimeError(f"screen 启动失败: {err}")
        return job_id
```

---

### 5.7 任务队列与并发控制 (Job Queue)

客户端控制并发数，根据服务器配置调整。

```python
class JobQueue(QObject):
    """任务队列 — 控制同时运行的 screen 会话数量"""

    job_started = pyqtSignal(str)   # execution_id
    queue_updated = pyqtSignal(int) # 排队中数量

    def __init__(self, ssh_service, max_concurrent=3):
        self.ssh = ssh_service
        self.max_concurrent = max_concurrent
        self._pending = deque()
        self._running: Dict[str, ExecutionRecord] = {}

    def submit(self, record, command, descriptor):
        if len(self._running) < self.max_concurrent:
            self._start(record, command, descriptor)
        else:
            self._pending.append((record, command, descriptor))
            self.queue_updated.emit(len(self._pending))

    def on_job_finished(self, execution_id):
        if execution_id in self._running:
            del self._running[execution_id]
        if self._pending:
            record, command, descriptor = self._pending.popleft()
            self._start(record, command, descriptor)
            self.queue_updated.emit(len(self._pending))

    def _start(self, record, command, descriptor):
        job_id = JobDispatcher.submit(self.ssh, command, record.execution_id)
        record.remote_job_id = job_id
        record.status = "running"
        self._running[record.execution_id] = record
        self.job_started.emit(record.execution_id)

    def update_max_concurrent(self, n: int):
        """用户修改并发数"""
        self.max_concurrent = n
```

**并发数确定**：
- 用户手动设置（设置页面"最大并行任务数"，默认 3）
- 可选自动探测：连接时 `nproc` + `free -g`，给出建议值，用户可覆盖

---

### 5.8 分析向导 (Analysis Wizard)

#### analysis_paths.yaml — 类型系统

**关键设计**：`input_type` 只声明文件格式，`recommended_input_from` 控制推荐排序。

```yaml
paths:
  read_based:
    name: "读长分析路径"
    stages:
      - id: qc
        name: "质量控制"
        required: true
        tools: [fastp, trimmomatic, bbduk]
        default: fastp
        input_type: fastq             # 文件格式匹配
        output_type: fastq
        description: "去除低质量读长和接头序列"

      - id: host_removal
        name: "宿主去除"
        required_when: "sample.source in ['human', 'animal', 'plant']"
        tools: [hostile, kneaddata, bowtie2]
        default: hostile
        input_type: fastq
        output_type: fastq
        depends_on: [qc]
        recommended_input_from: [qc]   # 推荐从 QC 阶段的输出取
        description: "去除宿主来源的读长"

      - id: taxonomy
        name: "物种分类"
        required: true
        tools: [kraken2, metaphlan4, motus3, centrifuge]
        default: kraken2
        allow_multiple: true
        input_type: fastq
        output_type: kreport
        depends_on: [host_removal]
        recommended_input_from: [host_removal, qc]  # 优先去宿主后的，其次 QC 后的
        description: "鉴定样本中的微生物组成"

      - id: abundance
        name: "丰度重估"
        required: false
        tools: [bracken]
        default: bracken
        input_type: kreport
        output_type: tsv
        depends_on: [taxonomy]
        recommended_input_from: [taxonomy]

      - id: functional
        name: "功能注释"
        required: false
        tools: [humann3, mifaser]
        default: humann3
        input_type: fastq
        output_type: tsv
        depends_on: [host_removal]
        recommended_input_from: [host_removal]

      - id: statistics
        name: "统计分析"
        required: false
        tools: [diversity_calc, lefse, deseq2]
        default: diversity_calc
        input_type: tsv
        output_type: tsv
        depends_on: [abundance]
        recommended_input_from: [abundance]

  assembly_based:
    name: "组装分析路径"
    stages:
      - id: qc
        name: "质量控制"
        required: true
        tools: [fastp, trimmomatic]
        default: fastp
        input_type: fastq
        output_type: fastq

      - id: host_removal
        name: "宿主去除"
        required_when: "sample.source in ['human', 'animal']"
        tools: [hostile, kneaddata]
        default: hostile
        input_type: fastq
        output_type: fastq
        depends_on: [qc]
        recommended_input_from: [qc]

      - id: assembly
        name: "宏基因组组装"
        required: true
        tools: [megahit, metaspades]
        default: megahit
        input_type: fastq
        output_type: fasta
        depends_on: [host_removal]
        recommended_input_from: [host_removal]

      - id: binning
        name: "分箱"
        required: true
        tools: [metabat2, maxbin2, concoct, das_tool]
        default: metabat2
        input_type: fasta
        output_type: fasta
        depends_on: [assembly]
        recommended_input_from: [assembly]

      - id: mag_qc
        name: "MAG 质量评估"
        required: true
        tools: [checkm2, busco]
        default: checkm2
        input_type: fasta
        output_type: tsv
        depends_on: [binning]
        recommended_input_from: [binning]

      - id: mag_taxonomy
        name: "MAG 分类注释"
        required: false
        tools: [gtdbtk]
        default: gtdbtk
        input_type: fasta
        output_type: tsv
        depends_on: [mag_qc]
        recommended_input_from: [binning]

      - id: mag_annotation
        name: "MAG 功能注释"
        required: false
        tools: [prokka, bakta, eggnog]
        default: prokka
        input_type: fasta
        output_type: gff
        depends_on: [mag_qc]
        recommended_input_from: [binning]
```

#### InputDataSelector 匹配逻辑

```
1. DataRegistry.find_compatible(sample_id, "fastq")
   → 返回该样本所有 fastq 类型的数据（可能 5 个：原始、QC 后、去宿主后...）

2. 按 recommended_input_from 排序:
   → 如果当前阶段 recommended_input_from: [host_removal, qc]
   → produced_by 为 host_removal 工具的输出排第一
   → produced_by 为 qc 工具的输出排第二
   → 其他（原始上传等）排后面

3. 用户看到排好序的列表，每个条目显示来源标签:
   "sample_001.clean.fq — 来自 hostile (3月5日)"
   "sample_001.trimmed.fq — 来自 fastp (3月5日)"
   "sample_001.raw.fq — 原始上传 (3月4日)"

4. 用户点击选择 → 选择即确认
```

#### AnalysisWizard

```python
class AnalysisWizard:
    def __init__(self, paths_config, tool_engine, data_registry):
        self.paths = paths_config
        self.engine = tool_engine
        self.registry = data_registry
        self.session: Optional[AnalysisSession] = None

    def start_session(self, project_id, path_id) -> AnalysisSession:
        ...

    def get_current_stage(self) -> dict:
        ...

    def get_recommended_inputs(self, stage_id, sample_id) -> List[dict]:
        """获取推荐排序后的可选输入"""
        stage = self._find_stage(stage_id)
        all_compatible = self.registry.find_compatible(sample_id, stage['input_type'])
        recommended_from = stage.get('recommended_input_from', [])
        return self._sort_by_recommendation(all_compatible, recommended_from)

    def run_stage(self, stage_id, tool_id, parameters, confirmed_inputs):
        """confirmed_inputs: {sample_id: data_id}"""
        for sample_id, data_id in confirmed_inputs.items():
            self.engine.execute(
                tool_id=tool_id,
                input_data_ids=[data_id],
                parameters=parameters,
                sample_id=sample_id,
                triggered_by="wizard",
            )

    def advance_stage(self): ...
    def skip_stage(self): ...
    def is_complete(self) -> bool: ...
```

---

### 5.9 数据库管理 (Database Manager)

见原文档 5.6 节，无变化。核心要点：

- **databases.yaml** 定义所有数据库：镜像列表、安装方式、完整性校验
- **四种状态**: installed / missing / incomplete / downloading
- **国内镜像优先**
- **完整性校验**: key_files + .install_ok 标记 + min_size_mb

---

### 5.10 环境探测 (Environment Prober)

**从 PluginRegistry 动态生成探测脚本**，不硬编码工具列表。

```python
class EnvironmentProber:
    CACHE_TTL = 300

    def __init__(self, ssh_service, plugin_registry, db_manager):
        self.ssh = ssh_service
        self.plugins = plugin_registry
        self.db_manager = db_manager
        self._cache: Optional[EnvironmentStatus] = None

    def probe_all(self) -> EnvironmentStatus:
        script = self._build_probe_script()
        rc, output, _ = self.ssh.run(f"bash << 'PROBE_EOF'\n{script}\nPROBE_EOF", timeout=30)
        self._cache = self._parse_output(output)
        return self._cache

    def _build_probe_script(self) -> str:
        lines = []

        # conda 环境列表
        lines.append('echo "===CONDA_ENVS==="')
        lines.append("conda env list 2>/dev/null | grep -v '^#' | awk '{print $1}' | grep -v '^$'")

        # 工具检测 — 从 PluginRegistry 动态生成
        lines.append('echo "===TOOLS==="')
        for tool_id in self.plugins.list_all_ids():
            desc = self.plugins.get_descriptor(tool_id)
            env = desc.get('conda_env', '')
            detect = desc.get('detection', {})
            cmd = detect.get('command', f'{tool_id} --version')
            if env:
                lines.append(f'ver=$(conda run -n {env} {cmd} 2>&1 | head -1 || echo NOT_FOUND); echo "{tool_id}|$ver"')
            else:
                lines.append(f'ver=$({cmd} 2>&1 | head -1 || echo NOT_FOUND); echo "{tool_id}|$ver"')

        # 磁盘
        lines.append('echo "===DISK==="')
        lines.append('df -BG /h2ometa 2>/dev/null | tail -1 || df -BG / | tail -1')

        # screen 会话
        lines.append('echo "===SCREENS==="')
        lines.append('screen -ls 2>/dev/null || echo NONE')

        # 数据库 — 批量检测
        lines.append('echo "===DATABASES==="')
        for db_id, db_config in self.db_manager.config['databases'].items():
            path = db_config['install_path']
            marker = db_config['integrity_check']['status_file']
            lines.append(f'echo "{db_id}|$(test -f {path}/{marker} && echo OK || echo MISSING)|$(du -sm {path} 2>/dev/null | cut -f1 || echo 0)"')

        return "\n".join(lines)

    def check_ready(self, tool_id: str) -> dict:
        """运行前精确检查"""
        descriptor = self.plugins.get_descriptor(tool_id)
        issues = []
        env = descriptor.get('conda_env')
        if env:
            rc, _, _ = self.ssh.run(f"conda env list | grep -q {env}")
            if rc != 0:
                issues.append(f"Conda 环境 '{env}' 不存在")
        for db_dep in descriptor.get('databases', []):
            status = self.db_manager.check_status(db_dep['id'])
            if status['status'] != 'installed':
                issues.append(f"数据库 {db_dep['id']} 状态: {status['status']}")
        return {"ready": len(issues) == 0, "issues": issues}
```

---

### 5.11 结果可视化 (Visualization)

**分两层**：Core 层解析数据，UI 层渲染图表。

#### Core 层：ChartDataParser

```python
# core/chart_parser.py — 纯数据处理，不依赖 QtWidgets
class ChartDataParser:
    PARSERS = {
        'stacked_bar': '_parse_stacked_bar',
        'krona': '_parse_krona',
        'heatmap': '_parse_heatmap',
        'table': '_parse_table',
        'pcoa': '_parse_pcoa',
        'boxplot': '_parse_boxplot',
    }

    def parse(self, view_config: dict, data_path: str) -> dict:
        parser_name = self.PARSERS.get(view_config['type'], '_parse_default')
        parser = getattr(self, parser_name)
        return {
            "type": view_config['type'],
            "title": view_config.get('title', ''),
            "data": parser(data_path, view_config.get('config', {})),
        }

    def _parse_stacked_bar(self, data_path, config) -> dict:
        df = pd.read_csv(data_path, sep='\t')
        top_n = config.get('top_n', 20)
        return {
            "labels": df.iloc[:top_n, 0].tolist(),
            "values": df.iloc[:top_n, 1].tolist(),
        }
    # ... 其他 parser
```

#### UI 层：ChartRenderer

```python
# ui/widgets/chart_renderer.py — 依赖 QtWidgets
class ChartRenderer:
    RENDERERS = {
        'stacked_bar': PlotlyRenderer,
        'krona': KronaRenderer,
        'heatmap': EChartsRenderer,
        'table': TableRenderer,       # QTableView
        'pcoa': PlotlyRenderer,
        'boxplot': PlotlyRenderer,
    }

    def render(self, chart_data: dict) -> QWidget:
        renderer_cls = self.RENDERERS.get(chart_data['type'])
        if not renderer_cls:
            return QLabel(f"不支持的图表类型: {chart_data['type']}")
        return renderer_cls().to_widget(chart_data)
```

UI 调用：
```python
data = self.chart_parser.parse(view_config, local_data_path)   # Core 层
widget = self.chart_renderer.render(data)                       # UI 层
```

---

### 5.12 重试与容错 (Retry & Fault Tolerance)

见原文档 5.9 节，无变化。核心要点：

- **SSHReconnector**: 指数退避重连 (2/4/8/16/32/60 秒)
- **ScreenHeartbeat**: screen 存活检测 + .exit_code + 心跳文件
- **TaskRetryManager**: 瞬时错误自动重试 (≤2 次) + 永久错误手动重试
- **CheckpointManager**: 输入+参数哈希匹配，相同已完成记录可复用
- **远端脚本通用包装**: trap exit_code + heartbeat + 日志分离

---

### 5.13 存储与导出 (Storage & Export)

见原文档 5.10 节，无变化。核心要点：

- **三层存储**: raw (永久/仅服务器) → intermediate (可清理) → results (永久/同步本地)
- **ResultSyncManager**: 任务完成自动同步 tier=result 文件
- **StorageManager**: 磁盘监控 + intermediate 自动清理
- **ProjectExporter**: 论文导出 (methods.txt + parameters.csv) / 复现导出 (Snakefile + config) / 归档导出
- **PipelineReconstructor**: 从 SQLite 执行记录 + execution_io 重建 DAG

---

## 6. 目标文件结构

```
bio_ui/
├── config.py                          # 全局配置 (保留，逐步迁移)
├── ARCHITECTURE.md                    # 本文档
│
├── config/                            # YAML 配置文件
│   ├── analysis_paths.yaml            # 分析路径定义
│   └── databases.yaml                 # 参考数据库定义
│
├── plugins/                           # 工具插件 (纯 YAML)
│   ├── qc/
│   │   ├── fastp/tool.yaml
│   │   └── trimmomatic/tool.yaml
│   ├── host_removal/
│   │   ├── hostile/tool.yaml
│   │   └── kneaddata/tool.yaml
│   ├── taxonomy/
│   │   ├── kraken2/tool.yaml
│   │   ├── metaphlan4/tool.yaml
│   │   └── motus3/tool.yaml
│   ├── assembly/
│   │   ├── megahit/tool.yaml
│   │   └── metaspades/tool.yaml
│   ├── binning/
│   │   ├── metabat2/tool.yaml
│   │   └── das_tool/tool.yaml
│   ├── annotation/
│   │   ├── prokka/tool.yaml
│   │   └── eggnog/tool.yaml
│   ├── statistics/
│   │   └── diversity_calc/tool.yaml
│   └── blast/
│       └── blastn/tool.yaml           # 现有 BLAST 迁移为普通插件
│
├── core/                              # Core 层 (允许 QtCore，禁止 QtWidgets)
│   ├── ssh_service.py                 # SSH 封装 (已有，增强重连)
│   ├── ssh_reconnector.py             # 指数退避重连
│   ├── plugin_registry.py             # 插件注册表
│   ├── project_manager.py             # 项目管理
│   ├── data_registry.py               # 数据注册表 (SQLite)
│   ├── data_importer.py               # 本地文件导入 (新增)
│   ├── tool_engine.py                 # 统一执行引擎
│   ├── command_builder.py             # 命令构建器
│   ├── job_dispatcher.py              # 任务分发 (screen)
│   ├── job_monitor.py                 # 任务监控 (QThread 轮询+心跳)
│   ├── job_queue.py                   # 并发控制队列 (新增)
│   ├── retry_manager.py               # 重试管理
│   ├── checkpoint_manager.py          # 断点续传
│   ├── analysis_wizard.py             # 分析向导
│   ├── database_manager.py            # 数据库管理
│   ├── environment_prober.py          # 环境探测 (从插件动态生成)
│   ├── result_sync.py                 # 结果同步
│   ├── storage_manager.py             # 存储管理
│   ├── project_exporter.py            # 项目导出
│   ├── pipeline_reconstructor.py      # DAG 重建
│   ├── chart_parser.py                # 可视化数据解析 (纯数据，新增)
│   │
│   └── task_manager.py                # (已有) → 逐步迁入 SQLite
│
├── ui/                                # UI 层 (PyQt6.QtWidgets)
│   ├── main.py                        # 应用入口
│   ├── main_window.py                 # 主窗口
│   ├── page_base.py                   # 页面基类
│   ├── pages/
│   │   ├── project_page.py            # 项目管理页 (新增)
│   │   ├── analysis_page.py           # 分析工作台 (新增)
│   │   ├── results_page.py            # 结果浏览/可视化 (新增)
│   │   ├── database_page.py           # 数据库管理 (新增)
│   │   ├── home_page.py               # (已有)
│   │   ├── detection_page.py          # (已有)
│   │   └── settings_page.py           # (已有)
│   └── widgets/
│       ├── styles.py                  # (已有) 样式系统
│       ├── input_data_selector.py     # 输入数据选择器 (新增)
│       ├── chart_renderer.py          # 图表渲染器 (新增, QWebEngineView)
│       ├── dag_status_view.py         # DAG 状态视图 (新增, 只读)
│       ├── wizard_step_widget.py      # 向导步骤组件 (新增)
│       ├── tool_browser_widget.py     # 工具浏览器 (新增)
│       ├── db_install_card.py         # 数据库安装卡片 (新增)
│       ├── environment_status_bar.py  # 环境状态栏 (新增)
│       ├── ssh_settings_card.py       # (已有)
│       ├── blast_*.py                 # (已有)
│       ├── task_history_card.py       # (已有)
│       └── ...
│
└── tests/
    ├── test_plugin_registry.py
    ├── test_data_registry.py
    ├── test_command_builder.py
    └── ...
```

---

## 7. 数据模型

### 实体关系

```
Project (1) ─── (N) Sample
    │                  │
    │                  │
    └──── (N) ExecutionRecord ──── execution_io ──── (N) DataItem
                │                  (input/output)          │
                │                                          │
                └── retry_of → ExecutionRecord              └── produced_by → ExecutionRecord
                └── tool_id → PluginDescriptor (YAML)
```

### 状态机

```
ExecutionRecord:
  pending → running → completed
                   → failed → retrying → running → ...
                                       → failed (最终)

JobQueue:
  submit → pending (排队) → running (执行) → completed/failed

Project:
  active → archived

DataItem tier:
  raw (永久) | intermediate (可清理) | result (永久+同步)
```

---

## 8. YAML 配置体系与类型系统

### 类型系统设计

**核心原则**：tool.yaml 只声明文件格式，analysis_paths.yaml 用 `recommended_input_from` 推荐来源。

```
tool.yaml inputs.type  = 文件格式 (fastq / fasta / kreport / tsv / gff / ...)
analysis_paths.yaml input_type = 同一套文件格式
analysis_paths.yaml recommended_input_from = 推荐从哪个阶段取输入
```

**匹配流程**：
1. `find_compatible(sample_id, format)` → 按格式粗筛
2. `recommended_input_from` → 按来源排序
3. 用户手动选择 → 选择即确认

### YAML 文件总览

| YAML 文件 | 职责 | 修改频率 |
|-----------|------|----------|
| `plugins/*/tool.yaml` | 工具定义 | 添加新工具时 |
| `config/analysis_paths.yaml` | 分析路径定义 | 极少 |
| `config/databases.yaml` | 数据库定义 | 添加新数据库时 |
| `~/.h2ometa/settings.yaml` | 用户设置 | 用户修改 |

### 扩展新工具

```
1. 创建: plugins/{category}/{tool_name}/tool.yaml
2. 填写: id, name, category, inputs, outputs, parameters, command_template
3. 重启应用
4. 新工具自动出现 → 环境探测自动覆盖
```

零 Python 代码修改。

---

## 9. 执行模型详解

### 完整生命周期

```
用户选择文件 → DataImporter.import_file() → data_id
    │
    ▼
用户点击"运行" (或向导"下一步")
    │
    ▼
ToolEngine.execute()
    ├── 1. 加载 tool.yaml 描述符
    ├── 2. 验证输入数据归属当前项目
    ├── 3. 合并默认参数
    ├── 4. EnvironmentProber.check_ready() → 检查工具+数据库
    │       └── 未就绪 → 提示安装 → 跳转数据库管理页
    ├── 5. CommandBuilder.build() → 生成远程命令
    ├── 6. 创建 ExecutionRecord (SQLite)
    ├── 7. 记录 execution_io (input)
    └── 8. JobQueue.submit()
            │
            ├── 队列未满 → JobDispatcher.submit() → screen -dmS 启动
            │               └── 通用包装: trap + 心跳 + 日志
            └── 队列已满 → 排队等待
                            └── UI 显示"排队中 (第N位)"
    │
    ▼ (JobMonitor QThread 轮询)
ScreenHeartbeat.check_job()
    ├── running → 继续轮询
    ├── completed → ToolEngine._on_completed()
    │       ├── 注册输出到 DataRegistry (SQLite)
    │       ├── ResultSyncManager 同步 tier=result 文件
    │       ├── JobQueue.on_job_finished() → 启动下一个排队任务
    │       └── 通知 UI
    ├── failed → RetryManager.on_task_failed()
    │       ├── 瞬时错误 → 自动重试 (≤2次)
    │       └── 永久错误 → UI 显示失败 + 手动重试按钮
    ├── stalled → UI 提示 "任务可能卡住"
    └── crashed → UI 提示 "任务异常终止" + 重试按钮
```

### SSH 断线恢复

```
SSH 连接断开
    │
    ▼
SSHReconnector (指数退避: 2/4/8/16/32/60秒)
    ├── 重连成功 → screen -ls 检查会话
    │       ├── 会话存在 → 继续监控
    │       └── 会话不存在 → check_exit_code → 判断完成/崩溃
    └── 重连失败 (5次) → UI 提示 "连接中断"
            └── 用户手动重连 → 恢复所有 running 状态任务的监控
```

---

## 10. 存储策略

### 本地存储

```
~/.h2ometa/
├── settings.yaml
├── projects.json              # 项目列表索引
└── projects/
    └── proj_xxx/
        ├── project.db         # SQLite (samples + executions + data_items + execution_io)
        └── cache/results/     # 本地缓存的结果文件
```

### 远端存储

```
/h2ometa/
├── envs/                      # Conda 环境
├── databases/                 # 参考数据库
└── projects/
    └── proj_xxx/
        ├── raw/               # 永久
        ├── intermediate/      # 可清理
        ├── results/           # 永久，同步到本地
        └── provenance/        # 溯源
```

---

## 11. UI 设计原则

### 导航结构

```
侧边栏:
  项目管理           → 创建/切换/归档项目
  分析工作台         → 向导模式 / 自由模式
  结果浏览           → 可视化 / 表格 / 导出
  数据库管理         → 安装/检查/更新
  ──────────
  病原体检测         → (已有 BLAST 功能)
  项目首页           → (已有)
  系统设置           → (已有)
```

### 关键交互

1. **项目切换器**: 顶部当前项目名，下拉切换
2. **环境状态栏**: 底部 SSH 状态 + 工具/数据库就绪度
3. **向导模式**: 左侧阶段列表 + 右侧配置面板
4. **自由模式**: 工具浏览器 + 参数面板 + InputDataSelector
5. **结果浏览**: Tab 切换视图，图表嵌入 QWebEngineView
6. **DAG 视图**: 只读流程图，节点颜色表示状态
7. **数据库管理**: 卡片式列表，状态/大小/操作按钮
8. **任务队列**: 显示排队中/运行中/已完成任务，可调并发数

---

## 12. 主流方案对比评估

| 能力维度 | Galaxy | nf-core/mag | QIIME 2 | Terra | H2OMeta |
|----------|--------|-------------|---------|-------|---------|
| 部署复杂度 | 高 | 中 | 低 | 低 | **极低** |
| 学习曲线 | 中 | 高 | 高 | 中 | **低** |
| 工具扩展 | XML | Nextflow DSL | 插件 | WDL | **YAML** |
| 可视化 | 有限 | 无 | 有 | 有限 | Plotly+Krona |
| 断点续传 | 有 | -resume | 有 | 有 | 哈希匹配 |
| 数据溯源 | History | 无 | Artifact | 无 | SQLite 血缘 |
| 中文支持 | 无 | 无 | 无 | 无 | **原生** |
| 国内镜像 | 无 | 无 | 无 | 无 | **内置** |
| 并发控制 | 有 | 有 | 无 | 有 | **客户端队列** |

---

## 13. 三阶段路线图

### Phase 1: 基础架构 — ✅ 已完成 (2026-03-06)

| 任务 | 优先级 | 状态 |
|------|--------|------|
| PluginRegistry (三层懒加载) | P0 | ✅ `core/plugin_registry.py` |
| ProjectManager + SQLite 存储 | P0 | ✅ `core/project_manager.py` |
| DataRegistry + DataImporter | P0 | ✅ `core/data_registry.py` + `core/data_importer.py` |
| ToolEngine + CommandBuilder | P0 | ✅ `core/tool_engine.py` + `core/command_builder.py` |
| JobDispatcher + JobMonitor | P0 | ✅ `core/job_dispatcher.py` + `core/job_monitor.py` |
| JobQueue (并发控制) | P0 | ✅ `core/job_queue.py` |
| SSHReconnector | P1 | ✅ `core/ssh_reconnector.py` |
| RetryManager | P1 | ✅ `core/retry_manager.py` |
| UI: 项目管理页 | P1 | ✅ `ui/pages/project_page.py` |
| UI: InputDataSelector | P1 | ✅ `ui/widgets/input_data_selector.py` |
| 首批 tool.yaml: fastp + kraken2 + hostile + blastn | P1 | ✅ `plugins/` 目录 |

**里程碑**: fastp → Kraken2 通过 ToolEngine 执行，数据有血缘，SQLite 存储。
**测试**: 308 个单元测试 + 集成测试全部通过。

### Phase 2: 分析能力 — 进行中

| 任务 | 优先级 | 状态 |
|------|--------|------|
| ServiceLocator 服务总线 | P0 | ✅ `core/service_locator.py` |
| PipelineRunner 流水线编排 | P0 | ✅ `core/pipeline_runner.py` |
| UI: 分析工作台 (读长分析) | P0 | ✅ `ui/pages/analysis_page.py` |
| UI: 组装分析页 (7阶段) | P0 | ✅ `ui/pages/assembly_page.py` |
| UI: 插件工作台 (Galaxy 风格) | P0 | ✅ `ui/pages/detection_page_web.py` |
| UI: 样本管理中心 | P1 | ✅ `ui/pages/home_page.py` |
| SSH 设置优化 (分步诊断+密钥+重连) | P1 | ✅ `ui/widgets/ssh_settings_card.py` |
| 遗留代码清理 | P2 | ✅ 删除 5 个无引用旧模块 |
| ChartDataParser + ChartRenderer | P1 | ⏳ |
| DatabaseManager + databases.yaml | P0 | ⏳ |
| UI: 结果浏览页 | P1 | ⏳ |
| UI: 数据库管理页 | P0 | ⏳ |
| 完整 tool.yaml 集合 | P1 | ⏳ |

**里程碑**: 完整读长分析路径可运行。

### Phase 3: 完善体验 (4-6 周)

| 任务 | 优先级 |
|------|--------|
| ProjectExporter (论文/复现/归档) | P0 |
| Methods 自动生成 | P0 |
| Snakefile 导出 | P1 |
| StorageManager | P1 |
| ECharts 集成 | P2 |
| PipelineReconstructor + DAG 视图 | P2 |
| 组装路径工具集 | P1 |
| databases.yaml 完善 | P1 |

**里程碑**: 完整可用平台，可生成论文级输出。

---

## 14. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 工具版本不兼容 | 中 | 中 | Conda 环境隔离 |
| 大文件传输失败 | 中 | 低 | SFTP 断点续传 |
| 远端磁盘满 | 高 | 中 | StorageManager 监控 + intermediate 清理 |
| 国内镜像不可用 | 低 | 中 | 多镜像 fallback |
| Screen 被清理 | 低 | 高 | .exit_code + 心跳 + 自动恢复 |
| QWebEngineView 兼容性 | 低 | 中 | 降级到 Matplotlib 静态图 |
| YAML 插件写错 | 中 | 低 | 启动时 schema 校验 |

---

## 15. 架构审查记录

v2.1 版本经过逐项审查，确认以下修订：

| # | 问题 | 原设计 | 修订后 | 理由 |
|---|------|--------|--------|------|
| 1 | Core 层依赖 | "纯 Python" | 允许 QtCore，禁止 QtWidgets | 避免过度设计，与现有代码一致 |
| 2 | 数据存储 | 多个 JSON 文件 | SQLite (project.db) | 事务安全，跨文件引用问题消解 |
| 3 | 线程模型 | 未明确 | ToolEngine 直接用 QThread + pyqtSignal | Core 允许 QtCore 后自然解决 |
| 4 | 类型系统 | analysis_paths 用语义类型 | 统一用文件格式 + recommended_input_from 推荐 | 与手动确认机制配合最好 |
| 5 | 并发策略 | 未定义 | JobQueue 客户端限制，按服务器配置调整 | 防止 OOM，用户可控 |
| 6 | 环境探测 | 硬编码工具列表 | 从 PluginRegistry 动态生成 | 新增插件自动覆盖 |
| 7 | BLAST 迁移 | 未明确 | 新增 DataImporter，废弃 blast_main.sh，BLAST 变为 tool.yaml 插件 | 统一所有工具的执行方式 |
| 8 | ChartEngine | 整体放 Core 层 | 拆分为 ChartDataParser (Core) + ChartRenderer (UI) | Core 不依赖 QtWidgets |

---

> 本文档 v2.2 版，Phase 1 已完成，Phase 2 进行中。最后更新: 2026-03-09。
