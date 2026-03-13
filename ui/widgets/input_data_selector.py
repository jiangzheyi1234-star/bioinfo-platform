"""输入数据选择器：展示可用输入数据并支持推荐来源排序。"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.data.data_registry import DataItem, DataRegistry
from ui.widgets import styles

logger = logging.getLogger(__name__)


class _DataItemRow(QFrame):
    """单条数据行。"""

    clicked = pyqtSignal(str)

    def __init__(self, item: DataItem, tool_name: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._data_id = item.data_id
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        self._build_ui(item, tool_name)
        self._update_style()

    def _build_ui(self, item: DataItem, tool_name: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        filename = item.file_path.rsplit("/", 1)[-1] if "/" in item.file_path else item.file_path
        name_label = QLabel(filename)
        name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {styles.COLOR_TEXT_DEFAULT};"
            f" background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(name_label, stretch=1)

        source_text = "原始上传"
        if item.produced_by:
            source_text = f"来自 {tool_name or item.produced_by[:8]}"

        source_label = QLabel(source_text)
        source_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT};"
            f" background: {styles.COLOR_BG_BLANK}; padding: 2px 6px;"
            f" border: 1px solid {styles.COLOR_BORDER}; border-radius: 3px;"
        )
        layout.addWidget(source_label)

        created = time.strftime("%m-%d %H:%M", time.localtime(item.created_at))
        time_label = QLabel(created)
        time_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_MUTED};"
            f" background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(time_label)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_SIDEBAR_SELECTED};"
                f" border: 1px solid {styles.COLOR_PRIMARY};"
                f" border-radius: {styles.RADIUS_CTRL}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_CARD};"
                f" border: 1px solid {styles.COLOR_BORDER};"
                f" border-radius: {styles.RADIUS_CTRL}; }}"
                f"QFrame:hover {{ border-color: {styles.COLOR_PRIMARY_HOVER}; }}"
            )

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._data_id)
        super().mousePressEvent(event)


class InputDataSelector(QFrame):
    """输入数据选择器（单选）。"""

    data_selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("InputDataSelector")
        self.setStyleSheet(styles.CARD_FRAME("InputDataSelector"))

        self._rows: list[_DataItemRow] = []
        self._selected_id: Optional[str] = None
        self._tool_name_map: dict[str, str] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("选择输入数据")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        self._hint_label = QLabel("请先选择样本和数据类型")
        self._hint_label.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self._hint_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setMaximumHeight(260)

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background-color: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)

        scroll.setWidget(self._list_container)
        layout.addWidget(scroll)

    def load_data(
        self,
        registry: DataRegistry,
        sample_id: str,
        data_type: str,
        recommended_from: Optional[list[str]] = None,
    ) -> None:
        """加载当前样本可用输入数据。"""
        self._clear_list()
        self._selected_id = None

        items = registry.find_compatible(sample_id, data_type)
        if not items:
            self._hint_label.setText("没有可用的数据")
            self._hint_label.show()
            return

        if recommended_from:
            items, self._tool_name_map = self._sort_by_recommendation(items, recommended_from, registry)

        self._hint_label.hide()

        for item in items:
            tool_name = self._tool_name_map.get(item.produced_by or "", "")
            row = _DataItemRow(item, tool_name=tool_name)
            row.clicked.connect(self._on_row_clicked)
            self._rows.append(row)
            self._list_layout.addWidget(row)

        self._list_layout.addStretch()

    @property
    def selected_data_id(self) -> Optional[str]:
        return self._selected_id

    def _on_row_clicked(self, data_id: str) -> None:
        self._selected_id = data_id
        for row in self._rows:
            row.set_selected(row._data_id == data_id)
        self.data_selected.emit(data_id)

    def _clear_list(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._hint_label.setText("请先选择样本和数据类型")
        self._hint_label.show()

    @staticmethod
    def _load_execution_tool_map(registry: DataRegistry, execution_ids: list[str]) -> dict[str, str]:
        if not execution_ids:
            return {}

        conn = getattr(registry, "_conn", None)
        if conn is None:
            return {}

        placeholders = ",".join(["?"] * len(execution_ids))
        sql = f"SELECT execution_id, tool_id FROM executions WHERE execution_id IN ({placeholders})"

        try:
            rows = conn.execute(sql, execution_ids).fetchall()
            return {str(row["execution_id"]): str(row["tool_id"] or "") for row in rows}
        except Exception:
            logger.exception("读取 execution -> tool_id 映射失败")
            return {}

    @classmethod
    def _sort_by_recommendation(
        cls,
        items: list[DataItem],
        recommended_from: list[str],
        registry: DataRegistry,
    ) -> tuple[list[DataItem], dict[str, str]]:
        """按 recommended_input_from 优先级排序。"""
        execution_ids = [item.produced_by for item in items if item.produced_by]
        exec_tool_map = cls._load_execution_tool_map(registry, [eid for eid in execution_ids if eid])

        def source_rank(item: DataItem) -> int:
            if not item.produced_by:
                return len(recommended_from) + 1

            tool_id = exec_tool_map.get(item.produced_by, "")
            if tool_id in recommended_from:
                return recommended_from.index(tool_id)

            return len(recommended_from)

        sorted_items = sorted(items, key=lambda i: (source_rank(i), -i.created_at))
        return sorted_items, exec_tool_map
