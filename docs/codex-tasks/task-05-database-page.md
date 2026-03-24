# Task 5: 新建数据库管理页面 + 侧边栏集成

## 目标
创建独立的数据库管理页面，并将其加入主窗口侧边栏导航。

## 新建文件
- `ui/pages/database_page.py`（~400 行）

## 修改文件
- `ui/main_window.py` — 侧边栏新增"数据库"入口
- `ui/pages/__init__.py` — 导出 DatabasePage
- `ui/widgets/__init__.py` — 导出新组件

## 依赖（需先完成）
- Task 3: `core/data/database_service.py`
- Task 4: `ui/widgets/database_management_components.py`

## database_page.py 设计

继承 `ui/page_base.py` 的 `BasePage`。

### 布局结构
```
┌──────────────────────────────────────────────────────┐
│  数据库管理                              [全部刷新]    │
│  数据库根目录: [________________/data/databases____] [保存] │
├──────────────────────────────────────────────────────┤
│  [物种分类]  [组装质控]  [功能注释]  [AMR]  [其他]      │
├──────────────────────────────────────────────────────┤
│  (QScrollArea 内的 DatabaseItemCard 列表)              │
└──────────────────────────────────────────────────────┘
```

### 核心结构
```python
from ui.page_base import BasePage
from core.data.database_service import DatabaseService, DatabaseStatus
from ui.widgets.database_management_components import (
    DatabaseItemCard, DatabaseInstallDialog,
    DatabaseStatusWorker, DatabaseInstallMonitor,
)

class DatabasePage(BasePage):
    def __init__(self):
        super().__init__("数据库管理")
        self._ssh_client = None
        self._database_service = DatabaseService()  # 加载 databases.yaml
        self._cards: dict[str, DatabaseItemCard] = {}  # db_id -> card
        self._init_ui()

    def _init_ui(self):
        # 1. 隐藏默认 title label
        self.label.hide()

        # 2. Header: 标题 + 全部刷新按钮
        # 3. db_root 输入行: QLineEdit + 保存按钮
        # 4. QTabWidget 按 category 分 tab
        #    每个 tab 内: QScrollArea > QWidget > QVBoxLayout > DatabaseItemCard 列表
        # 5. 从 DatabaseService.list_by_category() 获取数据，创建卡片

    def set_active_client(self, client):
        """SSH 连接变化时调用。client 为 paramiko.SSHClient 或 None。"""
        self._ssh_client = client
        if client:
            self._refresh_all_status()
        else:
            # 所有卡片状态设为 UNKNOWN
            pass

    def refresh_context(self):
        """项目/SSH 上下文变化时调用。"""
        if self._ssh_client:
            self._refresh_all_status()

    def _make_ssh_run_fn(self):
        """构造 SshRunFn 回调。参考 linux_settings_card.py 的同名方法。"""
        client = self._ssh_client
        def ssh_run(cmd, timeout=15):
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            return rc, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")
        return ssh_run

    def _refresh_all_status(self):
        """启动 DatabaseStatusWorker 批量检测。"""
        # 创建 worker + thread（moveToThread 模式）
        # worker.status_checked 信号连接到 _on_status_checked
        # worker.all_done 信号连接到清理 thread

    def _on_status_checked(self, db_id: str, result):
        """更新对应卡片状态。"""
        card = self._cards.get(db_id)
        if card:
            card.update_status(result)

    def _on_install_clicked(self, db_id: str):
        """打开安装对话框。"""
        info = self._database_service.get_info(db_id)
        db_root = self._get_db_root()
        commands = self._database_service.generate_install_commands(db_id, db_root)
        dialog = DatabaseInstallDialog(info, commands, parent=self)
        dialog.install_confirmed.connect(self._start_install)
        dialog.exec()

    def _start_install(self, db_id: str, mirror_index: int):
        """提交安装任务，启动 InstallMonitor。"""
        ssh_run_fn = self._make_ssh_run_fn()
        db_root = self._get_db_root()
        result = self._database_service.submit_install(ssh_run_fn, db_id, db_root, mirror_index=mirror_index)
        # 启动 DatabaseInstallMonitor 轮询进度
        # monitor.progress_updated → 更新卡片进度条
        # monitor.install_finished → 刷新状态

    def _on_path_override(self, db_id: str):
        """用户手动指定路径。弹出 QInputDialog 或 QLineEdit 对话框。"""
        # 保存到 config.databases.overrides[db_id]

    def _save_db_root(self):
        """保存 db_root 到 config.json。"""
        from config import get_config, save_config
        config = get_config()
        config["databases"]["db_root"] = self._db_root_edit.text().strip()
        save_config(config)

    def _get_db_root(self) -> str:
        return self._db_root_edit.text().strip()
```

