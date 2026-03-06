"""主窗口 — 侧边栏导航 + 项目切换器 + 环境状态栏 + ServiceLocator 集成

Phase 2 变更:
  - 集成 ServiceLocator 作为核心服务总线
  - 连接 SSH/项目/任务状态到环境状态栏
  - 将 ServiceLocator 传入各页面构造函数
"""
import logging
from typing import Optional

from PyQt6.QtCore import QTimer
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
from core.service_locator import ServiceLocator
from core.storage_manager import StorageManager
from ui.pages import AnalysisPage, DetectionPage, SettingsPage
from ui.pages.assembly_page import AssemblyPage
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

        # 创建 ServiceLocator
        self._locator = ServiceLocator(project_manager=self._pm)
        self._locator.initialize()

        # 磁盘监控定时器（每 5 分钟刷新一次）
        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(300_000)
        self._disk_timer.timeout.connect(self._refresh_disk_usage)

        self.init_ui()
        self._refresh_project_combo()
        self._connect_service_signals()

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
        self.project_page = ProjectPage(
            self._pm, main_window=self, service_locator=self._locator
        )
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

        # 读长分析流水线页
        self.analysis_page = AnalysisPage(main_window=self)
        self.content.addWidget(self.analysis_page)  # Index 4

        # 组装分析流水线页
        self.assembly_page = AssemblyPage(main_window=self)
        self.content.addWidget(self.assembly_page)  # Index 5

        # 导航项与堆栈索引严格对应
        self.sidebar.addItem(QListWidgetItem("项目管理"))    # idx 0
        self.sidebar.addItem(QListWidgetItem("项目首页"))    # idx 1
        self.sidebar.addItem(QListWidgetItem("病原体检测"))  # idx 2
        self.sidebar.addItem(QListWidgetItem("系统设置"))    # idx 3
        self.sidebar.addItem(QListWidgetItem("读长分析"))    # idx 4
        self.sidebar.addItem(QListWidgetItem("组装分析"))    # idx 5

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

    @property
    def service_locator(self) -> ServiceLocator:
        """获取 ServiceLocator 实例，供页面访问"""
        return self._locator

    def get_ssh_service(self):
        """获取 SSH 服务实例，优先从设置页面获取"""
        if hasattr(self, 'settings_page') and self.settings_page:
            return self.settings_page.get_active_client()
        return None

    def set_settings_locked(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        if hasattr(self, 'settings_page') and self.settings_page:
            self.settings_page.set_global_lock(locked, reason)

    # ── ServiceLocator 信号连接 ────────────────────────────────

    def _refresh_disk_usage(self) -> None:
        """通过 StorageManager 查询远端磁盘用量并更新状态栏"""
        ssh = self._locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            return
        try:
            mgr = StorageManager(ssh)
            usage = mgr.get_disk_usage("/h2ometa")
            self.status_bar.update_disk_usage(
                usage.used_gb, usage.total_gb, usage.percent
            )
        except Exception:
            pass

    def _connect_service_signals(self) -> None:
        """连接 ServiceLocator 信号到状态栏"""
        # SSH 连接状态 → 状态栏
        ssh = self._locator.ssh_service
        if ssh and hasattr(ssh, 'connection_status_changed'):
            ssh.connection_status_changed.connect(
                lambda connected: self.status_bar.update_ssh_status(connected)
            )

        # 任务队列状态 → 状态栏
        queue = self._locator.job_queue
        queue.job_started.connect(self._update_queue_display)
        queue.queue_updated.connect(lambda _: self._update_queue_display())

        # SSH 连接后启动磁盘监控定时器
        self._locator.ssh_changed.connect(
            lambda connected: self._disk_timer.start() if connected else self._disk_timer.stop()
        )

        # 项目切换 → ServiceLocator 自动重建 DataRegistry（已在内部处理）

    def _update_queue_display(self, *_args) -> None:
        """刷新状态栏任务队列显示"""
        status = self._locator.job_queue.get_status()
        self.status_bar.update_queue_status(
            running=status.get("running", 0),
            pending=status.get("pending", 0),
        )

    def closeEvent(self, event) -> None:
        """窗口关闭时清理资源"""
        self._locator.shutdown()
        super().closeEvent(event)
