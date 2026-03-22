"""项目选择器组件 — Windsurf 风格底部按钮 + 向上弹出菜单。"""

import logging
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles

if TYPE_CHECKING:
    from core.data.project_manager import ProjectManager

logger = logging.getLogger(__name__)

_PROJECT_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none">
  <circle cx="4" cy="5" r="1.5" fill="#475569"/>
  <circle cx="4" cy="9" r="1.5" fill="#475569"/>
  <circle cx="4" cy="13" r="1.5" fill="#475569"/>
  <rect x="7" y="4.5" width="8" height="1.5" rx="0.75" fill="#475569"/>
  <rect x="7" y="8.25" width="8" height="1.5" rx="0.75" fill="#475569"/>
  <rect x="7" y="12" width="8" height="1.5" rx="0.75" fill="#475569"/>
</svg>"""

_MAX_VISIBLE_ITEMS = 8
_ITEM_HEIGHT = 36


def _svg_to_icon(svg: str, size: int = 18) -> QIcon:
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtSvg import QSvgRenderer

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class ProjectSelectorButton(QPushButton):
    """底部项目选择按钮：图标 + 项目名。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._project_name = ""
        self._is_empty = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(styles.PROJECT_SELECTOR_BUTTON_EMPTY)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(44)
        self._update_display()

    def set_project_name(self, name: str) -> None:
        self._project_name = name or ""
        self._is_empty = False
        self.setStyleSheet(styles.PROJECT_SELECTOR_BUTTON)
        self._update_display()

    def set_empty_state(self) -> None:
        self._project_name = ""
        self._is_empty = True
        self.setStyleSheet(styles.PROJECT_SELECTOR_BUTTON_EMPTY)
        self._update_display()

    def _update_display(self) -> None:
        icon = _svg_to_icon(_PROJECT_ICON_SVG, 18)
        self.setIcon(icon)
        self.setIconSize(QSize(18, 18))
        if self._is_empty:
            self.setText("  + 新建项目")
        else:
            self.setText(f"  {self._project_name}")


class ProjectSelectorMenu(QWidget):
    """向上弹出的项目选择菜单。"""

    project_selected = pyqtSignal(str)
    create_project_requested = pyqtSignal()
    delete_project_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_project_id: Optional[str] = None
        self._projects: list = []
        self._setup_window_flags()
        self._setup_ui()

    def _setup_window_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.Popup 
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _setup_ui(self) -> None:
        self.setMinimumWidth(200)
        self.setMaximumWidth(200)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(0)

        self._panel = QFrame()
        self._panel.setObjectName("menuPanel")
        self._panel.setStyleSheet("""
            QFrame#menuPanel {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
            }
        """)
        
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        shadow = QGraphicsDropShadowEffect(self._panel)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 4)
        self._panel.setGraphicsEffect(shadow)
        
        main_layout.addWidget(self._panel)

        content_layout = QVBoxLayout(self._panel)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索项目...")
        self._search_input.setStyleSheet(styles.PROJECT_MENU_SEARCH)
        self._search_input.textChanged.connect(self._filter_projects)
        self._search_input.setVisible(False)
        content_layout.addWidget(self._search_input)

        self._project_list = QListWidget()
        self._project_list.setStyleSheet(styles.PROJECT_MENU_LIST)
        self._project_list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel
        )
        self._project_list.itemClicked.connect(self._on_item_clicked)
        content_layout.addWidget(self._project_list)

        self._create_btn = QPushButton("+ 新建项目")
        self._create_btn.setStyleSheet(styles.PROJECT_MENU_BUTTON)
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.clicked.connect(self._on_create_clicked)
        content_layout.addWidget(self._create_btn)

        self._delete_btn = QPushButton("🗑 删除项目...")
        self._delete_btn.setStyleSheet(styles.PROJECT_MENU_BUTTON_DANGER)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        content_layout.addWidget(self._delete_btn)

    def refresh_projects(self, pm: "ProjectManager") -> None:
        self._current_project_id = (
            pm.current_project.project_id if pm.current_project else None
        )
        self._projects = [
            p for p in pm.list_projects(sort_by="last_opened") if p.status == "active"
        ]

        show_search = len(self._projects) > 5
        self._search_input.setVisible(show_search)
        self._search_input.clear()

        self._populate_list()

        has_deletable = len(self._projects) > 1 and self._current_project_id is not None
        self._delete_btn.setVisible(has_deletable)

        item_count = self._project_list.count()
        if item_count > 0:
            list_height = min(item_count, _MAX_VISIBLE_ITEMS) * _ITEM_HEIGHT
            self._project_list.setFixedHeight(list_height)

    def _populate_list(self, filter_text: str = "") -> None:
        self._project_list.clear()
        filter_lower = filter_text.lower()

        for proj in self._projects:
            if filter_lower and filter_lower not in proj.name.lower():
                continue

            item = QListWidgetItem()
            is_current = proj.project_id == self._current_project_id

            if is_current:
                item.setText(f"✓ {proj.name}")
            else:
                item.setText(f"    {proj.name}")

            item.setData(Qt.ItemDataRole.UserRole, proj.project_id)
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            self._project_list.addItem(item)

    def _filter_projects(self, text: str) -> None:
        self._populate_list(text)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id and project_id != self._current_project_id:
            self.project_selected.emit(project_id)
        self.hide()

    def _on_create_clicked(self) -> None:
        self.create_project_requested.emit()
        self.hide()

    def _on_delete_clicked(self) -> None:
        self.delete_project_requested.emit()
        self.hide()

    def show_at(self, button: QPushButton) -> None:
        self.adjustSize()
        global_pos = button.mapToGlobal(QPoint(8, -self.height() + 12))
        self.move(global_pos)
        self.show()
        self._search_input.setFocus()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().event(event)