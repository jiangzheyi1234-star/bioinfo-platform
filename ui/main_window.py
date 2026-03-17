"""主窗口：6页导航 + 项目切换 + ServiceLocator 接线。"""

import logging
from typing import Optional

import paramiko
from PyQt6.QtCore import QEvent, QPoint, QSize, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from core.data.project_manager import ProjectManager
from core.execution.tool_bridge_service import ToolBridgeService
from core.service_locator import ServiceLocator
from core.remote.ssh_service import SSHService
from core.remote.storage_manager import StorageManager
from ui.pages import SettingsPage
from ui.pages.home_page import HomePage
from ui.pages.log_page import LogPage
from ui.pages.project_page import ProjectPage, CreateProjectDialog
from ui.pages.detection_page_web import DetectionPageWeb as DetectionPage
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
        self._ssh_service_wrapper: Optional[SSHService] = None

        self._locator = ServiceLocator(project_manager=self._pm)
        self._locator.initialize()

        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(300_000)
        self._disk_timer.timeout.connect(self._refresh_disk_usage)

        self._prev_activated = True

        self.init_ui()
        self._connect_service_signals()

        # 初始化日志页面的项目上下文
        if self._pm.current_project:
            pid = self._pm.current_project.project_id
            self.log_page.set_project_context(pid)
            self.log_page.load_history(self._pm.db, pid)

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

        # -- 项目选择区：上下两行（项目名 + ▾），点击弹出菜单 --
        self._project_trigger_btn = QPushButton("\u672a\u9009\u62e9\u9879\u76ee  \u25be")
        self._project_trigger_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._project_trigger_btn.setMinimumHeight(38)
        self._project_trigger_btn.setStyleSheet(f"""
            QPushButton {{
                margin: 8px 10px 4px 10px;
                padding: 0 12px;
                text-align: left;
                border-radius: 10px;
                border: 1px solid {styles.COLOR_BORDER};
                background: {styles.COLOR_BG_CARD};
                color: {styles.COLOR_TEXT_DEFAULT};
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border: 1px solid rgba(59, 130, 246, 0.5);
                background: #F8FBFF;
            }}
            QPushButton:pressed {{
                background: #EFF6FF;
                border: 1px solid rgba(59, 130, 246, 0.65);
            }}
        """)

        self._project_menu = QMenu(self._project_trigger_btn)
        self._project_menu.setStyleSheet(f"""
            QMenu {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: 10px;
                padding: 5px;
            }}
            QMenu::item {{
                min-height: 28px;
                padding: 3px 14px;
                border-radius: 6px;
                color: {styles.COLOR_TEXT_DEFAULT};
                font-size: 13px;
                font-weight: 600;
            }}
            QMenu::item:selected {{
                background: {styles.COLOR_SELECTION_BG};
                color: {styles.COLOR_PRIMARY};
            }}
            QMenu::separator {{
                height: 1px;
                background: {styles.COLOR_BORDER};
                margin: 6px 8px;
            }}
        """)

        # 点击弹出菜单
        self.project_combo = self._project_trigger_btn  # keep legacy attribute for tests
        self._project_trigger_btn.clicked.connect(lambda: self._show_project_menu(self._project_trigger_btn))
        sidebar_layout.addWidget(self._project_trigger_btn)

        self.sidebar = QListWidget()
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sidebar.setStyleSheet(styles.SIDEBAR_NAV_ITEM)
        sidebar_layout.addWidget(self.sidebar)

        middle_layout.addWidget(sidebar_widget)

        self.content = _CurrentPageStackedWidget()

        self.home_page = HomePage(main_window=self)
        self.content.addWidget(self.home_page)

        self.detection_page = DetectionPage(main_window=self)
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

        self.sidebar.currentRowChanged.connect(self.content.setCurrentIndex)
        middle_layout.addWidget(self.content)
        main_layout.addWidget(middle, stretch=1)

        self.status_bar = EnvironmentStatusBar()
        main_layout.addWidget(self.status_bar)
        self.log_page.log_status_changed.connect(self.status_bar.update_log_status)
        self.status_bar.update_log_status("日志: 就绪")

        self.sidebar.setCurrentRow(0)

        # 初始化一次 SSH 注入
        self._on_settings_active_client_changed(self.settings_page.get_active_client())

        self._refresh_project_combo()

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

    def _on_settings_active_client_changed(self, client) -> None:
        """把 Settings 的 SSH 客户端统一注入 ServiceLocator。"""
        # 断开旧 wrapper 的信号，防止悬空引用
        if self._ssh_service_wrapper is not None:
            try:
                self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_status_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_changed_for_disk)
            except (TypeError, RuntimeError):
                pass

        if client is None:
            self._ssh_service_wrapper = None
            self._locator.ssh_service = None  # type: ignore[assignment]
            self.status_bar.update_ssh_status(False)
            self._on_ssh_changed_for_disk(False)
            self._notify_pages_context_changed()
            return

        # 构造重连函数：捕获当前连接参数，用于 SSHService 自动重连
        ssh_cfg = self.settings_page.ssh_card.last_stable_config
        connect_fn = None
        if ssh_cfg:
            def _make_connect_fn(cfg: dict):
                def _connect() -> paramiko.SSHClient:
                    c = paramiko.SSHClient()
                    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    kwargs: dict = {
                        "hostname": cfg.get("ip", ""),
                        "port": cfg.get("port", 22),
                        "username": cfg.get("user", ""),
                        "timeout": 5,
                        "allow_agent": False,
                        "look_for_keys": False,
                    }
                    if cfg.get("use_key") and cfg.get("key_file"):
                        kwargs["key_filename"] = cfg["key_file"]
                    else:
                        kwargs["password"] = cfg.get("pwd", "")
                    c.connect(**kwargs)
                    c.get_transport().set_keepalive(30)
                    return c
                return _connect
            connect_fn = _make_connect_fn(ssh_cfg)

        self._ssh_service_wrapper = SSHService(
            lambda c=client: c,
            connect_fn=connect_fn,
        )
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_status_changed)
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_changed_for_disk)
        self._locator.ssh_service = self._ssh_service_wrapper
        self.status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._on_ssh_changed_for_disk(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()

    def _refresh_project_combo(self) -> None:
        """刷新项目下拉菜单，更新按钮文字。"""
        self._project_menu.clear()
        self._pm.reload_index()
        current = self._pm.current_project
        current_id = current.project_id if current else ""

        has_projects = False
        has_deletable = False
        for p in self._pm.list_projects():
            if p.status != "active":
                continue
            has_projects = True
            label = f"  {p.name}" if p.project_id != current_id else f"\u2713 {p.name}"
            action = self._project_menu.addAction(label)
            pid = p.project_id
            action.triggered.connect(lambda checked, _pid=pid: self._on_menu_project_selected(_pid))
            if p.project_id != current_id:
                has_deletable = True

        if not has_projects:
            empty_action = self._project_menu.addAction("\u6682\u65e0\u9879\u76ee")
            empty_action.setEnabled(False)

        self._project_menu.addSeparator()
        create_action = self._project_menu.addAction(f"+ \u65b0\u5efa\u9879\u76ee")
        create_action.triggered.connect(self._on_create_project_clicked)
        if has_deletable:
            self._project_menu.addSeparator()
            delete_action = self._project_menu.addAction("\u5220\u9664\u9879\u76ee...")
            delete_action.triggered.connect(self._on_menu_delete_project)

        # 更新项目名 label
        if current:
            name = current.name if len(current.name) <= 14 else current.name[:13] + "\u2026"
            self._project_trigger_btn.setText(f"{name}  \u25be")
            self._project_trigger_btn.setToolTip(current.name)
        else:
            self._project_trigger_btn.setText("\u672a\u9009\u62e9\u9879\u76ee  \u25be")
            self._project_trigger_btn.setToolTip("")

    def _show_project_menu(self, widget) -> None:
        """在项目区域下方弹出菜单。"""
        self._refresh_project_combo()
        self._project_menu.setMinimumWidth(max(widget.width(), 220))
        pos = widget.mapToGlobal(QPoint(0, widget.height()))
        self._project_menu.popup(pos)

    def _on_menu_project_selected(self, project_id: str) -> None:
        """菜单选择了一个项目。"""
        current = self._pm.current_project
        if current and current.project_id == project_id:
            return
        try:
            self._pm.open_project(project_id)
            self._on_project_switched(project_id)
        except Exception as e:
            logger.error("切换项目失败: %s", e)
            QMessageBox.warning(
                self,
                "切换项目失败",
                f"无法打开该项目：{e}",
            )

    def _on_create_project_clicked(self) -> None:
        """菜单中点击新建项目。"""
        dialog = CreateProjectDialog(self)
        if dialog.exec():
            name, desc = dialog.get_values()
            if not name:
                return
            try:
                project_id = self._pm.create_project(name, desc)
                self._pm.open_project(project_id)
                self._on_project_switched(project_id)
            except Exception as e:
                logger.error("创建项目失败: %s", e)

    def _on_menu_delete_project(self) -> None:
        current = self._pm.current_project
        current_id = current.project_id if current else ""

        candidates = [
            p for p in self._pm.list_projects()
            if p.status == "active" and p.project_id != current_id
        ]
        if not candidates:
            QMessageBox.information(self, "提示", "没有可删除的项目。请先切换到其他项目。")
            return

        labels = [p.name for p in candidates]
        selected_name, ok = QInputDialog.getItem(
            self,
            "删除项目",
            "选择要删除的项目：",
            labels,
            0,
            False,
        )
        if not ok or not selected_name:
            return

        target = next((p for p in candidates if p.name == selected_name), None)
        if target is None:
            return

        result = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除项目“{target.name}”吗？\n项目文件将被永久删除，无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        try:
            self._pm.delete_project(target.project_id)
            self._refresh_project_combo()
            QMessageBox.information(self, "成功", f"项目“{target.name}”已删除。")
        except Exception as e:
            logger.error("删除项目失败: %s", e)
            QMessageBox.critical(self, "错误", f"删除项目失败: {e}")

    def _on_project_switched(self, project_id: str) -> None:
        self._refresh_project_combo()

        current = self._pm.current_project
        self.status_bar.update_project(current.name if current else None)
        self._reconcile_running_tasks()
        self._notify_pages_context_changed()

        # 同步日志页面的项目上下文 + 加载历史
        self.log_page.set_project_context(project_id)
        self.log_page.load_history(self._pm.db, project_id)

        if getattr(self._pm, "db_read_only", False):
            QMessageBox.warning(
                self,
                "项目只读模式",
                "当前项目数据库被其他进程占用，已以只读模式打开。\n"
                "请关闭占用该数据库的程序后重试，以恢复可写模式。",
            )

        logger.info("项目已切换: %s", project_id)


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
        if connected:
            self._reconcile_running_tasks()

    def _on_ssh_changed_for_disk(self, connected: bool) -> None:
        """SSH 连接状态变化时处理磁盘监控"""
        if connected:
            self._disk_timer.start()
            self._refresh_disk_usage()  # 立即刷新一次
        else:
            self._disk_timer.stop()
            self.status_bar.update_disk_usage(0, 0, 0)  # 清空显示

    def _refresh_disk_usage(self) -> None:
        ssh = self._locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            return

        try:
            mgr = StorageManager(ssh)
            usage = mgr.get_disk_usage("/h2ometa")
            self.status_bar.update_disk_usage(usage.used_gb, usage.total_gb, usage.percent)
        except Exception as e:
            logger.warning("刷新磁盘用量失败: %s", e)
            # 调试：尝试获取原始输出
            try:
                rc, stdout, stderr = ssh.run("df -B1 /h2ometa 2>&1", timeout=15)
                logger.debug("df 命令返回: rc=%s, stdout=%r, stderr=%r", rc, stdout, stderr)
            except Exception as debug_e:
                logger.debug("调试命令失败: %s", debug_e)

    def _connect_service_signals(self) -> None:
        queue = self._locator.job_queue
        queue.job_started.connect(self._update_queue_display)

        self._locator.ssh_changed.connect(self._on_ssh_changed_for_disk)

        # 日志页面信号连接
        self._locator.execution_started.connect(self._on_exec_started_for_log)
        self._locator.execution_completed.connect(self._on_exec_completed_for_log)
        self._locator.execution_failed.connect(self._on_exec_failed_for_log)

    def _current_project_id(self) -> str:
        cp = self._pm.current_project
        return cp.project_id if cp else ""

    def _on_exec_started_for_log(self, execution_id: str) -> None:
        task_dir = self._locator.get_task_dir(execution_id)
        if task_dir:
            self.log_page.set_execution_context(execution_id, task_dir)
            if self._ssh_service_wrapper:
                self.log_page.set_ssh_run_fn(self._ssh_service_wrapper.run)

    def _on_exec_completed_for_log(self, execution_id: str) -> None:
        pid = self._current_project_id()
        self.log_page.append_log("SUCCESS", f"任务完成: {execution_id[:16]}",
                                 execution_id, pid)
        self.log_page.stop_tailing()

    def _on_exec_failed_for_log(self, execution_id: str, error: str) -> None:
        msg = f"任务失败: {execution_id[:16]}"
        if error:
            msg += f" — {error[:100]}"
        pid = self._current_project_id()
        self.log_page.append_log("ERROR", msg, execution_id, pid)
        self.log_page.stop_tailing()

    def _reconcile_running_tasks(self) -> None:
        try:
            if self._pm.current_project is None:
                return
            ssh = self._locator.ssh_service
            if ssh is None or not getattr(ssh, "is_connected", False):
                return
            service = ToolBridgeService(
                service_locator=self._locator,
                plugin_registry=self._locator.plugin_registry,
            )
            service.get_execution_history()
        except Exception:
            logger.exception("任务状态自动校准失败")

    def _update_queue_display(self, *_args) -> None:
        status = self._locator.job_queue.get_status()
        self.status_bar.update_queue_status(
            running=status.get("running", 0),
            pending=status.get("pending", 0),
        )

    def closeEvent(self, event) -> None:
        try:
            self._disk_timer.stop()
        except Exception:
            logger.debug("停止磁盘监控定时器失败", exc_info=True)

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
