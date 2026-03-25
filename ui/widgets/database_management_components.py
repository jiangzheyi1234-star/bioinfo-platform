from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QSize, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.data.database_service import (
    DatabaseCheckResult,
    DatabaseInfo,
    DatabaseService,
    DatabaseStatus,
)
from ui.widgets.styles import BUTTON_PRIMARY, BUTTON_SECONDARY

try:
    import qtawesome as qta
except Exception:  # pragma: no cover - fallback when optional dep is missing
    qta = None


class DatabaseItemCard(QFrame):
    install_requested = pyqtSignal(str)
    path_override_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)

    def __init__(self, db_info: DatabaseInfo, parent=None):
        super().__init__(parent)
        self.db_info = db_info
        self._installing = False
        self._status = DatabaseStatus.UNKNOWN

        self._build_ui()
        self.update_status(DatabaseCheckResult(db_id=db_info.db_id, status=DatabaseStatus.UNKNOWN))

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QFrame:hover {
                border: 1px solid #BFDBFE;
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setStyleSheet("QFrame { border: none; border-radius: 0; }")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 10, 12, 8)

        self.dot_label = QLabel("●")
        self.dot_label.setStyleSheet("font-size: 11px; color: #94A3B8;")
        self.name_label = QLabel(self.db_info.name)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #0F172A;")
        self.size_label = QLabel(f"{self.db_info.size_mb / 1024:.1f} GB" if self.db_info.size_mb >= 1024 else f"{self.db_info.size_mb} MB")
        self.size_label.setStyleSheet("font-size: 12px; color: #64748B;")
        top_layout.addWidget(self.dot_label)
        top_layout.addWidget(self.name_label)
        top_layout.addStretch()
        top_layout.addWidget(self.size_label)

        mid = QFrame()
        mid.setStyleSheet("QFrame { border: none; border-radius: 0; }")
        mid_layout = QHBoxLayout(mid)
        mid_layout.setContentsMargins(12, 0, 12, 8)
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("font-size: 12px; color: #64748B;")
        mid_layout.addWidget(self.meta_label)

        self.progress_wrap = QFrame()
        self.progress_wrap.setStyleSheet("QFrame { border: none; border-radius: 0; }")
        p_layout = QVBoxLayout(self.progress_wrap)
        p_layout.setContentsMargins(12, 0, 12, 8)
        p_layout.setSpacing(4)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(
            "QProgressBar { border: 1px solid #CBD5E1; border-radius: 4px; background: #F8FAFC; height: 12px; }"
            "QProgressBar::chunk { background: #3B82F6; border-radius: 3px; }"
        )
        self.progress_meta = QLabel("")
        self.progress_meta.setStyleSheet("font-size: 11px; color: #475569;")
        p_layout.addWidget(self.progress)
        p_layout.addWidget(self.progress_meta)
        self.progress_wrap.hide()

        bottom = QFrame()
        bottom.setStyleSheet("QFrame { border: none; border-radius: 0; }")
        b_layout = QHBoxLayout(bottom)
        b_layout.setContentsMargins(12, 0, 12, 10)
        b_layout.addStretch()
        self.install_btn = QPushButton("下载安装")
        self.install_btn.setStyleSheet(BUTTON_PRIMARY)
        self.install_btn.clicked.connect(lambda: self.install_requested.emit(self.db_info.db_id))
        self.reinstall_btn = QPushButton("重新安装")
        self.reinstall_btn.setStyleSheet(BUTTON_SECONDARY)
        self.reinstall_btn.clicked.connect(lambda: self.install_requested.emit(self.db_info.db_id))
        self.path_btn = QPushButton("选择已有路径")
        self.path_btn.setStyleSheet(BUTTON_SECONDARY)
        self.path_btn.clicked.connect(lambda: self.path_override_requested.emit(self.db_info.db_id))
        if qta is not None:
            self.install_btn.setIcon(qta.icon("ph.download-simple", color="#FFFFFF"))
            self.install_btn.setIconSize(QSize(14, 14))
            self.path_btn.setIcon(qta.icon("ph.folder-open", color="#475569"))
            self.path_btn.setIconSize(QSize(14, 14))
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.db_info.db_id))
        for btn in (self.install_btn, self.reinstall_btn, self.path_btn, self.cancel_btn):
            b_layout.addWidget(btn)

        root.addWidget(top)
        root.addWidget(mid)
        root.addWidget(self.progress_wrap)
        root.addWidget(bottom)

    def _set_status_style(self, color: str) -> None:
        self.dot_label.setStyleSheet(f"font-size: 11px; color: {color};")

    def update_status(self, result: DatabaseCheckResult) -> None:
        self._status = result.status
        tools = ",".join(self.db_info.tools) if self.db_info.tools else "-"
        msg = result.message or ""
        if result.status == DatabaseStatus.READY:
            self._set_status_style("#10B981")
            self.meta_label.setText(f"工具: {tools} · 状态: 已就绪")
            self.install_btn.hide()
            self.path_btn.hide()
            self.cancel_btn.hide()
            self.reinstall_btn.show()
        elif result.status in (DatabaseStatus.NOT_INSTALLED, DatabaseStatus.INCOMPLETE):
            self._set_status_style("#EF4444")
            suffix = f" · {msg}" if msg else ""
            self.meta_label.setText(f"工具: {tools} · 状态: 未安装/不完整{suffix}")
            self.reinstall_btn.hide()
            self.cancel_btn.hide()
            self.install_btn.show()
            self.path_btn.show()
        elif result.status == DatabaseStatus.INSTALLING:
            self._set_status_style("#3B82F6")
            self.meta_label.setText(f"工具: {tools} · 状态: 安装中")
            self.install_btn.hide()
            self.reinstall_btn.hide()
            self.path_btn.hide()
            self.cancel_btn.show()
            self.progress_wrap.show()
        else:
            self._set_status_style("#94A3B8")
            self.meta_label.setText(f"工具: {tools} · 状态: 未知")
            self.install_btn.show()
            self.path_btn.show()
            self.reinstall_btn.hide()
            self.cancel_btn.hide()

    def update_progress(self, percent: int, speed: str = "", eta: str = "") -> None:
        self.progress_wrap.show()
        self.progress.setValue(max(0, min(100, int(percent))))
        parts = []
        if speed:
            parts.append(f"速度: {speed}")
        if eta:
            parts.append(f"ETA: {eta}")
        self.progress_meta.setText(" · ".join(parts) if parts else "")

    def set_installing(self, installing: bool) -> None:
        self._installing = installing
        if installing:
            self.update_status(DatabaseCheckResult(db_id=self.db_info.db_id, status=DatabaseStatus.INSTALLING))
        else:
            self.progress_wrap.hide()


