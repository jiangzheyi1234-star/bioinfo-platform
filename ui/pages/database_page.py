from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import get_config, save_config
from core.data.database_service import DatabaseCheckResult, DatabaseInfo, DatabaseService, DatabaseStatus
from ui.page_base import BasePage
from ui.widgets.database_management_components import (
    DatabaseInstallDialog,
    DatabaseInstallMonitor,
    DatabaseItemCard,
    DatabaseStatusWorker,
)
from ui.widgets.styles import BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT_LINEEDIT, PAGE_HEADER_TITLE, SCROLL_BAR_ELEGANT

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "reads": "物种分类",
    "mag": "组装质控",
    "annotation": "功能注释",
    "amr": "AMR",
    "other": "其他",
}


class DatabasePage(BasePage):
    def __init__(self):
        super().__init__("数据库管理")
        self.label.hide()
        self._ssh_client = None
        self._database_service = DatabaseService()
        self._cards: dict[str, DatabaseItemCard] = {}
        self._dialogs: dict[str, DatabaseInstallDialog] = {}
        self._status_thread: Optional[QThread] = None
        self._status_worker: Optional[DatabaseStatusWorker] = None
        self._install_threads: dict[str, QThread] = {}
        self._install_workers: dict[str, DatabaseInstallMonitor] = {}
        self._init_ui()
        self._load_db_root()

    def _init_ui(self) -> None:
        self.layout.setContentsMargins(30, 24, 30, 24)
        self.layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("数据库管理")
        title.setStyleSheet(PAGE_HEADER_TITLE)
        self.refresh_btn = QPushButton("全部刷新")
        self.refresh_btn.setStyleSheet(BUTTON_SECONDARY)
        self.refresh_btn.clicked.connect(self._refresh_all_status)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.refresh_btn)
        self.layout.addLayout(title_row)

        root_row = QHBoxLayout()
        root_label = QLabel("数据库根目录:")
        root_label.setStyleSheet("font-size: 13px; color: #334155;")
        self.db_root_edit = QLineEdit()
        self.db_root_edit.setStyleSheet(INPUT_LINEEDIT)
        self.db_root_edit.setPlaceholderText("/data/databases")
        self.save_root_btn = QPushButton("保存")
        self.save_root_btn.setStyleSheet(BUTTON_PRIMARY)
        self.save_root_btn.clicked.connect(self._save_db_root)
        root_row.addWidget(root_label)
        root_row.addWidget(self.db_root_edit, stretch=1)
        root_row.addWidget(self.save_root_btn)
        self.layout.addLayout(root_row)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                padding: 8px 16px;
                margin-right: 4px;
                color: #64748B;
                font-size: 13px;
                font-weight: 500;
                border: none;
                border-bottom: 2px solid transparent;
                background: transparent;
            }
            QTabBar::tab:selected {
                color: #3B82F6;
                font-weight: 700;
                border-bottom: 2px solid #3B82F6;
            }
            QTabBar::tab:hover {
                color: #334155;
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
        scroll.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)

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
        self.db_root_edit.setText(str(databases.get("db_root", "") or ""))

    def _get_db_root(self) -> str:
        return self.db_root_edit.text().strip()

    def _save_db_root(self) -> None:
        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            databases = {}
        databases["db_root"] = self._get_db_root()
        databases.setdefault("overrides", {})
        cfg["databases"] = databases
        save_config(cfg)
        QMessageBox.information(self, "数据库配置", "数据库根目录已保存。")
        self._refresh_all_status()

    def set_active_client(self, client) -> None:
        self._ssh_client = client
        if client is None:
            for card in self._cards.values():
                card.update_status(DatabaseCheckResult(db_id=card.db_info.db_id, status=DatabaseStatus.UNKNOWN))
            return
        self._refresh_all_status()

    def refresh_context(self) -> None:
        if self._ssh_client is not None:
            self._refresh_all_status()

    def _make_ssh_run_fn(self):
        client = self._ssh_client
        if client is None:
            raise RuntimeError("SSH client is not connected")

        def _run(cmd: str, timeout: int = 15):
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            del stdin
            rc = stdout.channel.recv_exit_status()
            return rc, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")

        return _run

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
        if self._ssh_client is None:
            return
        self._cleanup_status_worker()
        self._status_thread = QThread(self)
        self._status_worker = DatabaseStatusWorker(
            database_service=self._database_service,
            ssh_run_fn=self._make_ssh_run_fn(),
            db_root=self._get_db_root(),
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
            card.update_status(result)

    def _on_status_error(self, message: str) -> None:
        logger.warning("Database status refresh failed: %s", message)
        self._cleanup_status_worker()

    def _on_install_clicked(self, db_id: str) -> None:
        if self._ssh_client is None:
            QMessageBox.warning(self, "数据库安装", "请先连接 SSH。")
            return
        info = self._database_service.get_info(db_id)
        if info is None:
            return
        try:
            commands = self._database_service.generate_install_commands(db_id, self._get_db_root())
        except Exception as exc:
            QMessageBox.warning(self, "数据库安装", str(exc))
            return
        dialog = DatabaseInstallDialog(info, commands, parent=self)
        self._dialogs[db_id] = dialog
        dialog.install_confirmed.connect(self._start_install)
        dialog.install_cancelled.connect(lambda _: self._dialogs.pop(db_id, None))
        dialog.show()

    def _start_install(self, db_id: str, mirror_index: int) -> None:
        card = self._cards.get(db_id)
        if card is None:
            return
        try:
            result = self._database_service.submit_install(
                self._make_ssh_run_fn(),
                db_id=db_id,
                db_root=self._get_db_root(),
                mirror_index=mirror_index,
            )
        except Exception as exc:
            QMessageBox.warning(self, "数据库安装", f"提交安装任务失败: {exc}")
            return
        card.set_installing(True)
        self._start_install_monitor(db_id, result["task_dir"])

    def _start_install_monitor(self, db_id: str, task_dir: str) -> None:
        self._stop_install_monitor(db_id)
        thread = QThread(self)
        worker = DatabaseInstallMonitor(
            database_service=self._database_service,
            ssh_run_fn=self._make_ssh_run_fn(),
            db_id=db_id,
            task_dir=task_dir,
            db_root=self._get_db_root(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.log_updated.connect(self._on_log_updated)
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

    def _on_progress_updated(self, db_id: str, percent: int, speed: str, eta: str) -> None:
        card = self._cards.get(db_id)
        if card:
            card.update_progress(percent, speed=speed, eta=eta)
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.update_progress(percent, speed, eta)

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
        self._refresh_all_status()

    def _on_path_override(self, db_id: str) -> None:
        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            databases = {}
        overrides = databases.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        current = str(overrides.get(db_id, "") or "")
        value, ok = QInputDialog.getText(self, "数据库路径覆盖", f"设置 {db_id} 的绝对路径:", text=current)
        if not ok:
            return
        path = str(value or "").strip()
        if path:
            overrides[db_id] = path
        else:
            overrides.pop(db_id, None)
        databases["overrides"] = overrides
        databases.setdefault("db_root", self._get_db_root())
        cfg["databases"] = databases
        save_config(cfg)
        self._refresh_all_status()

    def _on_cancel_install(self, db_id: str) -> None:
        self._stop_install_monitor(db_id)
        card = self._cards.get(db_id)
        if card:
            card.set_installing(False)
        dialog = self._dialogs.pop(db_id, None)
        if dialog:
            dialog.reject()

    def closeEvent(self, event) -> None:
        self._cleanup_status_worker()
        for db_id in list(self._install_threads.keys()):
            self._stop_install_monitor(db_id)
        super().closeEvent(event)
