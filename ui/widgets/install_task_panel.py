"""安装任务只读面板。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


_PANEL_STYLE = """
QFrame#installTaskPanel {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 12px;
}
"""

_ROW_STYLE = """
QFrame#taskRow {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
"""

_LOCATE_BTN_STYLE = """
QPushButton {
    background: transparent;
    color: #0284C7;
    border: 1px solid #BAE6FD;
    border-radius: 6px;
    padding: 2px 10px;
    min-height: 26px;
    font-size: 12px;
}
QPushButton:hover {
    background: #F0F9FF;
}
"""


class InstallTaskPanel(QDialog):
    """状态栏安装段点击后展示的任务面板（只读）。"""

    locate_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(430, 320)
        self._tasks: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("installTaskPanel")
        panel.setStyleSheet(_PANEL_STYLE)
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        panel.setGraphicsEffect(shadow)
        root.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("安装任务")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #0F172A; background: transparent;")
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #64748B; border: none; padding: 2px 6px; }"
            "QPushButton:hover { color: #0EA5E9; }"
        )
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        layout.addLayout(header)

        self._empty_label = QLabel("暂无安装任务")
        self._empty_label.setStyleSheet("font-size: 12px; color: #94A3B8; background: transparent;")
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent;")
        self._scroll.setVisible(False)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

    def set_tasks(self, tasks: list[dict]) -> None:
        self._tasks = list(tasks)
        self._render_tasks()

    def popup_at(self, anchor: QWidget) -> None:
        if anchor is None:
            return
        self.adjustSize()
        width = max(self.width(), 430)
        height = max(self.height(), 320)
        self.resize(width, height)
        anchor_tl = anchor.mapToGlobal(QPoint(0, 0))
        x = anchor_tl.x() - width + anchor.width()
        y = anchor_tl.y() - height - 8
        screen = QApplication.screenAt(anchor_tl) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - width))
            y = max(geo.top(), min(y, geo.bottom() - height))
        self.move(QPoint(x, y))
        self.show()

    def _render_tasks(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._tasks:
            self._empty_label.setVisible(True)
            self._scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._scroll.setVisible(True)

        for task in self._tasks:
            row = QFrame()
            row.setObjectName("taskRow")
            row.setStyleSheet(_ROW_STYLE)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)

            title_row = QHBoxLayout()
            state = str(task.get("state", "running") or "running").lower()
            badge = QLabel(self._state_text(state))
            badge.setStyleSheet(
                f"font-size: 11px; color: {self._state_color(state)}; background: transparent; font-weight: 600;"
            )
            title = QLabel(str(task.get("title", task.get("task_id", "")) or "安装任务"))
            title.setStyleSheet("font-size: 13px; color: #0F172A; background: transparent; font-weight: 600;")
            locate_btn = QPushButton("定位")
            locate_btn.setStyleSheet(_LOCATE_BTN_STYLE)
            source = str(task.get("source", "") or "")
            locate_btn.clicked.connect(lambda _=False, src=source: self._on_locate(src))

            title_row.addWidget(badge)
            title_row.addWidget(title, 1)
            title_row.addWidget(locate_btn)
            row_layout.addLayout(title_row)

            detail = str(task.get("detail", "") or "").strip()
            if detail:
                detail_lbl = QLabel(detail)
                detail_lbl.setWordWrap(True)
                detail_lbl.setStyleSheet("font-size: 12px; color: #64748B; background: transparent;")
                row_layout.addWidget(detail_lbl)

            self._content_layout.addWidget(row)

        self._content_layout.addStretch()

    def _on_locate(self, source: str) -> None:
        self.locate_requested.emit(source)
        self.hide()

    @staticmethod
    def _state_text(state: str) -> str:
        if state == "success":
            return "已完成"
        if state == "failed":
            return "失败"
        return "进行中"

    @staticmethod
    def _state_color(state: str) -> str:
        if state == "success":
            return "#10B981"
        if state == "failed":
            return "#EF4444"
        return "#F59E0B"

