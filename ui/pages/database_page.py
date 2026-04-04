from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import get_config, save_config
from core.data.database_service import DatabaseCheckResult, DatabaseInfo, DatabaseService, DatabaseStatus
from core.remote.server_capabilities import ServerCapabilities
from ui.page_base import BasePage
from ui.pages.database_dialogs import _AsyncTaskWorker, DatabaseSettingsDialog, RemoteDirectoryPickerDialog
from ui.pages.database_remote_ops import DatabaseRemoteOpsMixin
from ui.widgets.database_management_components import (
    DatabaseInstallDialog,
    DatabaseInstallMonitor,
    DatabaseItemCard,
    DatabaseStatusWorker,
)
from ui.widgets.styles import PAGE_HEADER_TITLE

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "reads": "物种分类",
    "mag": "组装质控",
    "annotation": "功能注释",
    "amr": "AMR",
    "other": "其他",
}

_ICON_COLOR = "#64748B"
_SETTINGS_ICON_COLOR = "#64748B"

_GHOST_BTN_STYLE = """
    QPushButton {
        background: transparent;
        color: #64748B;
        border: none;
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 13px;
    }
    QPushButton:hover {
        background: #EEF2F7;
        color: #334155;
    }
    QPushButton:pressed {
        background: #E2E8F0;
    }
"""

_ICON_BTN_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 14px;
    }
    QPushButton:hover {
        background: #E2E8F0;
    }
    QPushButton:pressed {
        background: #CBD5E1;
    }