class DatabaseInstallDialog(QDialog):
    install_confirmed = pyqtSignal(str, int)
    install_cancelled = pyqtSignal(str)

    def __init__(self, db_info: DatabaseInfo, commands: list[str], parent=None):
        super().__init__(parent)
        self.db_info = db_info
        self.commands = commands
        self.setWindowTitle(f"安装数据库 - {db_info.name}")
        self.resize(620, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        summary = QLabel(
            f"{self.db_info.name}\n{self.db_info.description}\n大小: {self.db_info.size_mb} MB"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 12px; color: #334155;")
        layout.addWidget(summary)

        self.mirror_combo = QComboBox()
        mirrors = self.db_info.mirrors or [{"mirror": "default"}]
        for i, m in enumerate(mirrors):
            label = str(m.get("mirror") or f"mirror-{i}")
            self.mirror_combo.addItem(label, i)
        layout.addWidget(self.mirror_combo)

        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setPlainText("\n".join(self.commands))
        self.command_preview.setStyleSheet(
            "QPlainTextEdit { background: #0F172A; color: #E2E8F0; border-radius: 8px; font-family: Consolas; }"
        )
        layout.addWidget(self.command_preview, stretch=1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.progress_meta = QLabel("")
        self.progress_meta.hide()
        self.progress_meta.setStyleSheet("font-size: 12px; color: #475569;")
        layout.addWidget(self.progress_meta)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.hide()
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background: #111827; color: #E5E7EB; border-radius: 8px; font-family: Consolas; }"
        )
        layout.addWidget(self.log_view, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.confirm_btn = QPushButton("确认安装")
        self.confirm_btn.setStyleSheet(BUTTON_PRIMARY)
        self.confirm_btn.clicked.connect(self._on_confirm)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setStyleSheet(BUTTON_SECONDARY)
        self.close_btn.hide()
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def _on_confirm(self) -> None:
        idx = int(self.mirror_combo.currentData() or 0)
        self.install_confirmed.emit(self.db_info.db_id, idx)
        self.start_monitoring()

    def _on_cancel(self) -> None:
        self.install_cancelled.emit(self.db_info.db_id)
        self.reject()

    def start_monitoring(self) -> None:
        self.confirm_btn.hide()
        self.progress.show()
        self.progress_meta.show()
        self.log_view.show()

    def update_log(self, text: str) -> None:
        if text:
            self.log_view.setPlainText(text)
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def update_progress(self, percent: int, speed: str, eta: str) -> None:
        self.progress.setValue(max(0, min(100, int(percent))))
        parts = []
        if speed:
            parts.append(f"速度: {speed}")
        if eta:
            parts.append(f"ETA: {eta}")
        self.progress_meta.setText(" · ".join(parts))

    def show_result(self, success: bool, message: str) -> None:
        self.progress_meta.setText(message)
        self.close_btn.show()
        self.cancel_btn.hide()
        self.confirm_btn.hide()
        if success:
            self.progress.setValue(100)


class DatabaseStatusWorker(QObject):
    status_checked = pyqtSignal(str, object)
    all_done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, database_service: DatabaseService, ssh_run_fn, db_root: str):
        super().__init__()
        self._database_service = database_service
        self._ssh_run_fn = ssh_run_fn
        self._db_root = db_root
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            for info in self._database_service.list_all():
                if self._cancelled:
                    return
                result = self._database_service.check_status(self._ssh_run_fn, info.db_id, self._db_root)
                self.status_checked.emit(info.db_id, result)
            self.all_done.emit()
        except Exception as exc:  # pragma: no cover - UI worker safety
            self.error.emit(str(exc))


class DatabaseInstallMonitor(QObject):
    progress_updated = pyqtSignal(str, int, str, str)
    log_updated = pyqtSignal(str, str)
    install_finished = pyqtSignal(str, bool, str)

    def __init__(
        self,
        database_service: DatabaseService,
        ssh_run_fn,
        db_id: str,
        task_dir: str,
        db_root: str,
    ):
        super().__init__()
        self._database_service = database_service
        self._ssh_run_fn = ssh_run_fn
        self._db_id = db_id
        self._task_dir = task_dir
        self._db_root = db_root
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            while not self._cancelled:
                status = self._database_service.check_install_status(self._ssh_run_fn, self._task_dir)
                log_text = self._database_service.read_install_log(self._ssh_run_fn, self._task_dir, tail=80)
                self.log_updated.emit(self._db_id, log_text)
                progress = self._database_service.parse_progress(log_text)
                self.progress_updated.emit(
                    self._db_id,
                    int(progress.get("percent", 0)),
                    str(progress.get("speed", "")),
                    str(progress.get("eta", "")),
                )

                state = str(status.get("status", ""))
                if state == "DONE":
                    verify = self._database_service.verify_integrity(self._ssh_run_fn, self._db_id, self._db_root)
                    ok = verify.status == DatabaseStatus.READY
                    self.install_finished.emit(self._db_id, ok, verify.message or ("安装完成" if ok else "完整性校验失败"))
                    return
                if state == "FAILED":
                    self.install_finished.emit(self._db_id, False, "安装失败")
                    return
                time.sleep(2)
        except Exception as exc:  # pragma: no cover - UI worker safety
            self.install_finished.emit(self._db_id, False, str(exc))
