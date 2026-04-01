from __future__ import annotations

import posixpath
from typing import Callable

import qtawesome as qta
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ui.widgets.styles import BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT_LINEEDIT

_POPOVER_PANEL_STYLE = """
    QFrame#popoverPanel {{
        background-color: #FFFFFF;
        border: 1px solid #D1D5DB;
        border-radius: 10px;
    }}
"""

_POPOVER_LIST_STYLE = """
    QListWidget {
        border: 1px solid #E5E7EB;
        border-radius: 6px;
        background: #FFFFFF;
        outline: none;
        font-size: 13px;
    }
    QListWidget::item {
        height: 30px;
        padding: 2px 8px;
        color: #111827;
    }
    QListWidget::item:hover {
        background: #F3F4F6;
    }
    QListWidget::item:selected {
        background: #E5E7EB;
        color: #111827;
    }
"""

_BROWSE_BTN_STYLE = """
    QPushButton {
        background: #FFFFFF;
        color: #374151;
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 0px 10px;
        font-size: 13px;
        min-width: 36px;
        min-height: 36px;
    }
    QPushButton:hover {
        background: #F9FAFB;
        border-color: #9CA3AF;
    }
    QPushButton:pressed {
        background: #F3F4F6;
    }
"""

_POPOVER_TITLE_STYLE = "font-size: 13px; font-weight: 600; color: #111827; background: transparent;"
_POPOVER_DIVIDER_STYLE = "background: #E5E7EB; max-height: 1px; border: none;"


def _make_popover_panel(parent=None) -> QFrame:
    """shadcn/ui Popover 标准面板：纯白 + 中性灰边框 + 轻阴影。"""
    panel = QFrame(parent)
    panel.setObjectName("popoverPanel")
    panel.setStyleSheet(_POPOVER_PANEL_STYLE)
    shadow = QGraphicsDropShadowEffect(panel)
    shadow.setBlurRadius(16)
    shadow.setColor(QColor(0, 0, 0, 40))
    shadow.setOffset(0, 4)
    panel.setGraphicsEffect(shadow)
    return panel


