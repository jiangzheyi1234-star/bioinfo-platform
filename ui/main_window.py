"""主窗口：6页导航 + 项目切换 + ServiceLocator 接线。"""

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

from core.project_manager import ProjectManager
from core.service_locator import ServiceLocator
from core.ssh_service import SSHService
from core.storage_manager import StorageManager
from ui.pages import AnalysisPage, DetectionPage, SettingsPage
from ui.pages.assembly_page import AssemblyPage
from ui.pages.home_page import HomePage
from ui.pages.project_page import ProjectPage
from ui.widgets import styles
from ui.widgets.environment_status_bar import EnvironmentStatusBar

logger = logging.getLogger(__name__)

class _CurrentPageStackedWidget(QStackedWidget):
    """Only use the current page minimum/size hint to avoid window shrink lock."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _idx: self.updateGeometry())

    def minimumSizeHint(self):
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return super().minimumSizeHint()

    def sizeHint(self):
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return super().sizeHint()


class MainWindow(QMainWindow):
    def __init__(self, project_manager: Optional[ProjectManager] = None):
        super().__init__()
        self.setWindowTitle("H2OMeta 宏基因组分析平台")
        self.resize(980, 680)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")

        self._pm = project_manager or ProjectManager()
        self._updating_combo = False
        self._ssh_service_wrapper: Optional[SSHService] = None

        self._locator = ServiceLocator(project_manager=self._pm)
        self._locator.initialize()

        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(300_000)
        self._disk_timer.timeout.connect(self._refresh_disk_usage)

        self.init_ui()
        self._refresh_project_combo()
        self._connect_service_signals()

    def init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        middle = QWidget()
        middle_layout = QHBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(200)
        sidebar_widget.setStyleSheet(
            f"background-color: {styles.COLOR_BG_CARD};"
            f"border-right: 1px solid {styles.COLOR_BORDER};"
        )
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        switcher_container = QWidget()
        switcher_container.setStyleSheet(
            f"background-color: {styles.COLOR_BG_CARD}; border: none;"
        )
        switcher_layout = QVBoxLayout(switcher_container)
        switcher_layout.setContentsMargins(12, 12, 12, 8)
        switcher_layout.setSpacing(4)

        switcher_label = QLabel("当前项目")
        switcher_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT};"
            f"background: {styles.COLOR_BG_BLANK};"
        )
        switcher_layout.addWidget(switcher_label)

        self.project_combo = QComboBox()
        self.project_combo.setPlaceholderText("选择项目...")
        self.project_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        self.project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        switcher_layout.addWidget(self.project_combo)

        sidebar_layout.addWidget(switcher_container)

        self.sidebar = QListWidget()
        self.sidebar.setStyleSheet(styles.SIDEBAR_NAV_ITEM)
        sidebar_layout.addWidget(self.sidebar)

        middle_layout.addWidget(sidebar_widget)

        self.content = _CurrentPageStackedWidget()

        self.project_page = ProjectPage(
            self._pm,
            main_window=self,
            service_locator=self._locator,
        )
        self.project_page.project_switched.connect(self._on_project_switched)
        self.content.addWidget(self.project_page)

        self.home_page = HomePage(main_window=self)
        self.content.addWidget(self.home_page)

        self.detection_page = DetectionPage(main_window=self)
        self.content.addWidget(self.detection_page)

        self.settings_page = SettingsPage()
        self.settings_page.active_client_changed.connect(self._on_settings_active_client_changed)
        self.content.addWidget(self.settings_page)

        self.analysis_page = AnalysisPage(main_window=self)
        self.content.addWidget(self.analysis_page)

        self.assembly_page = AssemblyPage(main_window=self)
        self.content.addWidget(self.assembly_page)

        self.sidebar.addItem(QListWidgetItem("项目管理"))
        self.sidebar.addItem(QListWidgetItem("项目首页"))
        self.sidebar.addItem(QListWidgetItem("病原检测"))
        self.sidebar.addItem(QListWidgetItem("系统设置"))
        self.sidebar.addItem(QListWidgetItem("分析工作台"))
        self.sidebar.addItem(QListWidgetItem("组装分析"))

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        middle_layout.addWidget(self.content)
        main_layout.addWidget(middle, stretch=1)

        self.status_bar = EnvironmentStatusBar()
        main_layout.addWidget(self.status_bar)

        self.sidebar.setCurrentRow(0)

        # 初始化一次 SSH 注入
        self._on_settings_active_client_changed(self.settings_page.get_active_client())

    def _on_settings_active_client_changed(self, client) -> None:
        """把 Settings 的 SSH 客户端统一注入 ServiceLocator。"""
        if client is None:
            self._ssh_service_wrapper = None
            self._locator.ssh_service = None  # type: ignore[assignment]
            self.status_bar.update_ssh_status(False)
            self._notify_pages_context_changed()
            return

        self._ssh_service_wrapper = SSHService(lambda c=client: c)
        self._ssh_service_wrapper.connection_status_changed.connect(self.status_bar.update_ssh_status)
        self._locator.ssh_service = self._ssh_service_wrapper
        self.status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()

    def _refresh_project_combo(self) -> None:
        self._updating_combo = True
        self.project_combo.clear()

        projects = self._pm.list_projects()
        current = self._pm.current_project
        selected_index = -1

        for project in projects:
            if project.status == "active":
                self.project_combo.addItem(project.name, project.project_id)
                if current and project.project_id == current.project_id:
                    selected_index = self.project_combo.count() - 1

        if selected_index >= 0:
            self.project_combo.setCurrentIndex(selected_index)

        self._updating_combo = False

    def _on_project_combo_changed(self, index: int) -> None:
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
        self._refresh_project_combo()

        current = self._pm.current_project
        self.status_bar.update_project(current.name if current else None)
        self._notify_pages_context_changed()

        logger.info("项目已切换: %s", project_id)


    def _notify_pages_context_changed(self) -> None:
        """Notify pages to refresh UI state when SSH/project context changes."""
        for page_name in ("home_page", "detection_page", "analysis_page", "assembly_page"):
            page = getattr(self, page_name, None)
            callback = getattr(page, "refresh_context", None)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    logger.exception("页面上下文刷新失败: %s", page_name)

    @property
    def service_locator(self) -> ServiceLocator:
        return self._locator

    def get_ssh_service(self):
        """兼容旧组件：返回原始 Paramiko client。"""
        if hasattr(self, "settings_page") and self.settings_page:
            return self.settings_page.get_active_client()
        return None

    def set_settings_locked(self, locked: bool, reason: str = "SSH 任务执行中，设置暂时锁定") -> None:
        if hasattr(self, "settings_page") and self.settings_page:
            self.settings_page.set_global_lock(locked, reason)

    def _refresh_disk_usage(self) -> None:
        ssh = self._locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            return

        try:
            mgr = StorageManager(ssh)
            usage = mgr.get_disk_usage("/h2ometa")
            self.status_bar.update_disk_usage(usage.used_gb, usage.total_gb, usage.percent)
        except Exception:
            pass

    def _connect_service_signals(self) -> None:
        queue = self._locator.job_queue
        queue.job_started.connect(self._update_queue_display)
        queue.queue_updated.connect(lambda _: self._update_queue_display())

        self._locator.ssh_changed.connect(
            lambda connected: self._disk_timer.start() if connected else self._disk_timer.stop()
        )

    def _update_queue_display(self, *_args) -> None:
        status = self._locator.job_queue.get_status()
        self.status_bar.update_queue_status(
            running=status.get("running", 0),
            pending=status.get("pending", 0),
        )

    def closeEvent(self, event) -> None:
        self._locator.shutdown()
        super().closeEvent(event)


