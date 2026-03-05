"""主窗口 — 侧边栏导航 + 项目切换器 + 环境状态栏

在原有导航基础上添加项目管理页和项目切换器，
底部添加环境状态栏显示连接和任务状态。
"""
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.project_manager import ProjectInfo, ProjectManager
from ui.pages import DetectionPage, SettingsPage
from ui.pages.home_page import HomePage
from ui.pages.project_page import ProjectPage
from ui.widgets import styles
from ui.widgets.environment_status_bar import EnvironmentStatusBar

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, project_manager: Optional[ProjectManager] = None):
        super().__init__()
        self.setWindowTitle("H2OMeta 宏基因组平台")
        self.resize(1100, 750)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")

        self._pm = project_manager or ProjectManager()
        self._updating_combo = False  # 防止信号循环
        self.init_ui()
        self._refresh_project_combo()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 中间区域：侧边栏 + 内容
        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        # ── 侧边栏 ────────────────────────────────────────────
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(200)
        sidebar_widget.setStyleSheet(
            f"background-color: {styles.COLOR_BG_CARD}; "
            f"border-right: 1px solid {styles.COLOR_BORDER};"
        )
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # 项目切换器
        switcher_container = QWidget()
        switcher_container.setStyleSheet(
            f"background-color: {styles.COLOR_BG_CARD}; border: none;"
        )
        switcher_layout = QVBoxLayout(switcher_container)
        switcher_layout.setContentsMargins(12, 12, 12, 8)
        switcher_layout.setSpacing(4)

        switcher_label = QLabel("当前项目")
        switcher_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        switcher_layout.addWidget(switcher_label)

        self.project_combo = QComboBox()
        self.project_combo.setPlaceholderText("选择项目...")
        self.project_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        self.project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        switcher_layout.addWidget(self.project_combo)

        sidebar_layout.addWidget(switcher_container)

        # 导航列表
        self.sidebar = QListWidget()
        self.sidebar.setStyleSheet(styles.SIDEBAR_NAV_ITEM)
        sidebar_layout.addWidget(self.sidebar)

        middle_layout.addWidget(sidebar_widget)

        # ── 内容区域 ────────────────────────────────────────────
        self.content = QStackedWidget()

        # 项目管理页
        self.project_page = ProjectPage(self._pm, main_window=self)
        self.project_page.project_switched.connect(self._on_project_switched)
        self.content.addWidget(self.project_page)  # Index 0

        # 首页
        self.home_page = HomePage(main_window=self)
        self.content.addWidget(self.home_page)  # Index 1

        # 病原体检测页
        self.detection_page = DetectionPage(main_window=self)
        self.content.addWidget(self.detection_page)  # Index 2

        # 设置页
        self.settings_page = SettingsPage()
        self.content.addWidget(self.settings_page)  # Index 3

        # 导航项与堆栈索引严格对应
        self.sidebar.addItem(QListWidgetItem("项目管理"))    # idx 0
        self.sidebar.addItem(QListWidgetItem("项目首页"))    # idx 1
        self.sidebar.addItem(QListWidgetItem("病原体检测"))  # idx 2
        self.sidebar.addItem(QListWidgetItem("系统设置"))    # idx 3

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        middle_layout.addWidget(self.content)

        main_layout.addWidget(middle, stretch=1)

        # ── 底部状态栏 ────────────────────────────────────────────
        self.status_bar = EnvironmentStatusBar()
        main_layout.addWidget(self.status_bar)

        # 默认选中项目管理页
        self.sidebar.setCurrentRow(0)

    # ── 项目切换器 ────────────────────────────────────────────

    def _refresh_project_combo(self) -> None:
        """刷新项目下拉列表"""
        self._updating_combo = True
        self.project_combo.clear()

        projects = self._pm.list_projects()
        current = self._pm.current_project
        selected_index = -1

        for i, project in enumerate(projects):
            if project.status == "active":
                self.project_combo.addItem(project.name, project.project_id)
                if current and project.project_id == current.project_id:
                    selected_index = self.project_combo.count() - 1

        if selected_index >= 0:
            self.project_combo.setCurrentIndex(selected_index)

        self._updating_combo = False

    def _on_project_combo_changed(self, index: int) -> None:
        """项目切换下拉变化"""
        if self._updating_combo or index < 0:
            return

        project_id = self.project_combo.currentData()
        if project_id:
            try:
                self._pm.open_project(project_id)
                self._on_project_switched(project_id)
            except Exception as e:
                logger.error("切换项目失败: %s", e)

    def _on_project_switched(self, project_id: str) -> None:
        """项目切换后的统一处理"""
        self._refresh_project_combo()

        # 更新状态栏
        current = self._pm.current_project
        if current:
            self.status_bar.update_project(current.name)
        else:
            self.status_bar.update_project(None)

        logger.info("当前项目已切换: %s", project_id)

    # ── 对外 API（保持兼容） ────────────────────────────────────

    def get_ssh_service(self):
        """获取 SSH 服务实例，优先从设置页面获取"""
        if hasattr(self, 'settings_page') and self.settings_page:
            return self.settings_page.get_active_client()
        return None

    def set_settings_locked(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        if hasattr(self, 'settings_page') and self.settings_page:
            self.settings_page.set_global_lock(locked, reason)
