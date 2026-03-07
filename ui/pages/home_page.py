"""项目首页 — 样本管理中心。

显示当前项目所有样本的分析进度，支持添加/删除样本、继续分析、查看最近执行。
"""

import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.page_base import BasePage
from ui.widgets import styles

logger = logging.getLogger(__name__)

# read_based 流程阶段（从 analysis_paths.yaml 加载，这里作为后备默认值）
_DEFAULT_STAGES = ["fastp", "hostile", "kraken2"]

# 阶段状态常量
_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"


def _load_read_based_stages() -> list[str]:
    """从 analysis_paths.yaml 读取 read_based 阶段列表。"""
    yaml_path = Path(__file__).parents[2] / "plugins" / "analysis_paths.yaml"
    try:
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        stages = data["paths"]["read_based"]["stages"]
        return [s["tool_id"] for s in stages]
    except Exception:
        logger.warning("无法加载 analysis_paths.yaml，使用默认阶段")
        return _DEFAULT_STAGES


def _human_time_ago(ts: float) -> str:
    """将时间戳转换为'X 分钟前'形式。"""
    diff = time.time() - ts
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff / 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff / 3600)} 小时前"
    return f"{int(diff / 86400)} 天前"


# ─────────────────────────────────────────────────────────────
#  样本进度节点控件
# ─────────────────────────────────────────────────────────────

class _StageNode(QWidget):
    """单个阶段节点：圆圈 + 标签，颜色随状态变化。"""

    _COLOR_MAP = {
        _STATUS_PENDING:   ("#CCCCCC", "#999999"),   # (圆圈色, 文字色)
        _STATUS_RUNNING:   ("#007AFF", "#007AFF"),
        _STATUS_COMPLETED: ("#06943D", "#06943D"),
        _STATUS_FAILED:    ("#FF3B30", "#FF3B30"),
    }
    _SYMBOL_MAP = {
        _STATUS_PENDING:   "○",
        _STATUS_RUNNING:   "◑",
        _STATUS_COMPLETED: "●",
        _STATUS_FAILED:    "✕",
    }

    def __init__(self, tool_id: str, status: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        circle_color, text_color = self._COLOR_MAP.get(status, self._COLOR_MAP[_STATUS_PENDING])
        symbol = self._SYMBOL_MAP.get(status, "○")

        self._dot = QLabel(symbol)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setStyleSheet(
            f"color: {circle_color}; font-size: 16px; background: transparent;"
        )

        self._label = QLabel(tool_id)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"color: {text_color}; font-size: 10px; background: transparent;"
        )

        layout.addWidget(self._dot)
        layout.addWidget(self._label)


