# Task 4: 新建 UI 组件 — 数据库卡片和安装对话框

## 目标
创建数据库管理页面所需的 UI 子组件：状态卡片、安装对话框、后台 Worker。

## 新建文件
`ui/widgets/database_management_components.py`（~450 行）

## 依赖（需先完成）
- Task 3: `core/data/database_service.py` 中的 `DatabaseInfo`, `DatabaseStatus`, `DatabaseCheckResult`, `DatabaseService`

## 架构约束
- UI 层文件，可以使用 PyQt6 全部模块
- 不包含 SQL/SSH/数据解析逻辑，这些在 core 层
- 复杂卡片 ≤ 500 行
- 参考 `ui/widgets/linux_settings_components.py` 中 `EnvInstallDialog` 和 `ToolEnvBridge` 的实现模式

## 组件清单

### 1. DatabaseItemCard(QFrame) — 单个数据库状态卡片

每个数据库一张卡片，有三种状态呈现：

**就绪状态（绿色）**：
- 左侧 3px 绿色边框
- 绿色圆点 + 数据库名称 + 大小（右对齐）
- 第二行：工具名 · 路径
- 按钮：[重新安装]

**未安装状态（红/灰色）**：
- 左侧 3px 红色边框
- 红色圆点 + 数据库名称 + 大小
- 第二行：工具名 · "路径: 未设置"
- 按钮：[下载安装] [选择已有路径]

**安装中状态（蓝色）**：
- 左侧 3px 蓝色边框
- 蓝色圆点 + 数据库名称 + 大小
- QProgressBar + 速度 + ETA 标签
- 按钮：[取消]

```python
class DatabaseItemCard(QFrame):
    install_requested = pyqtSignal(str)        # db_id
    path_override_requested = pyqtSignal(str)  # db_id
    cancel_requested = pyqtSignal(str)         # db_id

    def __init__(self, db_info: DatabaseInfo, parent=None): ...
    def update_status(self, result: DatabaseCheckResult) -> None: ...
    def update_progress(self, percent: int, speed: str = "", eta: str = "") -> None: ...
    def set_installing(self, installing: bool) -> None: ...
```

布局参考（QVBoxLayout 内嵌 QHBoxLayout）：
```
┌─[3px colored border]──────────────────────────────┐
│  ● Kraken2 Standard Database              50 GB   │
│  工具: kraken2 · 路径: /data/databases/kraken2     │
│                              [重新安装]             │
└───────────────────────────────────────────────────┘
```

样式使用 `ui/widgets/styles.py` 中的常量。卡片背景白色，圆角 8px，hover 时轻微阴影。

### 2. DatabaseInstallDialog(QDialog) — 安装确认 + 实时日志

两阶段对话框：

**阶段一：确认**
- 数据库名称、描述、大小
- 镜像选择下拉框（QComboBox，如果有多个 mirror）
- 命令预览（QPlainTextEdit，只读，monospace 字体）
- [确认安装] [取消] 按钮

**阶段二：安装中**
- 隐藏确认按钮，显示进度条
- QProgressBar（0-100%）
- QPlainTextEdit 显示实时日志（每 2s 刷新）
- 速度 + ETA 标签
- [取消] 按钮
- 完成后显示结果（成功/失败）+ [关闭] 按钮

```python
class DatabaseInstallDialog(QDialog):
    install_confirmed = pyqtSignal(str, int)  # db_id, mirror_index
    install_cancelled = pyqtSignal(str)       # db_id

    def __init__(self, db_info: DatabaseInfo, commands: list[str], parent=None): ...
    def start_monitoring(self) -> None: ...
    def update_log(self, text: str) -> None: ...
    def update_progress(self, percent: int, speed: str, eta: str) -> None: ...
    def show_result(self, success: bool, message: str) -> None: ...
```

对话框大小：约 600x500，可调整。

### 3. DatabaseStatusWorker(QObject) — 后台批量检测

```python
class DatabaseStatusWorker(QObject):
    status_checked = pyqtSignal(str, object)  # db_id, DatabaseCheckResult
    all_done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, database_service: DatabaseService, ssh_run_fn, db_root: str): ...
    def run(self) -> None:
        """遍历所有非 builtin 数据库，逐个 SSH 检测状态，发射信号。"""
```

使用 `moveToThread` 模式（参考 `linux_settings_components.py` 中的 worker 模式）。

### 4. DatabaseInstallMonitor(QObject) — 后台轮询安装进度

```python
class DatabaseInstallMonitor(QObject):
    progress_updated = pyqtSignal(str, int, str, str)  # db_id, percent, speed, eta
    log_updated = pyqtSignal(str, str)                 # db_id, log_text
    install_finished = pyqtSignal(str, bool, str)      # db_id, success, message

    def __init__(self, database_service: DatabaseService, ssh_run_fn,
                 db_id: str, task_dir: str): ...
    def run(self) -> None:
        """每 2s 轮询 status.txt + tail task.log，解析进度，直到完成。"""
```

轮询逻辑：
1. `check_install_status()` 读 status.txt
2. 如果 RUNNING：`read_install_log()` → `parse_progress()` → 发射 progress_updated + log_updated
3. 如果 DONE：`verify_integrity()` → 发射 install_finished(success=True)
4. 如果 FAILED：发射 install_finished(success=False)
5. sleep 2s，重复

## 参考文件
- `ui/widgets/linux_settings_components.py` — `EnvInstallDialog`（对话框模式）、`ToolEnvBridge`（worker 模式）
- `ui/widgets/styles.py` — 样式常量（CARD_FRAME, BUTTON_SUCCESS, BUTTON_LINK, INPUT_LINEEDIT 等）
- `core/data/database_service.py` — Task 3 创建的服务

## 验证
- 所有组件可以 import 不报错
- DatabaseItemCard 三种状态切换不崩溃
- DatabaseInstallDialog 显示命令预览正确
