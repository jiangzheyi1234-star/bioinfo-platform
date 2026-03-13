# H2OMeta — AI 开发指令

## 项目定位
宏基因组桌面分析平台：Windows 客户端 + SSH 远程执行
**三条分析路径**：Reads 分析 · MAG 重建 · AMR 分析
**不做**：16S / 云计算 / 多用户

---

## 架构约束

### Core 层（core/）
- **严格约束**：只允许 `PyQt6.QtCore`（信号/线程），禁止 QtWidgets/QtGui
- **职责**：业务逻辑、远程执行、数据管理、流程编排
- **关键模块**：
  - 执行链：tool_engine → command_builder → job_dispatcher（SSH+screen+事件驱动）→ job_monitor（fallback）
  - 流程：pipeline_runner（线性）· pipeline_reconstructor（DAG 重建）
  - 数据：data_registry（血缘追踪）· storage_manager · execution_cleaner
  - 插件：plugin_registry（YAML 三层懒加载）· env_detector · env_installer
  - 总线：service_locator（串联所有模块）

### UI 层（ui/）
- **约束**：新建 widget/page 必须同步更新 `__init__.py`
- **6 个页面**：home_page · project_page · analysis_page · assembly_page · detection_page_web · settings_page
- **QWebEngineView**：仅 detection_page_web 使用，必须延迟导入（QApplication 创建后）

### 插件层（plugins/）
- **结构**：`plugins/{category}/{tool_name}/tool.yaml`
- **必需字段**：conda_env · install_cmd · command_template
- **可选字段**：databases（依赖的数据库列表）
- **已有 30 个工具**，分 11 个 category

---

## 关键决策（不可推翻）

1. **SSH + Screen 远程执行** — 无服务端 agent，客户端断线不影响任务
2. **事件驱动任务等待** — JobDispatcher 后台线程监听 screen 会话，JobMonitor 作为 fallback
3. **每工具独立 conda 环境** — 避免依赖冲突
4. **YAML 声明式插件** — 新增工具只需添加 tool.yaml
5. **项目隔离存储** — 每个项目独立 SQLite + 文件目录
6. **数据血缘追踪** — execution_io 表记录输入输出关系

---

## 数据模型（SQLite）

```sql
samples       (sample_id PK, name, source, metadata)
executions    (execution_id PK, sample_id, tool_id, status, parameters,
               retry_of, is_final_version, remote_job_id, ...)
data_items    (data_id PK, sample_id, file_path, data_type, tier, produced_by, ...)
execution_io  (execution_id, data_id, direction, PK(all three))
```

**关键字段**：
- `executions.is_final_version` — 同工具多次执行，标记最终版本
- `executions.retry_of` — 重试链追踪
- `data_items.tier` — raw/intermediate/result
- `execution_io.direction` — input/output

---

## 配置管理（config.py）

**严格禁止**：硬编码 IP/用户名/密码/路径
**读取配置**：`get_config()` — 自动从 `%APPDATA%\H2OMeta\config.json` 加载
**保存配置**：`save_config(config)` — 持久化到本地
**默认模板**：`default_settings_schema()` — 仅首次启动或缺失字段时使用

---

## 项目进度

**Phase 2 ✅ 完成**
- ✅ 6 个 UI 页面：home_page · project_page · analysis_page · assembly_page · detection_page_web · settings_page
- ✅ 30 个 tool.yaml（11 个 category）
- ✅ conda 环境管理：env_detector · env_installer · LinuxSettingsCard 升级
- ✅ 完整执行链：ToolEngine → JobQueue → JobDispatcher（事件驱动）→ DataRegistry

**Phase 3 进行中** — 结果展示 + 页面扩展

---

## 待完成任务

### P1 — 阻断块（结果展示）
- [ ] ResultsPanel 接入 analysis_page._on_pipeline_completed()
- [ ] 远端结果文件下载（ssh.download）

### P2 — 核心功能（Phase 3）
- [ ] database_page（数据库下载管理）
- [ ] results_page（matplotlib 图表 + 数据表格 + DAG 可视化）
- [ ] amr_page（AMR 分析路径专用页面）
- [ ] 历史执行选择器（切换重试和最终版本）

---

## 开发规则（必须遵守）

1. **Core 和 UI 同步完成** — 验收标准：用户能在界面看到
2. **新建 widget 立即更新 `__init__.py`**
3. **不留死控件** — 未实现功能 `setEnabled(False)` + 提示
4. **完成后更新本文件待完成列表**
5. **响应式布局** — 禁止硬编码固定宽度
6. **测试临时文件用 fixture** — 统一用 `conftest.py` 的 `tmp_db` / `tmp_dir`
7. **禁止硬编码服务器信息** — 所有配置通过 config.py 读写
8. **测试禁止 module-level 创建 QApplication/QCoreApplication** — 统一用 `conftest.py` 的 `_ensure_qapp`（session-scope QApplication）。Qt 同一进程只允许一个 Application 实例，混用 QCoreApplication 和 QApplication 会导致 `0xC0000409` 原生崩溃
9. **测试中禁止实例化 QWebEngineView** — UI 测试需 `patch("ui.main_window.DetectionPage", FakeWidget)` 替换，避免 Chromium 子进程在无头环境崩溃

---

## 快速参考

**本地环境**：conda 环境 `bio_ui`（已配置完整依赖）
**启动应用**：`python -m ui.main`
**运行全量测试**：`QT_QPA_PLATFORM=offscreen pytest -p no:cacheprovider tests -q`
**单文件测试**：`pytest tests/test_xxx.py -v`
**仅 Core 测试**：`pytest tests -m "not ui" -q`（跳过 UI smoke，速度更快）
**仅 UI 测试**：`pytest tests/test_ui_smoke.py -v`
**依赖**：Python 3.11+ · PyQt6 · paramiko · Jinja2 · matplotlib
**详细架构**：见 `ARCHITECTURE.md`