"""

_SCROLL_BAR_GRAY = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(100, 116, 139, 0.22);
        border-radius: 5px;
        min-height: 40px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(100, 116, 139, 0.35);
    }
    QScrollBar::handle:vertical:pressed {
        background: rgba(100, 116, 139, 0.48);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
        background: transparent;
        border: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""


class DatabasePage(DatabaseRemoteOpsMixin, BasePage):
    install_task_event = pyqtSignal(dict)

    def __init__(self):
        super().__init__("数据库管理")
        self.label.hide()
        self._ssh_client = None
        self._ssh_service = None
        self._db_root_value = ""
        self._database_service = DatabaseService()
        self._cards: dict[str, DatabaseItemCard] = {}
        self._dialogs: dict[str, DatabaseInstallDialog] = {}
        self._status_thread: Optional[object] = None
        self._status_worker: Optional[DatabaseStatusWorker] = None
        self._install_threads: dict[str, object] = {}
        self._install_workers: dict[str, DatabaseInstallMonitor] = {}
        self._install_verify_paths: dict[str, str] = {}
        self._async_tasks: dict[str, tuple[QThread, _AsyncTaskWorker]] = {}
        self._install_submit_pending: set[str] = set()
        self._init_ui()
        self._load_db_root()

    def _init_ui(self) -> None:
        self.layout.setContentsMargins(30, 24, 30, 24)
        self.layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel("数据库管理")
        title.setStyleSheet(PAGE_HEADER_TITLE)

        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(qta.icon("ph.gear-six", color=_SETTINGS_ICON_COLOR))
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setToolTip("数据库设置")
        self.settings_btn.setStyleSheet(_ICON_BTN_STYLE)
        self.settings_btn.clicked.connect(self._open_db_settings_dialog)

        self.refresh_btn = QPushButton("  刷新")
        self.refresh_btn.setIcon(qta.icon("ph.arrows-clockwise", color=_ICON_COLOR))
        self.refresh_btn.setIconSize(QSize(15, 15))
        self.refresh_btn.setStyleSheet(_GHOST_BTN_STYLE)
        self.refresh_btn.clicked.connect(self._refresh_all_status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #E2E8F0; max-height: 20px;")

        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.refresh_btn)
        title_row.addWidget(sep)
        title_row.addWidget(self.settings_btn)
        self.layout.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar {
                background: transparent;
            }
            QTabBar::tab {
                background: transparent;
                color: #64748B;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 8px 18px 10px 18px;
                font-size: 13px;
                font-weight: 600;
                min-width: 72px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                color: #334155;
                font-weight: 700;
                border-bottom: 2px solid #94A3B8;
            }
            QTabBar::tab:hover:!selected {
                color: #475569;
            }
            """
        )
        self.layout.addWidget(self.tabs, stretch=1)

        grouped = self._database_service.list_by_category()
        for category in ("reads", "mag", "annotation", "amr", "other"):
            infos = grouped.get(category, [])
            page = self._build_category_page(infos)
            self.tabs.addTab(page, CATEGORY_LABELS.get(category, category))

    def _build_category_page(self, infos: list[DatabaseInfo]) -> QWidget:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.verticalScrollBar().setStyleSheet(_SCROLL_BAR_GRAY)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)
        for info in infos:
            card = DatabaseItemCard(info)
            card.install_requested.connect(self._on_install_clicked)
            card.path_override_requested.connect(self._on_path_override)
            card.cancel_requested.connect(self._on_cancel_install)
            self._cards[info.db_id] = card
            content_layout.addWidget(card)
        content_layout.addStretch()
        scroll.setWidget(content)
        host_layout.addWidget(scroll)
        return host

    def _load_db_root(self) -> None:
        cfg = get_config()
        databases = cfg.get("databases", {})
        self._db_root_value = str(databases.get("db_root", "") or "")

    def _get_server_capabilities(self) -> tuple[ServerCapabilities | None, str]:
        window = self.window()
        locator = getattr(window, "service_locator", None)
        if locator is None:
            return None, "未找到运行时服务上下文"
        caps = getattr(locator, "server_capabilities", None)
        error = str(getattr(locator, "server_capability_error", "") or "")
        if isinstance(caps, ServerCapabilities):
            return caps, error
        return None, error

    def _emit_install_task_event(
        self,
        db_id: str,
        state: str,
        *,
        message: str = "",
        progress_value: Optional[int] = None,
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "database",
        updated_at: Optional[float] = None,
    ) -> None:
        db_key = str(db_id or "").strip()
        if not db_key:
            return
        info = self._database_service.get_info(db_key)
        title = f"数据库安装 · {info.name if info else db_key}"
        payload = {
            "task_id": f"db:{db_key}",
            "title": title,
            "source": "db",
            "state": str(state or "").strip().lower() or "running",
            "message": str(message or "").strip(),
            "progress_value": progress_value if progress_value is None else max(int(progress_value), 0),
            "progress_text": str(progress_text or "").strip(),
            "speed_text": str(speed_text or "").strip(),
            "location_hint": str(location_hint or "").strip(),
            "updated_at": float(updated_at if updated_at is not None else time.time()),
        }
        self.install_task_event.emit(payload)

    def _get_database_info(self, db_id: str) -> DatabaseInfo | None:
        return self._database_service.get_info(str(db_id or "").strip())

    def _get_database_effective_path(self, db_id: str) -> str:
        return self._database_service.resolve_binding_value(
            db_id,
            self._get_db_root(),
            overrides=self._get_database_overrides(),
        )

    def _save_db_root(self, raw_input: str = "", done_cb: Optional[Callable[[bool], None]] = None) -> bool:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            QMessageBox.warning(self, "数据库配置", "请先连接 SSH，再保存数据库根目录。")
            if done_cb:
                done_cb(False)
            return False

        candidate = raw_input
        if not candidate:
            candidate = self._resolve_empty_db_root_candidate()
            if not candidate:
                if done_cb:
                    done_cb(False)
                return False

        def _persist(resolved_root: str, created: bool) -> None:
            cfg = get_config()
            databases = cfg.get("databases", {})
            if not isinstance(databases, dict):
                databases = {}
            databases["db_root"] = resolved_root
            databases.setdefault("overrides", {})
            cfg["databases"] = databases
            if self._empty_db_root_preference:
                runtime = cfg.get("runtime", {})
                if not isinstance(runtime, dict):
                    runtime = {}
                runtime["db_root_empty_action"] = self._empty_db_root_preference
                cfg["runtime"] = runtime
            save_config(cfg)
            self._db_root_value = resolved_root
            if created:
                QMessageBox.information(self, "数据库配置", f"已自动创建并保存目录: {resolved_root}")
            else:
                QMessageBox.information(self, "数据库配置", f"数据库根目录已保存: {resolved_root}")
            self._refresh_all_status()
            if done_cb:
                done_cb(True)

        def _run_validate(allow_create: bool) -> bool:
            task_key = "db_root_validate"
            return self._start_async_task(
                task_key,
                lambda: {
                    "allow_create": allow_create,
                    "result": self._validate_db_root_remote(candidate, allow_create=allow_create),
                },
                on_success=lambda payload: _on_validated(payload["allow_create"], payload["result"]),
                on_error=lambda err: _on_validate_error(allow_create, err),
            )

        def _on_validate_error(_allow_create: bool, err: str) -> None:
            QMessageBox.warning(self, "数据库配置", f"数据库根目录校验失败: {err}")
            if done_cb:
                done_cb(False)

        def _on_validated(allow_create: bool, result: tuple[bool, str, str, bool]) -> None:
            ok, resolved_root, message, created = result
            if ok:
                _persist(resolved_root, created)
                return
            if (not allow_create) and message.startswith("目录不存在:"):
                answer = QMessageBox.question(
                    self,
                    "目录不存在",
                    f"{message}\n是否现在创建该目录并继续保存？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    if not _run_validate(True):
                        QMessageBox.warning(self, "数据库配置", "目录校验任务已在执行，请稍候。")
                        if done_cb:
                            done_cb(False)
                    return
            QMessageBox.warning(self, "数据库配置", message)
            if done_cb:
                done_cb(False)

        started = _run_validate(False)
        if not started:
            QMessageBox.warning(self, "数据库配置", "目录校验任务已在执行，请稍候。")
            if done_cb:
                done_cb(False)
        return started

    def _open_db_settings_dialog(self) -> None:
        dialog = DatabaseSettingsDialog(
            initial_path=self._get_db_root(),
            info_fn=self._collect_db_root_info,
            browse_fn=self._pick_remote_db_root,
            save_fn=self._save_db_root,
            parent=self,
        )
        dialog.popup_at(self.settings_btn)
        dialog.exec()

    def _pick_remote_db_root(self, start_path: str = "", anchor=None) -> str:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            QMessageBox.warning(self, "目录浏览", "请先连接 SSH，再浏览远程目录。")
            return ""
        start_path = start_path or self._get_db_root() or "~"
        dialog = RemoteDirectoryPickerDialog(start_path, self._list_remote_directories_async, parent=self)
        dialog.popup_at(anchor)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_path:
            return dialog.selected_path
        return ""

    def _start_async_task(
        self,
        task_key: str,
        task_fn: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        if task_key in self._async_tasks:
            return False
        thread = QThread(self)
        worker = _AsyncTaskWorker(task_fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda payload, k=task_key: self._on_async_task_finished(k, payload, on_success))
        worker.failed.connect(lambda err, k=task_key: self._on_async_task_failed(k, err, on_error))
        self._async_tasks[task_key] = (thread, worker)
        thread.start()
        return True

    def _on_async_task_finished(self, task_key: str, payload: object, on_success: Callable[[object], None]) -> None:
        self._stop_async_task(task_key)
        on_success(payload)

    def _on_async_task_failed(self, task_key: str, error: str, on_error: Optional[Callable[[str], None]]) -> None:
        self._stop_async_task(task_key)
        if on_error:
            on_error(error)
        else:
            logger.warning("Async task failed (%s): %s", task_key, error)

    def _stop_async_task(self, task_key: str) -> None:
        pair = self._async_tasks.pop(task_key, None)
        if not pair:
            return
        thread, _worker = pair
        thread.quit()
        thread.wait(1500)
        thread.deleteLater()

    @property
    def _empty_db_root_preference(self) -> str:
        cfg = get_config()
        runtime = cfg.get("runtime", {})
        if not isinstance(runtime, dict):
            return ""
        value = str(runtime.get("db_root_empty_action", "") or "").strip().lower()
        return value if value in {"use_home"} else ""

    def _resolve_empty_db_root_candidate(self) -> str:
        if self._empty_db_root_preference == "use_home":
            return "~/databases"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("数据库配置")
        msg.setText("尚未设置数据库根目录，建议使用 ~/databases。")
        msg.setInformativeText("请选择下一步操作。")
        use_home_btn = msg.addButton("使用 ~/databases", QMessageBox.ButtonRole.AcceptRole)
        manual_btn = msg.addButton("手动输入", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        remember_box = QCheckBox("记住这次选择")
        msg.setCheckBox(remember_box)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == use_home_btn:
            if remember_box.isChecked():
                cfg = get_config()
                runtime = cfg.get("runtime", {})
                if not isinstance(runtime, dict):
                    runtime = {}
                runtime["db_root_empty_action"] = "use_home"
                cfg["runtime"] = runtime
                save_config(cfg)
            return "~/databases"
        if clicked in (manual_btn, cancel_btn):
            return ""
        return ""

    def set_active_client(self, client) -> None:
        self._ssh_client = client
        if client is None and self._ssh_service is None:
            for card in self._cards.values():
                card.update_status(DatabaseCheckResult(db_id=card.db_info.db_id, status=DatabaseStatus.UNKNOWN))
            return
        self._refresh_all_status()
        self._recover_running_install_monitors()

    def set_ssh_service(self, ssh_service) -> None:
        self._ssh_service = ssh_service
        if ssh_service is None and self._ssh_client is None:
            for card in self._cards.values():
                card.update_status(DatabaseCheckResult(db_id=card.db_info.db_id, status=DatabaseStatus.UNKNOWN))
            return
        self._refresh_all_status()
        self._recover_running_install_monitors()

    def refresh_context(self) -> None:
        if self._ssh_service is not None or self._ssh_client is not None:
            self._refresh_all_status()
            self._recover_running_install_monitors()

    def _cleanup_status_worker(self) -> None:
        if self._status_worker is not None and hasattr(self._status_worker, "cancel"):
            self._status_worker.cancel()
        if self._status_thread is not None:
            self._status_thread.quit()
            self._status_thread.wait(1500)
            self._status_thread.deleteLater()
        self._status_worker = None
        self._status_thread = None

    def _refresh_all_status(self) -> None:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            return
        from PyQt6.QtCore import QThread
        self._cleanup_status_worker()
        self._status_thread = QThread(self)
        self._status_worker = DatabaseStatusWorker(
            database_service=self._database_service,
            status_check_fn=self._check_database_status,
        )
        self._status_worker.moveToThread(self._status_thread)
        self._status_thread.started.connect(self._status_worker.run)
        self._status_worker.status_checked.connect(self._on_status_checked)
        self._status_worker.all_done.connect(self._cleanup_status_worker)
        self._status_worker.error.connect(self._on_status_error)
        self._status_thread.start()

    def _on_status_checked(self, db_id: str, result) -> None:
        card = self._cards.get(db_id)
        if card is not None:
            if db_id in self._install_workers or db_id in self._install_submit_pending:
                return
            card.update_status(result)

    def _on_status_error(self, message: str) -> None:
        logger.warning("Database status refresh failed: %s", message)
        self._cleanup_status_worker()

    def _on_install_clicked(self, db_id: str) -> None:
        try:
            logger.info("install_confirm_click db_id=%s", db_id)
            if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
                QMessageBox.warning(self, "数据库安装", "请先连接 SSH。")
                return
            caps, preflight_error = self._get_server_capabilities()
            if caps is None:
                QMessageBox.warning(
                    self,
                    "数据库安装",
                    preflight_error or "服务器预检尚未完成，请稍后重试。",
                )
                return
            info = self._database_service.get_info(db_id)
            if info is None:
                return
            try:
                commands = self._database_service.generate_install_commands(caps, db_id, self._get_db_root())
            except Exception as exc:
                QMessageBox.warning(self, "数据库安装", str(exc))
                return
            dialog = DatabaseInstallDialog(info, commands, parent=self)
            self._dialogs[db_id] = dialog
            dialog.install_confirmed.connect(self._submit_install_async)
            dialog.install_cancelled.connect(lambda _: self._dialogs.pop(db_id, None))
            dialog.show()
        except Exception as exc:
            logger.exception("install_confirm_click_error db_id=%s error=%s", db_id, exc)
            QMessageBox.warning(self, "数据库安装", f"打开安装窗口失败: {exc}")

    def locate_install_task(self, task: dict) -> None:
        db_id = self._extract_db_id_from_task(task)
        if not db_id:
            logger.debug("无法从安装任务中解析数据库 ID: %s", task)
            return
        dialog = self._dialogs.get(db_id)
        if dialog is not None:
            if dialog.isMinimized():
                dialog.showNormal()
            else:
                dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
        self._on_install_clicked(db_id)

    @staticmethod
    def _extract_db_id_from_task(task: dict) -> str:
        task_id = str(task.get("task_id", "") or "").strip()
        if task_id.startswith("db:"):
            return str(task_id.split(":", 1)[1]).strip()
        return ""

    def _submit_install_async(self, db_id: str, mirror_index: int) -> None:
        try:
            logger.info("install_submit_begin db_id=%s mirror_index=%s", db_id, mirror_index)
            if db_id in self._install_submit_pending:
                QMessageBox.information(self, "数据库安装", "该数据库安装任务正在提交，请稍候。")
                return
            caps, preflight_error = self._get_server_capabilities()
            if caps is None:
                QMessageBox.warning(
                    self,
                    "数据库安装",
                    preflight_error or "服务器预检尚未完成，请稍后重试。",
                )
                return
            card = self._cards.get(db_id)
            if card is None:
                return
            self._install_submit_pending.add(db_id)
            card.set_installing(True)
            self._install_verify_paths[db_id] = self._get_database_install_target_path(db_id)
            self._emit_install_task_event(db_id, "running", message="正在提交安装任务")

            started = self._start_async_task(
                f"submit_install:{db_id}",
                lambda: self._database_service.submit_install(
                    self._make_ssh_run_fn(),
                    caps,
                    db_id=db_id,
                    db_root=self._get_db_root(),
                    mirror_index=mirror_index,
                ),
                on_success=lambda result: self._on_install_submit_success(db_id, result),
                on_error=lambda err: self._on_install_submit_failed(db_id, err),
            )
            if not started:
                self._install_submit_pending.discard(db_id)
                card.set_installing(False)
                self._install_verify_paths.pop(db_id, None)
                self._emit_install_task_event(db_id, "failed", message="安装提交任务已在执行")
                QMessageBox.warning(self, "数据库安装", "安装提交任务已在执行，请稍候。")
                return
        except Exception as exc:
            self._install_submit_pending.discard(db_id)
            card = self._cards.get(db_id)
            if card is not None:
                card.set_installing(False)
            self._install_verify_paths.pop(db_id, None)
            logger.exception("install_submit_error db_id=%s error=%s", db_id, exc)
            self._emit_install_task_event(db_id, "failed", message=f"提交安装任务失败: {exc}")
            QMessageBox.warning(self, "数据库安装", f"提交安装任务失败: {exc}")

    def _on_install_submit_success(self, db_id: str, result: dict) -> None:
        logger.info("install_submit_end db_id=%s rc=0", db_id)
        self._install_submit_pending.discard(db_id)
        task_dir = str(result.get("task_dir", "") or "").strip()
        if not task_dir:
            self._on_install_submit_failed(db_id, "返回的任务目录为空")
            return
        self._emit_install_task_event(db_id, "running", message="安装任务已提交，正在拉取进度")
        self._start_install_monitor(db_id, task_dir)

    def _on_install_submit_failed(self, db_id: str, error: str) -> None:
        logger.warning("install_submit_end db_id=%s rc=-1 error=%s", db_id, error)
        self._install_submit_pending.discard(db_id)
        card = self._cards.get(db_id)
        if card is not None:
            card.set_installing(False)
        self._install_verify_paths.pop(db_id, None)
        self._emit_install_task_event(db_id, "failed", message=str(error or "提交安装任务失败"))
        QMessageBox.warning(self, "数据库安装", f"提交安装任务失败: {error}")

    def _start_install_monitor(self, db_id: str, task_dir: str) -> None:
        from PyQt6.QtCore import QThread
        verify_db_path = str(self._install_verify_paths.get(db_id, "") or "").strip() or self._get_database_install_target_path(db_id)
        self._stop_install_monitor(db_id)
        thread = QThread(self)
        worker = DatabaseInstallMonitor(
            database_service=self._database_service,
            ssh_run_fn=self._make_ssh_run_fn(),
            db_id=db_id,
            task_dir=task_dir,
            verify_db_path=verify_db_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.log_updated.connect(self._on_log_updated)
        worker.install_stalled.connect(self._on_install_stalled)
        worker.install_finished.connect(self._on_install_finished)
        self._install_threads[db_id] = thread
        self._install_workers[db_id] = worker
        thread.start()

    def _stop_install_monitor(self, db_id: str) -> None:
        worker = self._install_workers.pop(db_id, None)
        if worker is not None and hasattr(worker, "cancel"):
            worker.cancel()
        thread = self._install_threads.pop(db_id, None)
        if thread is not None:
            thread.quit()
            if not thread.wait(1500):
                logger.warning("Database install thread did not stop in time: %s", db_id)
            thread.deleteLater()
        self._install_verify_paths.pop(db_id, None)

    def _on_progress_updated(self, db_id: str, percent: int, speed: str, eta: str) -> None:
        card = self._cards.get(db_id)
        if card:
            card.update_progress(percent, speed=speed, eta=eta)
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.update_progress(percent, speed, eta)
        detail_parts = [f"{int(percent)}%"]
        if str(speed or "").strip():
            detail_parts.append(f"速度 {speed}")
        if str(eta or "").strip():
            detail_parts.append(f"预计 {eta}")
        self._emit_install_task_event(
            db_id,
            "running",
            message=" · ".join(detail_parts),
            progress_value=int(percent),
            progress_text=f"{int(percent)}%",
            speed_text=str(speed or "").strip(),
        )

    def _on_log_updated(self, db_id: str, log_text: str) -> None:
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.update_log(log_text)

    def _on_install_finished(self, db_id: str, success: bool, message: str) -> None:
        self._stop_install_monitor(db_id)
        card = self._cards.get(db_id)
        if card is not None:
            card.set_installing(False)
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.show_result(success, message)
        self._emit_install_task_event(
            db_id,
            "success" if success else "failed",
            message=str(message or "").strip(),
        )
        self._refresh_all_status()

    def _on_install_stalled(self, db_id: str, message: str) -> None:
        self._emit_install_task_event(db_id, "running", message=str(message or "安装任务心跳超时").strip())
        dialog = self._dialogs.get(db_id)
        if dialog is not None:
            dialog.update_log(message)

    def _scan_running_install_tasks(self) -> list[dict[str, str]]:
        ssh_run_fn = self._make_ssh_run_fn()
        rows: list[dict[str, str]] = []
        for info in self._database_service.list_all():
            task_dir = f"{self._database_service.INSTALL_BASE}/{info.db_id}"
            status = self._database_service.check_install_status(ssh_run_fn, task_dir)
            if str(status.get("status", "")).strip().upper() == "RUNNING":
                rows.append({"db_id": info.db_id, "task_dir": task_dir})
        return rows

    def _recover_running_install_monitors(self) -> None:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            return
        started = self._start_async_task(
            "db_install_recovery",
            self._scan_running_install_tasks,
            on_success=self._on_recover_running_install_monitors_finished,
            on_error=self._on_recover_running_install_monitors_error,
        )
        if not started:
            return

    def _on_recover_running_install_monitors_finished(self, payload: object) -> None:
        rows = list(payload if isinstance(payload, list) else [])
        for item in rows:
            db_id = str(item.get("db_id", "") or "").strip()
            task_dir = str(item.get("task_dir", "") or "").strip()
            if not db_id or not task_dir:
                continue
            if db_id in self._install_workers:
                continue
            card = self._cards.get(db_id)
            if card is not None:
                card.set_installing(True)
            self._emit_install_task_event(db_id, "running", message="检测到后台数据库安装任务仍在运行")
            self._start_install_monitor(db_id, task_dir)

    def _on_recover_running_install_monitors_error(self, message: str) -> None:
        logger.warning("恢复数据库安装监控失败: %s", message)

    def _on_path_override(self, db_id: str) -> None:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            QMessageBox.warning(self, "数据库路径覆盖", "请先连接 SSH，再选择已有路径。")
            return

        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            databases = {}
        overrides = databases.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        current = str(overrides.get(db_id, "") or "").strip()
        start_path = self._get_db_root() or "~"
        if current:
            expanded_current = self._normalize_remote_path(self._expand_remote_path(current) or current)
            start_path = self._database_service.get_storage_root(db_id, expanded_current)
        selected = self._pick_remote_db_root(start_path)
        if not selected:
            return

        info = self._get_database_info(db_id)
        if info is None:
            QMessageBox.warning(self, "数据库路径覆盖", f"未找到数据库定义: {db_id}")
            return
        result = self._check_database_path_remote(info, selected)
        if result.status != DatabaseStatus.READY:
            QMessageBox.warning(self, "数据库路径覆盖", result.message or "数据库路径完整性校验失败")
            return

        binding_value = self._database_service.binding_value_from_storage_root(
            db_id,
            self._normalize_remote_path(self._expand_remote_path(selected) or selected),
        )
        try:
            self._database_service.ensure_status_marker_at_path(
                self._make_ssh_run_fn(),
                db_id,
                binding_value,
            )
        except Exception as exc:
            QMessageBox.warning(self, "数据库路径覆盖", f"数据库内容可用，但写入状态标记失败: {exc}")
            return
        overrides[db_id] = binding_value
        databases["overrides"] = overrides
        databases.setdefault("db_root", self._get_db_root())
        cfg["databases"] = databases
        save_config(cfg)
        QMessageBox.information(self, "数据库路径覆盖", f"{db_id} 已设置为: {overrides[db_id]}")
        self._refresh_all_status()

    def _on_cancel_install(self, db_id: str) -> None:
        self._stop_install_monitor(db_id)
        card = self._cards.get(db_id)
        if card:
            card.set_installing(False)
        dialog = self._dialogs.pop(db_id, None)
        if dialog:
            dialog.reject()
        self._emit_install_task_event(db_id, "failed", message="用户已取消安装任务")

    def closeEvent(self, event) -> None:
        self._cleanup_status_worker()
        for task_key in list(self._async_tasks.keys()):
            self._stop_async_task(task_key)
        for db_id in list(self._install_threads.keys()):
            self._stop_install_monitor(db_id)
        self._install_submit_pending.clear()
        super().closeEvent(event)
