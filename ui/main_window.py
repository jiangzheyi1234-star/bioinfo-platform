"""主窗口：6页导航 + 项目切换 + ServiceLocator 接线。"""

import logging
from typing import Optional

from PyQt6.QtCore import QEvent, QSize, QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.data.project_manager import ProjectManager
from core.execution.execution_reconcile_service import ExecutionReconcileService
from core.service_locator import ServiceLocator
from core.remote.ssh_service import SSHService
from ui.pages import SettingsPage
from ui.pages.home_page import HomePage
from ui.pages.log_page import LogPage
from ui.pages.detection_page_web import DetectionPageWeb as DetectionPage
from ui.controllers.main_window_disk_monitor import MainWindowDiskMonitor
from ui.controllers.main_window_log_controller import MainWindowLogController
from ui.controllers.main_window_project_controller import MainWindowProjectController
from ui.controllers.main_window_reconcile_controller import MainWindowReconcileController
from ui.controllers.main_window_ssh_controller import MainWindowSSHController
from ui.widgets import styles
from ui.widgets.environment_status_bar import EnvironmentStatusBar
from ui.widgets.project_selector import ProjectSelectorButton

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
        self._ssh_service_wrapper: Optional[SSHService] = None

        self._locator = ServiceLocator(project_manager=self._pm)
        self._services_initialized = False
        self._disk_monitor: Optional[MainWindowDiskMonitor] = None
        self._log_controller: Optional[MainWindowLogController] = None
        self._project_controller: Optional[MainWindowProjectController] = None
        self._reconcile_controller: Optional[MainWindowReconcileController] = None
        self._ssh_controller: Optional[MainWindowSSHController] = None

        self._prev_activated = True

        self.init_ui()
        self._initialize_controllers()
        self._connect_service_signals()
        self._on_settings_active_client_changed(self.settings_page.get_active_client())
        QTimer.singleShot(0, self._initialize_services_deferred)
        QTimer.singleShot(0, self._initialize_log_context_deferred)

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
            f"background-color: {styles.COLOR_BG_SIDEBAR};"
            f"border-right: 1px solid {styles.COLOR_BORDER};"
        )
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # -- 导航菜单 --
        self.sidebar = QListWidget()
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sidebar.setStyleSheet(styles.SIDEBAR_NAV_ITEM)
        sidebar_layout.addWidget(self.sidebar, stretch=1)

        # -- 底部项目选择器 --
        self._project_selector_btn = ProjectSelectorButton()
        self._project_selector_btn.clicked.connect(self._show_project_menu)
        sidebar_layout.addWidget(self._project_selector_btn)

        middle_layout.addWidget(sidebar_widget)

        self.content = _CurrentPageStackedWidget()

        self.home_page = HomePage(main_window=self)
        self.content.addWidget(self.home_page)

        self._detection_loaded = False
        self._detection_placeholder = QWidget()
        self._detection_placeholder.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self.detection_page = self._detection_placeholder
        self.content.addWidget(self.detection_page)

        self.settings_page = SettingsPage()
        self.settings_page.active_client_changed.connect(self._on_settings_active_client_changed)
        self.content.addWidget(self.settings_page)

        # 将 PluginRegistry 注入 LinuxSettingsCard，支持动态工具环境检测
        try:
            pr = self._locator.plugin_registry
            if pr and hasattr(self.settings_page, "linux_card"):
                self.settings_page.linux_card.set_plugin_registry(pr)
        except Exception:
            logger.exception("注入 PluginRegistry 到 LinuxSettingsCard 失败")

        self.log_page = LogPage(main_window=self)
        self.content.addWidget(self.log_page)

        _NAV_ICONS = [
            # (svg_path_d, label) — 简洁线条图标
            ("M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2v10a1 1 0 01-1 1h-3m-4 0v-6a1 1 0 011-1h2a1 1 0 011 1v6m-6 0h6",
             "项目首页"),
            ("M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
             "病原检测"),
            ("M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066zM15 12a3 3 0 11-6 0 3 3 0 016 0z",
             "系统设置"),
            ("M4 6h16M4 10h16M4 14h16M4 18h16",
             "日志"),
        ]
        for svg_d, label in _NAV_ICONS:
            icon = self._make_nav_icon(svg_d)
            item = QListWidgetItem(icon, f"  {label}")
            self.sidebar.addItem(item)

        self.sidebar.setIconSize(QSize(20, 20))

        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

        self.sidebar.currentRowChanged.connect(self._on_nav_row_changed)
        middle_layout.addWidget(self.content)
        main_layout.addWidget(middle, stretch=1)

        self.status_bar = EnvironmentStatusBar()
        main_layout.addWidget(self.status_bar)
        self.log_page.log_status_changed.connect(self.status_bar.update_log_status)
        self.status_bar.update_log_status("日志: 就绪")

        self.sidebar.setCurrentRow(0)

        self._update_project_selector()

    def _initialize_controllers(self) -> None:
        self._disk_monitor = MainWindowDiskMonitor(
            parent=self,
            status_bar=self.status_bar,
            locator=self._locator,
            logger=logger,
        )
        self._log_controller = MainWindowLogController(
            pm=self._pm,
            locator=self._locator,
            log_page=self.log_page,
        )
        self._reconcile_controller = MainWindowReconcileController(
            pm=self._pm,
            locator=self._locator,
            parent=self,
            is_services_initialized=lambda: self._services_initialized,
            logger=logger,
        )
        self._project_controller = MainWindowProjectController(
            pm=self._pm,
            project_selector_btn=self._project_selector_btn,
            status_bar=self.status_bar,
            log_page=self.log_page,
            log_controller=self._log_controller,
            schedule_reconcile_fn=self._schedule_reconcile_running_tasks,
            notify_context_fn=self._notify_pages_context_changed,
            logger=logger,
            parent_widget=self,
        )
        self._ssh_controller = MainWindowSSHController(
            locator=self._locator,
            settings_page=self.settings_page,
            status_bar=self.status_bar,
            on_ssh_status_changed=self._on_ssh_status_changed,
            on_ssh_changed_for_disk=self._on_ssh_changed_for_disk,
            notify_pages_context_changed=self._notify_pages_context_changed,
        )

    @staticmethod
    def _make_nav_icon(svg_path_d: str) -> QIcon:
        """根据 SVG path data 生成单色图标。"""
        svg_xml = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="#64748B" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{svg_path_d}"/></svg>'
        )
        from PyQt6.QtSvg import QSvgRenderer
        from PyQt6.QtCore import QByteArray
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))
        renderer = QSvgRenderer(QByteArray(svg_xml.encode()))
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)


    def _initialize_services_deferred(self) -> None:
        if self._services_initialized:
            return
        try:
            self._locator.initialize()
            self._services_initialized = True
            self._apply_plugin_registry_to_settings()
        except Exception:
            logger.exception("ServiceLocator deferred initialization failed")

    def _initialize_log_context_deferred(self) -> None:
        if self._pm.current_project:
            pid = self._pm.current_project.project_id
            self.log_page.set_project_context(pid)
            if self._log_controller is not None:
                self._log_controller.load_log_history_for_project(pid, logger)

    def _apply_plugin_registry_to_settings(self) -> None:
        try:
            pr = self._locator.plugin_registry
            if pr and hasattr(self.settings_page, "linux_card"):
                self.settings_page.linux_card.set_plugin_registry(pr)
        except Exception:
            logger.exception("Injecting PluginRegistry into LinuxSettingsCard failed")

    def _ensure_detection_page_loaded(self) -> None:
        if self._detection_loaded:
            return
        try:
            page = DetectionPage(main_window=self)
            idx = self.content.indexOf(self._detection_placeholder)
            if idx >= 0:
                self.content.removeWidget(self._detection_placeholder)
                self._detection_placeholder.deleteLater()
                self.content.insertWidget(idx, page)
            self.detection_page = page
            self._detection_loaded = True
            callback = getattr(self.detection_page, "refresh_context", None)
            if callable(callback):
                callback()
        except Exception:
            logger.exception("Lazy-loading detection page failed")

    def _on_nav_row_changed(self, row: int) -> None:
        if row == 1:
            self._ensure_detection_page_loaded()
        self.content.setCurrentIndex(row)

    def _on_settings_active_client_changed(self, client) -> None:
        """把 Settings 的 SSH 客户端统一注入 ServiceLocator。"""
        if self._ssh_controller is None:
            return
        self._ssh_service_wrapper = self._ssh_controller.apply_active_client(client)

    def _show_project_menu(self) -> None:
        if self._project_controller is not None:
            self._project_controller.show_project_menu()

    def _update_project_selector(self) -> None:
        if self._project_controller is not None:
            self._project_controller.update_project_selector()

    def _on_menu_project_selected(self, project_id: str) -> None:
        if self._project_controller is not None:
            self._project_controller.on_menu_project_selected(project_id)

    def _on_create_project_clicked(self) -> None:
        if self._project_controller is not None:
            self._project_controller.on_create_project_clicked()

    def _on_menu_delete_project(self) -> None:
        if self._project_controller is not None:
            self._project_controller.on_menu_delete_project()

    def _on_project_switched(self, project_id: str) -> None:
        if self._project_controller is not None:
            self._project_controller.on_project_switched(
                project_id,
                logger=logger,
                parent_widget=self,
            )

    def _load_log_history_for_project(self, project_id: str) -> None:
        if self._log_controller is not None:
            self._log_controller.load_log_history_for_project(project_id, logger)


    def _notify_pages_context_changed(self) -> None:
        """Notify pages to refresh UI state when SSH/project context changes."""
        for page_name in ("home_page", "detection_page"):
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

    def open_analysis_for_sample(
        self,
        *,
        sample_id: str,
        sample_name: str,
        r1_path: str = "",
        r2_path: str = "",
    ) -> bool:
        return False

    def _on_ssh_status_changed(self, connected: bool) -> None:
        """SSH 连接状态变化时更新状态栏"""
        self.status_bar.update_ssh_status(connected)
        if self._reconcile_controller is not None:
            self._reconcile_controller.on_ssh_status_changed(connected)

    def _on_ssh_changed_for_disk(self, connected: bool) -> None:
        """SSH connection changed: start/stop disk monitor."""
        if connected:
            if self._disk_monitor is not None:
                self._disk_monitor.on_ssh_changed(True)
            if self._reconcile_controller is not None:
                self._reconcile_controller.on_ssh_changed(True)
        else:
            if self._disk_monitor is not None:
                self._disk_monitor.on_ssh_changed(False)
            if self._reconcile_controller is not None:
                self._reconcile_controller.on_ssh_changed(False)
            self.status_bar.update_disk_usage(0, 0, 0)

    def _refresh_disk_usage(self) -> None:
        if self._disk_monitor is not None:
            self._disk_monitor.refresh()

    def _cleanup_disk_usage_worker(self) -> None:
        if self._disk_monitor is not None:
            self._disk_monitor.cleanup()

    def _connect_service_signals(self) -> None:
        queue = self._locator.job_queue
        queue.job_started.connect(self._update_queue_display)

        self._locator.ssh_changed.connect(self._on_ssh_changed_for_disk)

        # 日志页面信号连接
        self._locator.execution_started.connect(self._on_exec_started_for_log)
        self._locator.execution_completed.connect(self._on_exec_completed_for_log)
        self._locator.execution_failed.connect(self._on_exec_failed_for_log)

    def _current_project_id(self) -> str:
        if self._log_controller is not None:
            return self._log_controller.current_project_id()
        cp = self._pm.current_project
        return cp.project_id if cp else ""

    def _on_exec_started_for_log(self, execution_id: str) -> None:
        if self._log_controller is not None:
            self._log_controller.on_exec_started(execution_id, self._ssh_service_wrapper)

    def _on_exec_completed_for_log(self, execution_id: str) -> None:
        if self._log_controller is not None:
            self._log_controller.on_exec_completed(execution_id)

    def _on_exec_failed_for_log(self, execution_id: str, error: str) -> None:
        if self._log_controller is not None:
            self._log_controller.on_exec_failed(execution_id, error)


    def _schedule_reconcile_running_tasks(self, delay_ms: int = 150) -> None:
        if self._reconcile_controller is not None:
            self._reconcile_controller.schedule(delay_ms=delay_ms)

    @staticmethod
    def _collect_reconcile_actions(
        ssh,
        remote_base: str,
        running_rows: list[tuple[str, str, str]],
        failed_rows: list[tuple[str, str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        return ExecutionReconcileService.collect_actions(
            ssh,
            remote_base,
            running_rows,
            failed_rows,
        )

    @staticmethod
    def _read_status_bundle(ssh, task_dir: str) -> tuple[str, str, str]:
        return ExecutionReconcileService.read_status_bundle(ssh, task_dir)

    @staticmethod
    def _parse_status_bundle(output: str) -> dict[str, str]:
        return ExecutionReconcileService.parse_status_bundle(output)

    def _update_queue_display(self, *_args) -> None:
        status = self._locator.job_queue.get_status()
        self.status_bar.update_queue_status(
            running=status.get("running", 0),
            pending=status.get("pending", 0),
        )

    def closeEvent(self, event) -> None:
        try:
            if self._disk_monitor is not None:
                self._disk_monitor.timer.stop()
        except Exception:
            logger.debug("停止磁盘监控定时器失败", exc_info=True)

        self._cleanup_disk_usage_worker()

        log_page = getattr(self, "log_page", None)
        if log_page is not None and hasattr(log_page, "stop_tailing"):
            try:
                log_page.stop_tailing()
            except Exception:
                logger.debug("停止日志追踪失败", exc_info=True)

        try:
            self._locator.ssh_changed.disconnect(self._on_ssh_changed_for_disk)
        except (TypeError, RuntimeError):
            pass

        for signal, handler in (
            (self._locator.execution_started, self._on_exec_started_for_log),
            (self._locator.execution_completed, self._on_exec_completed_for_log),
            (self._locator.execution_failed, self._on_exec_failed_for_log),
        ):
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        if self._reconcile_controller is not None:
            self._reconcile_controller.shutdown()

        if self._ssh_service_wrapper is not None:
            for handler in (self._on_ssh_status_changed, self._on_ssh_changed_for_disk):
                try:
                    self._ssh_service_wrapper.connection_status_changed.disconnect(handler)
                except (TypeError, RuntimeError):
                    pass

        self._locator.shutdown()
        super().closeEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
            self.raise_()
            self.activateWindow()

            if hasattr(self, "sidebar") and self.sidebar is not None:
                if not self._prev_activated:
                    self.sidebar.setCurrentRow(self.sidebar.currentRow())
                    self._prev_activated = True
        elif event.type() == QEvent.Type.WindowDeactivate:
            self._prev_activated = False
        return super().event(event)