class _AsyncTaskWorker(QObject):
    """Run a callable inside QThread and emit result to UI thread."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task_fn: Callable[[], object]):
        super().__init__()
        self._task_fn = task_fn

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self._task_fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class RemoteDirectoryPickerDialog(QDialog):
    """VS Code 风格远程目录浏览弹窗。"""

    def __init__(self, start_path: str, list_dirs_fn, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(500, 400)
        self._list_dirs_fn = list_dirs_fn
        self._loading = False
        self.selected_path = ""
        self._current_path = ""
        self._build_ui()
        self._load_path(start_path or "~")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        panel = _make_popover_panel()
        root.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("选择目录")
        title.setStyleSheet(_POPOVER_TITLE_STYLE)
        layout.addWidget(title)

        div = QFrame()
        div.setStyleSheet(_POPOVER_DIVIDER_STYLE)
        layout.addWidget(div)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        self.up_btn = QPushButton("↑ 上级")
        self.up_btn.setStyleSheet(_BROWSE_BTN_STYLE)
        self.up_btn.clicked.connect(self._go_parent)
        self.path_label = QLabel()
        self.path_label.setStyleSheet("font-size: 12px; color: #6B7280; background: transparent;")
        self.path_label.setWordWrap(False)
        nav.addWidget(self.up_btn)
        nav.addWidget(self.path_label, stretch=1)
        layout.addLayout(nav)

        self.dir_list = QListWidget()
        self.dir_list.setStyleSheet(_POPOVER_LIST_STYLE)
        self.dir_list.itemClicked.connect(self._open_child)
        self.dir_list.itemDoubleClicked.connect(self._open_child)
        self.dir_list.itemActivated.connect(self._open_child)
        self.dir_list.currentItemChanged.connect(self._on_item_selected)
        layout.addWidget(self.dir_list, stretch=1)

        self.selected_label = QLabel("选择: ")
        self.selected_label.setStyleSheet("font-size: 12px; color: #6B7280; background: transparent;")
        layout.addWidget(self.selected_label)

        div2 = QFrame()
        div2.setStyleSheet(_POPOVER_DIVIDER_STYLE)
        layout.addWidget(div2)

        foot = QHBoxLayout()
        foot.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        select_btn = QPushButton("选择此目录")
        select_btn.setStyleSheet(BUTTON_PRIMARY)
        select_btn.clicked.connect(self._accept_selected)
        foot.addWidget(cancel_btn)
        foot.addWidget(select_btn)
        layout.addLayout(foot)

    def _load_path(self, raw_path: str) -> None:
        if self._loading:
            return
        self._loading = True
        self.up_btn.setEnabled(False)
        self.dir_list.setEnabled(False)
        self.selected_label.setText("选择: 读取目录中...")

        def _on_done(ok: bool, resolved: str, dirs: list[str], message: str) -> None:
            self._loading = False
            self.up_btn.setEnabled(True)
            self.dir_list.setEnabled(True)
            if not ok:
                self.selected_label.setText(f"选择: {self.selected_path or self._current_path or '--'}")
                QMessageBox.warning(self, "目录浏览", message)
                return
            self._current_path = resolved
            self.selected_path = resolved
            self.path_label.setText(resolved)
            self.selected_label.setText(f"选择: {resolved}")
            self.dir_list.clear()
            for name in dirs:
                item = QListWidgetItem(qta.icon("ph.folder", color="#9CA3AF"), name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.dir_list.addItem(item)

        self._list_dirs_fn(raw_path, _on_done)

    def popup_at(self, anchor) -> None:
        if anchor is None:
            return
        pop_w = self.sizeHint().width() or 500
        x = anchor.mapToGlobal(QPoint(0, 0)).x() + anchor.width() - pop_w - 16
        y = anchor.mapToGlobal(QPoint(0, anchor.height() + 6)).y()
        screen = QApplication.screenAt(anchor.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - pop_w))
        self.move(QPoint(x, y))

    def _go_parent(self) -> None:
        if self._loading or not self._current_path:
            return
        parent = posixpath.dirname(self._current_path.rstrip("/")) or "/"
        self._load_path(parent)

    def _open_child(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
        if not name:
            return
        self._load_path(posixpath.join(self._current_path, name))

    def _on_item_selected(self, current: QListWidgetItem, _prev) -> None:
        if current is None:
            self.selected_path = self._current_path
        else:
            name = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
            self.selected_path = posixpath.join(self._current_path, name) if name else self._current_path
        self.selected_label.setText(f"选择: {self.selected_path}")

    def _accept_selected(self) -> None:
        self.selected_path = self.selected_path or self._current_path
        if not self.selected_path:
            QMessageBox.warning(self, "目录浏览", "请选择有效目录。")
            return
        self.accept()


class DatabaseSettingsDialog(QDialog):
    """shadcn/ui Popover 风格的数据库根目录设置弹窗。"""

    def __init__(self, initial_path: str, info_fn, browse_fn, save_fn, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(360)
        self._info_fn = info_fn
        self._browse_fn = browse_fn
        self._save_fn = save_fn
        self._build_ui()
        self.path_edit.setText(initial_path)
        self._set_busy(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        panel = _make_popover_panel()
        root.addWidget(panel)

        content = QVBoxLayout(panel)
        content.setContentsMargins(14, 14, 14, 14)
        content.setSpacing(10)

        title = QLabel("数据库根目录")
        title.setStyleSheet(_POPOVER_TITLE_STYLE)
        content.addWidget(title)

        div = QFrame()
        div.setStyleSheet(_POPOVER_DIVIDER_STYLE)
        content.addWidget(div)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.path_edit = QLineEdit()
        self.path_edit.setStyleSheet(INPUT_LINEEDIT)
        self.path_edit.setPlaceholderText("~/databases")
        self.browse_btn = QPushButton("…")
        self.browse_btn.setStyleSheet(_BROWSE_BTN_STYLE)
        self.browse_btn.setFixedSize(36, 36)
        self.browse_btn.setToolTip("浏览远程目录")
        self.browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self.path_edit, stretch=1)
        row.addWidget(self.browse_btn)
        content.addLayout(row)

        foot = QHBoxLayout()
        foot.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(BUTTON_PRIMARY)
        save_btn.clicked.connect(self._on_save)
        self._save_btn = save_btn
        self._cancel_btn = cancel_btn
        foot.addWidget(cancel_btn)
        foot.addWidget(save_btn)
        content.addLayout(foot)

    def _on_browse(self) -> None:
        selected = self._browse_fn(self.path_edit.text().strip(), self.browse_btn)
        if selected:
            self.path_edit.setText(selected)

    def _on_save(self) -> None:
        self._set_busy(True)

        def _on_done(success: bool) -> None:
            self._set_busy(False)
            if success:
                self.accept()

        started = self._save_fn(self.path_edit.text().strip(), _on_done)
        if not started:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.path_edit.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(not busy)
        self._save_btn.setEnabled(not busy)
        self._save_btn.setText("处理中..." if busy else "保存")

    def popup_at(self, anchor) -> None:
        if anchor is None:
            return
        pop_w = self.sizeHint().width() or 360
        anchor_tl = anchor.mapToGlobal(QPoint(0, 0))
        x = anchor_tl.x() - pop_w - 8
        y = anchor_tl.y() + anchor.height() + 6
        screen = QApplication.screenAt(anchor_tl) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - pop_w))
        self.move(QPoint(x, y))