class _PipelineProgress(QWidget):
    """流水线进度条：节点 + 连接线。"""

    def __init__(
        self,
        stages: list[str],
        stage_statuses: dict[str, str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for i, tool_id in enumerate(stages):
            status = stage_statuses.get(tool_id, _STATUS_PENDING)
            node = _StageNode(tool_id, status)
            layout.addWidget(node)

            if i < len(stages) - 1:
                # 连接线
                line = QLabel("—")
                line.setAlignment(Qt.AlignmentFlag.AlignCenter)
                line.setStyleSheet(
                    f"color: {styles.COLOR_TEXT_MUTED}; font-size: 12px;"
                    "background: transparent; padding-bottom: 14px;"
                )
                layout.addWidget(line)


# ─────────────────────────────────────────────────────────────
#  样本卡片
# ─────────────────────────────────────────────────────────────

class _SampleCard(QFrame):
    """单个样本卡片，显示阶段进度和操作按钮。"""

    delete_requested = pyqtSignal(str)           # sample_id
    continue_requested = pyqtSignal(str)         # sample_id
    results_requested = pyqtSignal(str)          # sample_id

    def __init__(
        self,
        sample_id: str,
        name: str,
        source: str,
        stage_statuses: dict[str, str],
        stages: list[str],
        last_activity: Optional[float],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._sample_id = sample_id
        self._stages = stages
        self._stage_statuses = stage_statuses

        self.setObjectName("SampleCard")
        self.setFixedWidth(240)
        self.setStyleSheet(f"""
            QFrame#SampleCard {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: 8px;
            }}
            QFrame#SampleCard:hover {{
                border-color: rgba(0, 122, 255, 0.25);
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # ── 顶部行：名称 + 删除按钮 ──
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)

        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.COLOR_TEXT_DEFAULT};"
            "background: transparent;"
        )
        name_label.setWordWrap(False)
        top_row.addWidget(name_label, stretch=1)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(20, 20)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {styles.COLOR_TEXT_HINT};
                font-size: 14px;
                font-weight: bold;
                border-radius: 10px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: rgba(255, 59, 48, 0.12);
                color: {styles.COLOR_DANGER};
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._sample_id))
        top_row.addWidget(del_btn)
        layout.addLayout(top_row)

        # ── 来源行 ──
        src_label = QLabel(source or "无来源信息")
        src_label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        src_label.setWordWrap(False)
        src_label.setMaximumWidth(210)
        src_text = source or "无来源信息"
        # 截断过长文本
        if len(src_text) > 26:
            src_text = src_text[:24] + "…"
        src_label.setText(src_text)
        layout.addWidget(src_label)

        # ── 分隔线 ──
        layout.addWidget(self._make_divider())

        # ── 进度区 ──
        progress = _PipelineProgress(stages, stage_statuses)
        progress.setStyleSheet("background: transparent;")
        layout.addWidget(progress)

        # ── 分隔线 ──
        layout.addWidget(self._make_divider())

        # ── 最后活动时间 ──
        if last_activity:
            time_text = _human_time_ago(last_activity)
        else:
            time_text = "未开始分析"
        time_label = QLabel(time_text)
        time_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        layout.addWidget(time_label)

        # ── 操作按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        all_done = all(
            stage_statuses.get(s, _STATUS_PENDING) == _STATUS_COMPLETED
            for s in stages
        )
        any_started = any(
            stage_statuses.get(s, _STATUS_PENDING) != _STATUS_PENDING
            for s in stages
        )

        if all_done:
            action_text = "重新运行"
        elif any_started:
            action_text = "继续分析"
        else:
            action_text = "开始分析"

        action_btn = QPushButton(action_text)
        action_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        action_btn.clicked.connect(lambda: self.continue_requested.emit(self._sample_id))
        btn_row.addWidget(action_btn)

        results_btn = QPushButton("查看结果")
        results_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        results_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        results_btn.setEnabled(any_started)
        results_btn.clicked.connect(lambda: self.results_requested.emit(self._sample_id))
        btn_row.addWidget(results_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def _make_divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"background-color: {styles.COLOR_BORDER}; max-height: 1px; border: none;"
        )
        return line


# ─────────────────────────────────────────────────────────────
#  "添加新样本"占位卡
# ─────────────────────────────────────────────────────────────

class _AddSamplePlaceholder(QFrame):
    """末尾的"+ 添加新样本"占位卡。"""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("AddPlaceholder")
        self.setFixedWidth(240)
        self.setMinimumHeight(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame#AddPlaceholder {{
                background: transparent;
                border: 2px dashed {styles.COLOR_BORDER_INPUT};
                border-radius: 8px;
            }}
            QFrame#AddPlaceholder:hover {{
                border-color: {styles.COLOR_PRIMARY};
                background: rgba(0, 122, 255, 0.03);
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        plus = QLabel("+")
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet(
            f"font-size: 28px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        layout.addWidget(plus)

        hint = QLabel("添加新样本")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────
#  添加样本对话框
# ─────────────────────────────────────────────────────────────

class SampleAddDialog(QDialog):
    """添加样本对话框。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("添加样本")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background: {styles.COLOR_BG_APP};")

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 样本名称
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例：sample_01")
        self._name_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        form.addRow("样本名称 *", self._name_edit)

        # R1 文件
        r1_row = QHBoxLayout()
        self._r1_edit = QLineEdit()
        self._r1_edit.setPlaceholderText("R1 FASTQ 文件路径（必填）")
        self._r1_edit.setReadOnly(True)
        self._r1_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        r1_btn = QPushButton("浏览…")
        r1_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        r1_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        r1_btn.clicked.connect(lambda: self._browse_file(self._r1_edit, "R1"))
        r1_row.addWidget(self._r1_edit)
        r1_row.addWidget(r1_btn)
        form.addRow("R1 FASTQ *", r1_row)

        # R2 文件（可选）
        r2_row = QHBoxLayout()
        self._r2_edit = QLineEdit()
        self._r2_edit.setPlaceholderText("R2 FASTQ 文件路径（可选，双端测序）")
        self._r2_edit.setReadOnly(True)
        self._r2_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        r2_btn = QPushButton("浏览…")
        r2_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        r2_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        r2_btn.clicked.connect(lambda: self._browse_file(self._r2_edit, "R2"))
        r2_row.addWidget(self._r2_edit)
        r2_row.addWidget(r2_btn)
        form.addRow("R2 FASTQ", r2_row)

        # 来源/备注
        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText("例：SRR123456 / 城市污水 2024")
        self._source_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        form.addRow("来源/备注", self._source_edit)

        layout.addLayout(form)

        # 提示文字
        hint = QLabel("* 为必填项。FASTQ 文件将在分析时上传到远端服务器。")
        hint.setStyleSheet(f"font-size: 11px; color: {styles.COLOR_TEXT_HINT};")
        layout.addWidget(hint)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("确认添加")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(styles.BUTTON_PRIMARY)
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(styles.BUTTON_SECONDARY)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _browse_file(self, target: QLineEdit, label: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {label} FASTQ 文件",
            "",
            "FASTQ Files (*.fastq *.fastq.gz *.fq *.fq.gz);;All Files (*)",
        )
        if path:
            target.setText(path)

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        r1 = self._r1_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "样本名称不能为空")
            return
        if not r1:
            QMessageBox.warning(self, "提示", "请选择 R1 FASTQ 文件")
            return
        self.accept()

    @property
    def sample_name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def r1_path(self) -> str:
        return self._r1_edit.text().strip()

    @property
    def r2_path(self) -> str:
        return self._r2_edit.text().strip()

    @property
    def source(self) -> str:
        return self._source_edit.text().strip()


# ─────────────────────────────────────────────────────────────
#  首页主体
# ─────────────────────────────────────────────────────────────

class HomePage(BasePage):
    """样本管理中心首页。"""

    def __init__(self, main_window: Any = None, parent: Optional[QWidget] = None):
        super().__init__("项目首页")
        if hasattr(self, "label"):
            self.label.hide()
        self._main_window = main_window
        self._stages = _load_read_based_stages()
        self._search_text = ""
        self._card_widgets: list[_SampleCard] = []

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()

    # ── 公开接口 ─────────────────────────────────────────────

    def refresh_context(self) -> None:
        """项目切换 / SSH 变化时由 MainWindow 调用。"""
        self._load_all()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(24, 16, 24, 16)
        self.layout.setSpacing(0)

        # ── 项目头部 ──
        self._header_widget = self._build_project_header()
        self.layout.addWidget(self._header_widget)

        # ── 工具栏 ──
        toolbar = self._build_toolbar()
        self.layout.addWidget(toolbar)

        self.layout.addSpacing(12)

        # ── 样本卡片网格（可滚动）──
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("background: transparent; border: none;")

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(14)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll_area.setWidget(self._grid_container)
        self.layout.addWidget(self._scroll_area, stretch=1)

        self.layout.addSpacing(8)

        # ── 空状态提示（默认隐藏）──
        self._empty_label = QLabel('请先在\u201c项目管理\u201d中创建或选择一个项目')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"font-size: 14px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        self._empty_label.hide()
        self.layout.addWidget(self._empty_label)

        # ── 底部最近执行条 ──
        self._recent_bar = self._build_recent_bar()
        self.layout.addWidget(self._recent_bar)

        # 延迟一次初始加载
        QTimer.singleShot(0, self._load_all)

    def _build_project_header(self) -> QWidget:
        """项目名/描述 + 4 个统计卡片。"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        v = QVBoxLayout(widget)
        v.setContentsMargins(0, 0, 0, 10)
        v.setSpacing(8)

        # 项目名行
        name_row = QHBoxLayout()
        self._proj_name_label = QLabel("—")
        self._proj_name_label.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {styles.COLOR_TEXT_DEFAULT};"
            "background: transparent;"
        )
        name_row.addWidget(self._proj_name_label)
        name_row.addStretch()
        v.addLayout(name_row)

        self._proj_desc_label = QLabel("")
        self._proj_desc_label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        v.addWidget(self._proj_desc_label)

        # 统计条
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._stat_samples = self._make_stat_chip("📁", "0 个样本")
        self._stat_execs = self._make_stat_chip("▶", "0 次执行")
        self._stat_success = self._make_stat_chip("✅", "0 次成功")
        self._stat_disk = self._make_stat_chip("💾", "—")

        for chip in (self._stat_samples, self._stat_execs, self._stat_success, self._stat_disk):
            stats_row.addWidget(chip)
        stats_row.addStretch()
        v.addLayout(stats_row)

        # 细分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(
            f"background: {styles.COLOR_BORDER}; max-height: 1px; border: none;"
        )
        v.addWidget(line)

        return widget

    @staticmethod
    def _make_stat_chip(icon: str, text: str) -> QLabel:
        label = QLabel(f"{icon} {text}")
        label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_SUB};"
            f"background: {styles.COLOR_BG_CARD};"
            f"border: 1px solid {styles.COLOR_BORDER};"
            "border-radius: 4px;"
            "padding: 3px 10px;"
        )
        return label

    def _build_toolbar(self) -> QWidget:
        """搜索框 + 添加样本按钮。"""
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  搜索样本名称或来源…")
        self._search_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        self._search_edit.setMaximumWidth(280)
        self._search_edit.textChanged.connect(self._on_search_changed)
        row.addWidget(self._search_edit)
        row.addStretch()

        self._add_btn = QPushButton("+ 添加样本")
        self._add_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_sample)
        row.addWidget(self._add_btn)

        return toolbar

    def _build_recent_bar(self) -> QWidget:
        """底部最近执行栏。"""
        widget = QFrame()
        widget.setObjectName("RecentBar")
        widget.setStyleSheet(f"""
            QFrame#RecentBar {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: 6px;
            }}
        """)
        widget.setMaximumHeight(90)

        v = QVBoxLayout(widget)
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(4)

        header = QLabel("最近执行")
        header.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {styles.COLOR_TEXT_HINT};"
            "background: transparent;"
        )
        v.addWidget(header)

        self._recent_rows_widget = QWidget()
        self._recent_rows_widget.setStyleSheet("background: transparent;")
        self._recent_rows_layout = QVBoxLayout(self._recent_rows_widget)
        self._recent_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_rows_layout.setSpacing(2)
        v.addWidget(self._recent_rows_widget)

        return widget

    # ── 数据加载 ─────────────────────────────────────────────

    def _load_all(self) -> None:
        """全量刷新：统计、样本卡片、最近执行。"""
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            self._show_no_project_state()
            return

        self._show_project_state(pm.current_project)
        self._load_stats(pm)
        self._load_samples(pm)
        self._load_recent(pm)

    def _show_no_project_state(self) -> None:
        self._proj_name_label.setText("无活动项目")
        self._proj_desc_label.setText('请在\u201c项目管理\u201d中创建或选择一个项目')
        self._stat_samples.setText("📁 — 个样本")
        self._stat_execs.setText("▶ — 次执行")
        self._stat_success.setText("✅ — 次成功")
        self._stat_disk.setText("💾 —")
        self._clear_grid()
        self._empty_label.show()
        self._add_btn.setEnabled(False)
        self._search_edit.setEnabled(False)
        self._clear_recent()

    def _show_project_state(self, project) -> None:
        self._proj_name_label.setText(project.name)
        self._proj_desc_label.setText(project.description or "")
        self._empty_label.hide()
        self._add_btn.setEnabled(True)
        self._search_edit.setEnabled(True)

    def _load_stats(self, pm) -> None:
        """查询并更新统计条。"""
        try:
            db = pm.db
            sample_count = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            row = db.execute(
                "SELECT COUNT(*), SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)"
                " FROM executions"
            ).fetchone()
            exec_count = row[0] or 0
            success_count = int(row[1] or 0)

            self._stat_samples.setText(f"📁 {sample_count} 个样本")
            self._stat_execs.setText(f"▶ {exec_count} 次执行")
            self._stat_success.setText(f"✅ {success_count} 次成功")

            # 磁盘：尝试通过 storage_manager 获取，否则显示 —
            disk_text = self._query_disk_usage()
            self._stat_disk.setText(f"💾 {disk_text}")
        except Exception:
            logger.exception("统计数据加载失败")

    def _query_disk_usage(self) -> str:
        """尝试查询远端磁盘占用，失败返回'—'。"""
        try:
            locator = self._get_service_locator()
            if locator is None:
                return "—"
            ssh = getattr(locator, "ssh_service", None)
            if ssh is None or not getattr(ssh, "is_connected", False):
                return "—"
            from core.storage_manager import StorageManager
            mgr = StorageManager(ssh)
            usage = mgr.get_disk_usage("/h2ometa")
            return f"{usage.used_gb:.1f} / {usage.total_gb:.0f} GB"
        except Exception:
            return "—"

    def _load_samples(self, pm) -> None:
        """查询样本列表，重建卡片网格。"""
        try:
            db = pm.db
            rows = db.execute(
                "SELECT sample_id, name, source FROM samples ORDER BY rowid DESC"
            ).fetchall()
        except Exception:
            logger.exception("样本列表加载失败")
            rows = []

        # 过滤
        search = self._search_text.lower()
        if search:
            rows = [r for r in rows if search in r["name"].lower() or search in (r["source"] or "").lower()]

        self._clear_grid()
        self._card_widgets.clear()

        col_count = 2
        for idx, row in enumerate(rows):
            stage_statuses = self._get_stage_statuses(pm.db, row["sample_id"])
            last_ts = self._get_last_activity(pm.db, row["sample_id"])

            card = _SampleCard(
                sample_id=row["sample_id"],
                name=row["name"],
                source=row["source"] or "",
                stage_statuses=stage_statuses,
                stages=self._stages,
                last_activity=last_ts,
            )
            card.delete_requested.connect(self._on_delete_sample)
            card.continue_requested.connect(self._on_continue_analysis)
            card.results_requested.connect(self._on_view_results)

            grid_row = idx // col_count
            grid_col = idx % col_count
            self._grid_layout.addWidget(card, grid_row, grid_col, Qt.AlignmentFlag.AlignTop)
            self._card_widgets.append(card)

        # 末尾添加占位卡
        placeholder = _AddSamplePlaceholder()
        placeholder.clicked.connect(self._on_add_sample)
        total = len(rows)
        ph_row = total // col_count
        ph_col = total % col_count
        self._grid_layout.addWidget(placeholder, ph_row, ph_col, Qt.AlignmentFlag.AlignTop)

        if not rows:
            self._empty_label.hide()  # 占位卡已表达空状态

    def _get_stage_statuses(self, db: sqlite3.Connection, sample_id: str) -> dict[str, str]:
        """获取每个阶段的最新状态。"""
        result: dict[str, str] = {}
        try:
            rows = db.execute(
                "SELECT tool_id, status FROM executions"
                " WHERE sample_id = ?"
                " ORDER BY created_at DESC",
                (sample_id,),
            ).fetchall()
            # 每个 tool_id 取最新一条
            for row in rows:
                tid = row["tool_id"]
                if tid not in result:
                    result[tid] = row["status"]
        except Exception:
            logger.exception("获取阶段状态失败")
        return result

    def _get_last_activity(self, db: sqlite3.Connection, sample_id: str) -> Optional[float]:
        """获取样本最后一次执行的时间。"""
        try:
            row = db.execute(
                "SELECT MAX(created_at) FROM executions WHERE sample_id = ?",
                (sample_id,),
            ).fetchone()
            return row[0] if row and row[0] else None
        except Exception:
            return None

    def _load_recent(self, pm) -> None:
        """加载最近 5 次执行，更新底部执行条。"""
        self._clear_recent()
        try:
            db = pm.db
            rows = db.execute(
                "SELECT e.tool_id, e.sample_id, e.status, e.created_at, s.name as sample_name"
                " FROM executions e"
                " LEFT JOIN samples s ON e.sample_id = s.sample_id"
                " ORDER BY e.created_at DESC LIMIT 5"
            ).fetchall()
        except Exception:
            logger.exception("最近执行加载失败")
            rows = []

        if not rows:
            placeholder = QLabel("暂无执行记录")
            placeholder.setStyleSheet(
                f"font-size: 11px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
            )
            self._recent_rows_layout.addWidget(placeholder)
            return

        _STATUS_ICONS = {
            "completed": "✅",
            "running":   "🔄",
            "failed":    "❌",
            "pending":   "⏳",
            "retrying":  "🔁",
        }
        for row in rows:
            icon = _STATUS_ICONS.get(row["status"], "•")
            sample_name = row["sample_name"] or row["sample_id"] or "—"
            time_text = _human_time_ago(row["created_at"]) if row["created_at"] else "—"
            text = f"{icon}  {row['tool_id']}  ·  {sample_name}  ·  {time_text}"

            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"font-size: 11px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
            )
            self._recent_rows_layout.addWidget(lbl)

    # ── 工具方法 ─────────────────────────────────────────────

    def _clear_grid(self) -> None:
        """清空卡片网格。"""
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_recent(self) -> None:
        while self._recent_rows_layout.count():
            item = self._recent_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _get_project_manager(self):
        if self._main_window and hasattr(self._main_window, "_pm"):
            return self._main_window._pm
        return None

    def _get_service_locator(self):
        if self._main_window and hasattr(self._main_window, "_locator"):
            return self._main_window._locator
        return None

    # ── 槽函数 ──────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        pm = self._get_project_manager()
        if pm and pm.current_project:
            self._load_samples(pm)

    def _on_add_sample(self) -> None:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            QMessageBox.information(self, "提示", "请先选择一个项目")
            return

        dialog = SampleAddDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._on_sample_added(
                pm,
                name=dialog.sample_name,
                r1_path=dialog.r1_path,
                r2_path=dialog.r2_path,
                source=dialog.source,
            )

    def _on_sample_added(
        self,
        pm,
        name: str,
        r1_path: str,
        r2_path: str,
        source: str,
    ) -> None:
        """将新样本写入 samples 表并刷新。"""
        import json as _json

        sample_id = f"smp_{uuid.uuid4().hex[:12]}"
        metadata = _json.dumps({"r1": r1_path, "r2": r2_path}, ensure_ascii=False)
        try:
            pm.db.execute(
                "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
                (sample_id, name, source, metadata),
            )
            pm.db.commit()
            logger.info("样本已添加: %s (%s)", name, sample_id)
            self._load_all()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "添加失败", f"样本 ID 已存在：{sample_id}")
        except Exception as e:
            QMessageBox.critical(self, "数据库错误", str(e))
            logger.exception("添加样本失败")

    def _on_delete_sample(self, sample_id: str) -> None:
        pm = self._get_project_manager()
        if pm is None:
            return

        # 查询样本名
        try:
            row = pm.db.execute(
                "SELECT name FROM samples WHERE sample_id = ?", (sample_id,)
            ).fetchone()
            name = row["name"] if row else sample_id
        except Exception:
            name = sample_id

        reply = QMessageBox.question(
            self,
            "确认删除",
            f'确定要删除样本\u201c{name}\u201d及其所有执行记录吗？\n此操作不可撤销。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # 删除执行 IO 记录 → 数据项 → 执行 → 样本
            pm.db.execute(
                "DELETE FROM execution_io WHERE execution_id IN"
                " (SELECT execution_id FROM executions WHERE sample_id = ?)",
                (sample_id,),
            )
            pm.db.execute(
                "DELETE FROM data_items WHERE sample_id = ?", (sample_id,)
            )
            pm.db.execute(
                "DELETE FROM executions WHERE sample_id = ?", (sample_id,)
            )
            pm.db.execute("DELETE FROM samples WHERE sample_id = ?", (sample_id,))
            pm.db.commit()
            logger.info("样本已删除: %s", sample_id)
            self._load_all()
        except Exception as e:
            QMessageBox.critical(self, "删除失败", str(e))
            logger.exception("删除样本失败")

    def _on_continue_analysis(self, sample_id: str) -> None:
        """跳转到分析工作台，预填样本信息。"""
        pm = self._get_project_manager()
        if pm is None:
            return

        try:
            row = pm.db.execute(
                "SELECT name, metadata FROM samples WHERE sample_id = ?", (sample_id,)
            ).fetchone()
        except Exception:
            row = None

        # 切换到分析工作台（侧边栏索引 4）
        if self._main_window and hasattr(self._main_window, "sidebar"):
            self._main_window.sidebar.setCurrentRow(4)

        # 如果分析页支持预填，尝试注入
        if row and self._main_window and hasattr(self._main_window, "analysis_page"):
            import json as _json
            try:
                meta = _json.loads(row["metadata"] or "{}")
                r1 = meta.get("r1", "")
                r2 = meta.get("r2", "")
                ap = self._main_window.analysis_page
                if hasattr(ap, "set_sample_context"):
                    ap.set_sample_context(
                        sample_id=sample_id,
                        sample_name=row["name"],
                        r1_path=r1,
                        r2_path=r2,
                    )
                elif hasattr(ap, "refresh_context"):
                    ap.refresh_context()
            except Exception:
                logger.debug("预填分析页参数失败（非严重错误）")
    def _on_view_results(self, sample_id: str) -> None:
        """暂未实现的结果浏览（待 results_page 建成后接入）。"""
        QMessageBox.information(
            self,
            "功能开发中",
            "结果浏览页正在开发中，敬请期待。",
        )

