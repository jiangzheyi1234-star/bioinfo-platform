"""侧边栏项目切换器 — 下拉式项目选择面板。"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)


class _ProjectItem(QWidget):
    """紧凑项目列表项 — 使用 QWidget 避免 QFrame 样式级联。"""

    clicked = pyqtSignal(str)

    def __init__(self, project_id: str, name: str, is_current: bool, parent=None):
        super().__init__(parent)
        self._project_id = project_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)

        bg = styles.COLOR_SELECTION_BG if is_current else "transparent"
        text_color = styles.COLOR_PRIMARY if is_current else styles.COLOR_TEXT_DEFAULT

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        if is_current:
            check = QLabel("\u2713")
            check.setStyleSheet(f"color: {styles.COLOR_PRIMARY}; font-size: 11px;")
            check.setFixedWidth(14)
            layout.addWidget(check)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color: {text_color}; font-size: 13px; font-weight: 500;")
        layout.addWidget(name_lbl, stretch=1)

        self._bg = bg
        self._hover_bg = styles.COLOR_SELECTION_HOVER

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 6.0, 6.0)
        if self.underMouse():
            painter.fillPath(path, QColor(self._hover_bg) if self._bg == "transparent" else QColor(self._bg))
        elif self._bg != "transparent":
            painter.fillPath(path, QColor(self._bg))
        painter.end()
        super().paintEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._project_id)
        super().mouseReleaseEvent(event)


class _DropdownPanel(QWidget):
    """弹出式项目列表面板。"""

    project_selected = pyqtSignal(str)
    create_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumWidth(200)
        self.setMaximumHeight(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.verticalScrollBar().setStyleSheet(styles.SCROLL_BAR_ELEGANT)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(6, 6, 6, 4)
        self._list_layout.setSpacing(2)
        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll)

        # 分割线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {styles.COLOR_BORDER};")
        layout.addWidget(sep)

        # "+ 新建项目" 行
        create_row = QWidget()
        create_row.setCursor(Qt.CursorShape.PointingHandCursor)
        create_row.setFixedHeight(36)
        cr_layout = QHBoxLayout(create_row)
        cr_layout.setContentsMargins(18, 0, 12, 0)
        cr_lbl = QLabel("+ 新建项目")
        cr_lbl.setStyleSheet(f"color: {styles.COLOR_PRIMARY}; font-size: 13px; font-weight: 600;")
        cr_layout.addWidget(cr_lbl)
        create_row.mouseReleaseEvent = lambda e: (self.create_requested.emit(), self.hide())
        layout.addWidget(create_row)

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0, 8.0, 8.0)
        painter.fillPath(path, QColor(styles.COLOR_BG_CARD))
        painter.setPen(QPen(QColor(styles.COLOR_BORDER), 1.0))
        painter.drawPath(path)
        painter.end()

    def populate(self, projects: list, current_id: str) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for p in projects:
            if p.status != "active":
                continue
            is_current = p.project_id == current_id
            item = _ProjectItem(p.project_id, p.name, is_current, self._list_widget)
            item.clicked.connect(self._on_item_clicked)
            self._list_layout.addWidget(item)

        self._list_layout.addStretch()

    def _on_item_clicked(self, project_id: str):
        self.hide()
        self.project_selected.emit(project_id)


class ProjectSwitcher(QWidget):
    """侧边栏顶部项目切换器。"""

    project_switched = pyqtSignal(str)
    project_create_requested = pyqtSignal()

    def __init__(self, project_manager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pm = project_manager
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)

        self._name_lbl = QLabel("未选择项目")
        self._name_lbl.setStyleSheet(
            f"color: {styles.COLOR_TEXT_TITLE}; font-size: 14px; font-weight: 700;"
        )
        layout.addWidget(self._name_lbl, stretch=1)

        self._arrow = QLabel("\u25bc")
        self._arrow.setStyleSheet(f"color: {styles.COLOR_TEXT_HINT}; font-size: 10px;")
        self._arrow.setFixedWidth(16)
        layout.addWidget(self._arrow)

        self._dropdown = _DropdownPanel()
        self._dropdown.project_selected.connect(self._on_project_selected)
        self._dropdown.create_requested.connect(self.project_create_requested.emit)

        self.refresh()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor
        painter = QPainter(self)
        # 底部分割线
        painter.fillRect(0, self.height() - 1, self.width(), 1, QColor(styles.COLOR_BORDER))
        if self.underMouse():
            painter.fillRect(0, 0, self.width(), self.height() - 1, QColor(styles.COLOR_SELECTION_HOVER))
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def refresh(self) -> None:
        current = self._pm.current_project
        if current:
            name = current.name
            if len(name) > 16:
                name = name[:15] + "\u2026"
            self._name_lbl.setText(name)
        else:
            self._name_lbl.setText("未选择项目")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_dropdown()
        super().mouseReleaseEvent(event)

    def _show_dropdown(self):
        self._pm.reload_index()
        projects = self._pm.list_projects()
        current = self._pm.current_project
        current_id = current.project_id if current else ""
        self._dropdown.populate(projects, current_id)

        pos = self.mapToGlobal(QPoint(0, self.height()))
        self._dropdown.setFixedWidth(max(self.width(), 200))
        self._dropdown.move(pos)
        self._dropdown.show()

    def _on_project_selected(self, project_id: str):
        current = self._pm.current_project
        if current and current.project_id == project_id:
            return
        self.project_switched.emit(project_id)
