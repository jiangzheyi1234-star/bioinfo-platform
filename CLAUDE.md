# H2OMeta — AI 开发指令

## 项目定位
宏基因组桌面分析平台：Windows 客户端 + SSH 远程执行
**三条分析路径**：Reads 分析 · MAG 重建 · AMR 分析
**不做**：16S / 云计算 / 多用户

---

## 架构约束

- **Core 层（core/）**：只允许 `PyQt6.QtCore`，禁止 QtWidgets/QtGui。6 个子包：execution/ · data/ · remote/ · pipeline/ · environment/ · plugins/，总线 `service_locator.py`
- **UI 层（ui/）**：新建 widget/page 必须同步更新 `__init__.py`。6 个页面。QWebEngineView 当前用于 `detection_page_web` 与 `linux_settings_card`，必须延迟导入
- **插件层（plugins/）**：`plugins/{category}/{tool_name}/tool.yaml`，必需字段：conda_env · install_cmd · command_template，30 个工具 / 12 个 category

**详细目录结构与模块清单**：见 `ARCHITECTURE.md`

---

## 关键决策（不可推翻）

1. SSH + Screen 远程执行 — 无服务端 agent，客户端断线不影响任务
2. 事件驱动任务等待 — JobDispatcher 后台线程 + JobMonitor fallback
3. 每工具独立 conda 环境 — 避免依赖冲突
4. YAML 声明式插件 — 新增工具只需添加 tool.yaml
5. 项目隔离存储 — 每项目独立 SQLite + 文件目录
6. 数据血缘追踪 — execution_io 表记录输入输出关系

---

## 数据模型（SQLite）

```sql
samples       (sample_id PK, name, source, metadata)
executions    (execution_id PK, sample_id, tool_id, status, parameters,
               retry_of, is_final_version, remote_job_id, ...)
data_items    (data_id PK, sample_id, file_path, data_type, tier, produced_by, ...)
execution_io  (execution_id, data_id, direction, PK(all three))
```

---

## 配置管理（config.py）

**严格禁止**：硬编码 IP/用户名/密码/路径
`get_config()` 从 `%APPDATA%\H2OMeta\config.json` 加载 · `save_config(config)` 持久化 · `default_settings_schema()` 仅首次启动用

---

## 待完成任务

**P1 — 阻断块**：ResultsPanel 接入 analysis_page · 远端结果文件下载（ssh.download）
**P2 — Phase 3**：database_page · results_page（图表+DAG） · amr_page · 历史执行选择器

---

## 开发规则（必须遵守）

1. **Core 和 UI 同步完成** — 验收标准：用户能在界面看到
2. **新建 widget 立即更新 `__init__.py`**
3. **不留死控件** — 未实现功能 `setEnabled(False)` + 提示
4. **完成后更新本文件待完成列表**
5. **响应式布局** — 禁止硬编码固定宽度
6. **测试临时文件用 fixture** — 统一用 `conftest.py` 的 `tmp_db` / `tmp_dir`
7. **禁止硬编码服务器信息** — 所有配置通过 config.py 读写
8. **测试禁止 module-level 创建 QApp** — 统一用 `conftest.py` 的 `_ensure_qapp`（session-scope），Qt 只允许一个 Application 实例
9. **测试禁止实例化 QWebEngineView** — `patch("ui.main_window.DetectionPage", FakeWidget)` 替换
10. **分层禁令** — ui/ 只负责界面渲染、信号绑定、状态展示。SQL/SSH/数据解析/文件IO/配置拼装一律放 core/。跨页面协作放 ui/controllers/ 或 MainWindow 公开接口。plugins/ 只放 YAML 静态声明
11. **体积约束** — UI 页面 ≤ 400 行，复杂卡片 ≤ 500 行，超 600 行必须先拆分再加功能。函数超 40 行评估拆分
12. **新增代码放置** — 弹窗/子卡片 → `ui/widgets/*_components.py`；页面编排 → `ui/controllers/*_controller.py`；查询/执行逻辑 → `core/*/*_service.py`；通用函数 → `core/utils.py`；Worker 纯逻辑放 core/，UI 只做信号壳

---

## 快速参考

```
启动应用：  python -m ui.main
全量测试：  QT_QPA_PLATFORM=offscreen pytest -p no:cacheprovider tests -q
单文件测试：pytest tests/test_xxx.py -v
Core 测试： pytest tests -m "not ui" -q
UI 测试：   pytest tests/test_ui_smoke.py -v
```

**环境**：conda `bio_ui` · Python 3.11+ · PyQt6 · paramiko · Jinja2 · matplotlib