### Tab 分类映射
```python
CATEGORY_LABELS = {
    "reads": "物种分类",
    "mag": "组装质控",
    "annotation": "功能注释",
    "amr": "AMR",
    "other": "其他",
}
```

## main_window.py 修改

### 1. Import
```python
from ui.pages.database_page import DatabasePage
```

### 2. 侧边栏导航项
在 `_NAV_ICONS` 列表中，在"病原检测"和"系统设置"之间插入"数据库"项。

需要一个数据库图标的 SVG path。可以用一个简单的圆柱体/存储图标，或者复用已有图标风格。

侧边栏顺序变为：
```
0: 项目首页
1: 病原检测
2: 数据库        ← 新增
3: 系统设置
4: 日志
```

### 3. 页面创建
在 `init_ui()` 中，在 detection_page 之后、settings_page 之前创建：
```python
self.database_page = DatabasePage()
self.content.addWidget(self.database_page)
```

注意：`self.content` 是 `QStackedWidget`，addWidget 的顺序必须与侧边栏 index 一致。

### 4. 导航处理
`_on_nav_row_changed()` 中的 index 映射需要调整。原来：
- 0=首页, 1=检测, 2=设置, 3=日志

改为：
- 0=首页, 1=检测, 2=数据库, 3=设置, 4=日志

如果有 `if row == 1: self._ensure_detection_page_loaded()` 这类硬编码 index 的逻辑，需要保持 row==1 不变（检测页还是 index 1）。

### 5. SSH client 传递
在 SSH 连接状态变化时，传递 client 给 database_page：
```python
# 在 _on_ssh_state_changed 或等效位置
self.database_page.set_active_client(client)
```

找到 `settings_page.active_client_changed` 信号的连接点，加上 database_page 的传递。

### 6. 上下文刷新
在 `_notify_pages_context_changed()` 中加入 `"database_page"`。

## __init__.py 更新

### ui/pages/__init__.py
```python
from .database_page import DatabasePage
# 加入 __all__
```

### ui/widgets/__init__.py
```python
from .database_management_components import DatabaseItemCard, DatabaseInstallDialog
# 加入 __all__
```

## 参考文件
- `ui/page_base.py` — BasePage 基类
- `ui/main_window.py` — 侧边栏定义（_NAV_ICONS, line ~146）、页面注册（line ~120-144）、导航处理（line ~283）
- `ui/pages/settings_page.py` — 同类页面参考（ScrollArea + 卡片布局）
- `ui/widgets/linux_settings_card.py` — `set_active_client()` + `_make_ssh_run_fn()` 模式
- `ui/widgets/styles.py` — PAGE_HEADER_TITLE, COLOR_BG_APP, SCROLL_BAR_ELEGANT 等

## 验证
```bash
# UI 冒烟测试
QT_QPA_PLATFORM=offscreen pytest tests/test_ui_smoke.py -v
```
- DatabasePage 实例化不崩溃
- 侧边栏显示 5 个导航项
- 点击"数据库"切换到正确页面
