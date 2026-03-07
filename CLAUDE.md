# H2OMeta — Claude 开发指令

> 产品需求见 `PRODUCT.md`，技术架构见 `ARCHITECTURE.md`。

## 架构规则

- **Core 层**：只允许 `PyQt6.QtCore`（QObject/pyqtSignal/QThread），禁止 QtWidgets/QtGui
- **UI 层**：新建 `ui/widgets/` 或 `ui/pages/` 文件后，**必须同步更新对应 `__init__.py`**
- **插件**：`plugins/{category}/{tool_name}/tool.yaml`，规范见 ARCHITECTURE.md §5.1
- **可视化**：matplotlib + FigureCanvasQTAgg，不用 QWebEngineView + ECharts
- **存储**：SQLite 每项目一个 `project.db`，本地 `~/.h2ometa/projects/{id}/`，远端 `/h2ometa/projects/{id}/`

## SQLite Schema

```sql
CREATE TABLE samples (sample_id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT, metadata TEXT);
CREATE TABLE executions (
    execution_id TEXT PRIMARY KEY, sample_id TEXT, tool_id TEXT NOT NULL,
    parameters TEXT NOT NULL, status TEXT NOT NULL, triggered_by TEXT,
    created_at REAL NOT NULL, completed_at REAL, error TEXT,
    retry_count INTEGER DEFAULT 0, retry_of TEXT, remote_job_id TEXT
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
新架构远端路径：`/h2ometa/projects/{project_id}/`

## 测试

pytest，`bio_ui` conda 环境（Python 3.11），测试文件在 `tests/`，约 398 个测试用例

---

## 待完成功能（每次开发前先 Review）

### P1 — 阻断（功能跑通但结果看不到）
- [ ] `chart_widget.py` 未集成到 `analysis_page.py`（流水线完成后无图表）
- [ ] `analysis_page` 缺结果文件下载逻辑（fastp JSON / kreport 在远端，需 `ssh.download()` 后再传给 `ResultsPanel`）
- [ ] `ChartWidget` / `ResultsPanel` 未加入 `ui/widgets/__init__.py`

### P2 — 核心功能缺失
- [ ] `assembly_page` 步骤 2-4（binning / 质量评估 / 注释）有 UI 无执行逻辑，是空壳按钮
- [ ] 结果浏览页（`results_page.py`）完全未建
- [ ] 数据库管理页（`database_page.py`）完全未建
- [ ] AMR 分析页（`amr_page.py`）完全未建（污水研究核心，见 PRODUCT.md）
- [ ] DAG 视图（`dag_widget.py`）完全未建
- [ ] `ResultSyncManager` 未建（任务完成后自动下载 `tier=result` 文件到本地）
- [ ] 缺少插件 YAML：`bracken`、`krona`、`rgi`、`genomad`、`integron_finder`、`isescan`、`quast`、`amrfinderplus`

### P3 — 体验完善
- [ ] `ui/widgets/__init__.py` 的 `__all__` 缺少 `ExportDialog`、`ChartWidget`、`ResultsPanel`

---

## 开发规则（从历史错误中总结）

1. **Core 和 UI 必须同步完成** — 写完 Core 模块后立即接入 UI，以用户能看到为验收标准，不留"后台完成 UI 未接"的中间状态
2. **新建 widget 立即更新 `__init__.py`** — 当次提交内完成
3. **不留死控件** — 暂不实现的功能必须 `setEnabled(False)` + 提示文字，不留无逻辑的按钮
4. **完成后更新待完成列表** — `[x]` 标注已完成，新发现问题追加 `[ ]`
