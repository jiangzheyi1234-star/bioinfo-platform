"""输入数据选择器 — 展示可用输入数据并支持选择

按 recommended_input_from 排序，每个条目显示文件名、来源工具、创建时间。
单选模式，选择后通过信号通知。
"""
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

from core.data_registry import DataItem, DataRegistry
from ui.widgets import styles

logger = logging.getLogger(__name__)


class _DataItemRow(QFrame):
    """单个数据项行"""

    clicked = pyqtSignal(str)  # data_id

    def __init__(self, item: DataItem, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._data_id = item.data_id
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)
        self._build_ui(item)
        self._update_style()

    def _build_ui(self, item: DataItem) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # 文件名
        filename = item.file_path.rsplit("/", 1)[-1] if "/" in item.file_path else item.file_path
        name_label = QLabel(filename)
        name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {styles.COLOR_TEXT_DEFAULT}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(name_label, stretch=1)

        # 来源标签
        if item.produced_by:
            source_text = f"来自 {item.produced_by[:8]}..."
        else:
            source_text = "原始上传"
        source_label = QLabel(source_text)
        source_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT}; "
            f"background: {styles.COLOR_BG_BLANK}; padding: 2px 6px; "
            f"border: 1px solid {styles.COLOR_BORDER}; border-radius: 3px;"
        )
        layout.addWidget(source_label)

        # 创建时间
        created = time.strftime("%m-%d %H:%M", time.localtime(item.created_at))
        time_label = QLabel(created)
        time_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_MUTED}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(time_label)

    def set_selected(self, selected: bool) -> None:
        """设置选中状态"""
        self._selected = selected
        self._update_style()

    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_SIDEBAR_SELECTED}; "
                f"border: 1px solid {styles.COLOR_PRIMARY}; "
                f"border-radius: {styles.RADIUS_CTRL}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_CARD}; "
                f"border: 1px solid {styles.COLOR_BORDER}; "
                f"border-radius: {styles.RADIUS_CTRL}; }}"
                f"QFrame:hover {{ border-color: {styles.COLOR_PRIMARY_HOVER}; }}"
            )

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._data_id)
        super().mousePressEvent(event)


class InputDataSelector(QFrame):
    """输入数据选择器

    显示当前样本可用的输入数据列表，支持按推荐来源排序。
    单选模式，选择即确认。

    Signals:
        data_selected(str): 用户选中数据项，参数为 data_id
    """

    data_selected = pyqtSignal(str)  # data_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("InputDataSelector")
        self.setStyleSheet(styles.CARD_FRAME("InputDataSelector"))

        self._rows: list[_DataItemRow] = []
        self._selected_id: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 标题
        title = QLabel("选择输入数据")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 提示
        self._hint_label = QLabel("请先选择样本和数据类型")
        self._hint_label.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self._hint_label)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setMaximumHeight(250)

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
        """加载可选数据列表

        Args:
            registry: 数据注册表
            sample_id: 样本 ID
            data_type: 需要的数据类型 (fastq / fasta / ...)
            recommended_from: 推荐来源工具 ID 列表，用于排序
        """
        self._clear_list()
        self._selected_id = None

        items = registry.find_compatible(sample_id, data_type)

        if not items:
            self._hint_label.setText("没有可用的数据")
            self._hint_label.show()
            return

        # 按推荐来源排序
        if recommended_from:
            items = self._sort_by_recommendation(items, recommended_from)

        self._hint_label.hide()

        for item in items:
            row = _DataItemRow(item)
            row.clicked.connect(self._on_row_clicked)
            self._rows.append(row)
            self._list_layout.addWidget(row)

        self._list_layout.addStretch()

    @property
    def selected_data_id(self) -> Optional[str]:
        """当前选中的数据 ID"""
        return self._selected_id

    def _on_row_clicked(self, data_id: str) -> None:
        """处理行点击事件"""
        self._selected_id = data_id

        # 更新选中状态
        for row in self._rows:
            row.set_selected(row._data_id == data_id)

        self.data_selected.emit(data_id)

    def _clear_list(self) -> None:
        """清空列表"""
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()

        # 清除 stretch
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._hint_label.setText("请先选择样本和数据类型")
        self._hint_label.show()

    @staticmethod
    def _sort_by_recommendation(
        items: list[DataItem],
        recommended_from: list[str],
    ) -> list[DataItem]:
        """按推荐来源排序

        推荐来源靠前的排前面，其他的排后面。

        Args:
            items: 数据项列表
            recommended_from: 推荐来源工具 ID 列表（越靠前优先级越高）

        Returns:
            排序后的数据项列表
        """

        def sort_key(item: DataItem) -> tuple[int, float]:
            if item.produced_by:
                # 检查 produced_by（execution_id）是否包含推荐工具的标识
                for idx, tool_id in enumerate(recommended_from):
                    if tool_id in (item.produced_by or ""):
                        return (idx, -item.created_at)
                # 有来源但不在推荐列表中
                return (len(recommended_from), -item.created_at)
            else:
                # 原始上传排最后
                return (len(recommended_from) + 1, -item.created_at)

        return sorted(items, key=sort_key)
