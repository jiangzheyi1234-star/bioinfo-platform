"""阶段状态小组件 — 显示流水线单阶段的图标 + 名称 + 状态。

用于 AnalysisPage 的流水线配置区，每个阶段一个 widget。
"""
import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)

# 状态定义
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_STATUS_TEXT = {
    STATUS_PENDING: "等待中",
    STATUS_RUNNING: "运行中...",
    STATUS_COMPLETED: "已完成",
    STATUS_FAILED: "失败",
}

_STATUS_COLORS = {
    STATUS_PENDING: styles.COLOR_TEXT_MUTED,
    STATUS_RUNNING: styles.COLOR_PRIMARY,
    STATUS_COMPLETED: styles.COLOR_SUCCESS,
    STATUS_FAILED: styles.COLOR_DANGER,
}

_DOT_COLORS = {
    STATUS_PENDING: styles.COLOR_TEXT_MUTED,
    STATUS_RUNNING: styles.COLOR_PRIMARY,
    STATUS_COMPLETED: styles.COLOR_SUCCESS,
    STATUS_FAILED: styles.COLOR_DANGER,
}


class StageStatusWidget(QFrame):
    """流水线阶段状态组件

    布局: [状态圆点] [工具名称]  [状态文字]
    """

    def __init__(
        self,
        tool_id: str,
        tool_name: str,
        stage_index: int,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._tool_id = tool_id
        self._stage_index = stage_index
        self._status = STATUS_PENDING
        self.setObjectName(f"StageStatus_{tool_id}")
        self._build_ui(tool_name)
        self._update_display()

    def _build_ui(self, tool_name: str) -> None:
        self.setFixedHeight(44)
        self.setStyleSheet(
            f"QFrame {{ background-color: {styles.COLOR_BG_CARD}; "
            f"border: 1px solid {styles.COLOR_BORDER}; "
            f"border-radius: {styles.RADIUS_CTRL}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # 状态圆点
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        layout.addWidget(self._dot)

        # 阶段编号 + 工具名称
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)

        self._name_label = QLabel(f"阶段 {self._stage_index + 1}: {tool_name}")
        self._name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {styles.COLOR_TEXT_DEFAULT}; "
            f"background: {styles.COLOR_BG_BLANK}; border: none;"
        )
        info_layout.addWidget(self._name_label)

        layout.addLayout(info_layout, stretch=1)

        # 状态文字
        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            f"font-size: 11px; background: {styles.COLOR_BG_BLANK}; border: none;"
        )
        layout.addWidget(self._status_label)

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        """更新阶段状态"""
        if status not in _STATUS_TEXT:
            return
        self._status = status
        self._update_display()

    def _update_display(self) -> None:
        """刷新显示"""
        color = _STATUS_COLORS.get(self._status, styles.COLOR_TEXT_MUTED)
        dot_color = _DOT_COLORS.get(self._status, styles.COLOR_TEXT_MUTED)

        self._dot.setStyleSheet(
            f"background-color: {dot_color}; border-radius: 5px; border: none;"
        )
        self._status_label.setText(_STATUS_TEXT.get(self._status, ""))
        self._status_label.setStyleSheet(
            f"font-size: 11px; color: {color}; background: {styles.COLOR_BG_BLANK}; "
            f"border: none;"
        )

        # 运行中阶段高亮边框
        if self._status == STATUS_RUNNING:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_CARD}; "
                f"border: 1px solid {styles.COLOR_PRIMARY}; "
                f"border-radius: {styles.RADIUS_CTRL}; }}"
            )
        elif self._status == STATUS_FAILED:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_CARD}; "
                f"border: 1px solid {styles.COLOR_DANGER}; "
                f"border-radius: {styles.RADIUS_CTRL}; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame {{ background-color: {styles.COLOR_BG_CARD}; "
                f"border: 1px solid {styles.COLOR_BORDER}; "
                f"border-radius: {styles.RADIUS_CTRL}; }}"
            )
