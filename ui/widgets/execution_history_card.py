"""执行历史卡片 — 基于 SQLite executions 表的执行历史展示。

替代 JSON 版 TaskHistoryCard，从项目数据库中读取执行记录。
支持实时刷新、展开详情、按状态过滤。
"""

import json
import logging
import time
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)

# 状态显示映射
_STATUS_DISPLAY = {
    "pending": ("等待中", styles.COLOR_TEXT_MUTED),
    "running": ("运行中", styles.COLOR_PRIMARY),
    "completed": ("已完成", styles.COLOR_SUCCESS),
    "failed": ("失败", styles.COLOR_DANGER),
    "retrying": ("重试中", styles.COLOR_WARNING),
}


class ExecutionHistoryCard(QFrame):
    """执行历史卡片

    从项目 SQLite 数据库的 executions 表读取历史，
    展示 tool_id / status / created_at / triggered_by 等信息。

    收到 ToolEngine.execution_completed/failed 信号时自动刷新。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ExecutionHistoryCard")
        self.setStyleSheet(styles.CARD_FRAME("ExecutionHistoryCard"))
        self._db_conn = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 标题行
        header_row = QHBoxLayout()
        title = QLabel("执行历史")
        title.setStyleSheet(styles.CARD_TITLE)
        header_row.addWidget(title)
        header_row.addStretch()

        self._count_label = QLabel("0 条记录")
        self._count_label.setStyleSheet(styles.LABEL_HINT)
        header_row.addWidget(self._count_label)
        layout.addLayout(header_row)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "工具", "状态", "触发来源", "开始时间", "耗时", "错误信息",
        ])
        self._table.setStyleSheet(styles.TABLE_WIDGET)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)

        # 列宽
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 120)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 80)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 80)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 140)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 80)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._table)

    def set_db_connection(self, conn) -> None:
        """设置数据库连接并刷新

        Args:
            conn: SQLite 连接 (sqlite3.Connection)
        """
        self._db_conn = conn
        self.refresh()

    def refresh(self) -> None:
        """从 executions 表刷新列表"""
        self._table.setRowCount(0)

        if self._db_conn is None:
            self._count_label.setText("未连接数据库")
            return

        try:
            rows = self._db_conn.execute(
                "SELECT execution_id, tool_id, status, triggered_by, "
                "created_at, completed_at, error "
                "FROM executions ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        except Exception as e:
            logger.error("查询执行历史失败: %s", e)
            self._count_label.setText("查询失败")
            return

        self._table.setRowCount(len(rows))
        self._count_label.setText(f"{len(rows)} 条记录")

        for i, row in enumerate(rows):
            # 工具
            tool_item = QTableWidgetItem(row["tool_id"])
            tool_item.setData(Qt.ItemDataRole.UserRole, row["execution_id"])
            self._table.setItem(i, 0, tool_item)

            # 状态
            status = row["status"]
            display_text, color = _STATUS_DISPLAY.get(status, (status, styles.COLOR_TEXT_DEFAULT))
            status_item = QTableWidgetItem(display_text)
            status_item.setForeground(
                Qt.GlobalColor.black  # 默认
            )
            self._table.setItem(i, 1, status_item)

            # 触发来源
            triggered = row["triggered_by"] or "unknown"
            self._table.setItem(i, 2, QTableWidgetItem(triggered))

            # 开始时间
            created = row["created_at"]
            if created:
                time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(created))
            else:
                time_str = "-"
            self._table.setItem(i, 3, QTableWidgetItem(time_str))

            # 耗时
            completed = row["completed_at"]
            if created and completed:
                elapsed = completed - created
                if elapsed < 60:
                    elapsed_str = f"{elapsed:.0f}s"
                elif elapsed < 3600:
                    elapsed_str = f"{elapsed / 60:.1f}m"
                else:
                    elapsed_str = f"{elapsed / 3600:.1f}h"
            elif status == "running":
                elapsed_str = "运行中..."
            else:
                elapsed_str = "-"
            self._table.setItem(i, 4, QTableWidgetItem(elapsed_str))

            # 错误信息
            error = row["error"] or ""
            error_item = QTableWidgetItem(error[:80])
            if error:
                error_item.setToolTip(error)
            self._table.setItem(i, 5, error_item)
