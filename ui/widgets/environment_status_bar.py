"""环境状态栏 — 底部显示 SSH、任务队列等状态信息

通过颜色指示器（绿/黄/红）直观展示各项状态。
"""
import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)


class _StatusDot(QLabel):
    """状态圆点指示器"""

    _COLORS = {
        "green": styles.COLOR_SUCCESS,
        "yellow": styles.COLOR_WARNING,
        "red": styles.COLOR_DANGER,
        "gray": styles.COLOR_TEXT_MUTED,
    }

    def __init__(self, color: str = "gray", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        """设置圆点颜色 ('green' | 'yellow' | 'red' | 'gray')"""
        hex_color = self._COLORS.get(color, self._COLORS["gray"])
        self.setStyleSheet(
            f"background-color: {hex_color}; border-radius: 5px; border: none;"
        )


class EnvironmentStatusBar(QFrame):
    """环境状态栏

    底部横向排列，显示：
    - SSH 连接状态
    - 当前项目名称
    - 运行中/排队中任务数量

    使用颜色指示器: 绿=正常, 黄=警告/重连, 红=断开/错误
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("EnvironmentStatusBar")
        self.setFixedHeight(32)
        self.setStyleSheet(f"""
            QFrame#EnvironmentStatusBar {{
                background-color: {styles.COLOR_BG_CARD};
                border-top: 1px solid {styles.COLOR_BORDER};
                padding: 0 12px;
            }}
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)

        label_style = (
            f"font-size: 11px; color: {styles.COLOR_TEXT_SUB}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )

        # SSH 状态
        self._ssh_dot = _StatusDot("gray")
        self._ssh_label = QLabel("SSH: 未连接")
        self._ssh_label.setStyleSheet(label_style)
        layout.addWidget(self._ssh_dot)
        layout.addWidget(self._ssh_label)

        # 分隔
        sep1 = QLabel("|")
        sep1.setStyleSheet(
            f"color: {styles.COLOR_BORDER}; font-size: 11px; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(sep1)

        # 项目状态
        self._project_label = QLabel("项目: 无")
        self._project_label.setStyleSheet(label_style)
        layout.addWidget(self._project_label)

        # 分隔
        sep2 = QLabel("|")
        sep2.setStyleSheet(
            f"color: {styles.COLOR_BORDER}; font-size: 11px; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(sep2)

        # 任务队列状态
        self._queue_dot = _StatusDot("gray")
        self._queue_label = QLabel("任务: 空闲")
        self._queue_label.setStyleSheet(label_style)
        layout.addWidget(self._queue_dot)
        layout.addWidget(self._queue_label)

        # 分隔符
        sep_log = QLabel("|")
        sep_log.setStyleSheet(
            f"color: {styles.COLOR_BORDER}; font-size: 11px; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(sep_log)

        # 日志状态
        self._log_label = QLabel("日志: 就绪")
        self._log_label.setStyleSheet(label_style)
        layout.addWidget(self._log_label)

        # 分隔
        sep3 = QLabel("|")
        sep3.setStyleSheet(
            f"color: {styles.COLOR_BORDER}; font-size: 11px; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        layout.addWidget(sep3)

        # 磁盘用量
        self._disk_label = QLabel("磁盘: —")
        self._disk_label.setStyleSheet(label_style)
        layout.addWidget(self._disk_label)

        layout.addStretch()

    # ── 公开更新方法 ──────────────────────────────────────────────

    def update_ssh_status(self, connected: bool, reconnecting: bool = False) -> None:
        """更新 SSH 连接状态

        Args:
            connected: 是否已连接
            reconnecting: 是否正在重连
        """
        if connected:
            self._ssh_dot.set_color("green")
            self._ssh_label.setText("SSH: 已连接")
        elif reconnecting:
            self._ssh_dot.set_color("yellow")
            self._ssh_label.setText("SSH: 重连中...")
        else:
            self._ssh_dot.set_color("red")
            self._ssh_label.setText("SSH: 未连接")

    def update_project(self, project_name: Optional[str]) -> None:
        """更新当前项目名称

        Args:
            project_name: 项目名称，None 表示无项目
        """
        if project_name:
            self._project_label.setText(f"项目: {project_name}")
        else:
            self._project_label.setText("项目: 无")

    def update_disk_usage(self, used_gb: float, total_gb: float, percent: float) -> None:
        """更新磁盘用量显示

        Args:
            used_gb: 已用空间 (GB)
            total_gb: 总空间 (GB)
            percent: 使用率 0.0~1.0
        """
        pct = int(percent * 100)
        self._disk_label.setText(f"磁盘: {used_gb:.1f}/{total_gb:.1f}G ({pct}%)")
        # 超过 85% 变黄，超过 95% 变红
        if percent >= 0.95:
            color = styles.COLOR_DANGER
        elif percent >= 0.85:
            color = styles.COLOR_WARNING
        else:
            color = styles.COLOR_TEXT_SUB
        self._disk_label.setStyleSheet(
            f"font-size: 11px; color: {color}; background: {styles.COLOR_BG_BLANK};"
        )

    def update_queue_status(self, running: int, pending: int) -> None:
        """更新任务队列状态

        Args:
            running: 运行中任务数
            pending: 排队中任务数
        """
        if running == 0 and pending == 0:
            self._queue_dot.set_color("gray")
            self._queue_label.setText("任务: 空闲")
        elif pending > 0:
            self._queue_dot.set_color("yellow")
            self._queue_label.setText(f"任务: {running} 运行 / {pending} 排队")
        else:
            self._queue_dot.set_color("green")
            self._queue_label.setText(f"任务: {running} 运行中")

    def update_log_status(self, status_text: str) -> None:
        """更新日志面板状态提示。"""
        text = str(status_text or "").strip() or "日志: 就绪"
        self._log_label.setText(text)
