"""Reusable widgets for the home page."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.utils import human_time_ago
from ui.widgets import styles

_STATUS_PENDING = "pending"
_STATUS_RUNNING = "running"
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"


class StageNode(QWidget):
    """Single pipeline stage node."""

    _COLOR_MAP = {
        _STATUS_PENDING: (styles.COLOR_TEXT_MUTED, styles.COLOR_TEXT_HINT),
        _STATUS_RUNNING: (styles.COLOR_PRIMARY, styles.COLOR_PRIMARY),
        _STATUS_COMPLETED: (styles.COLOR_SUCCESS, styles.COLOR_SUCCESS),
        _STATUS_FAILED: (styles.COLOR_DANGER, styles.COLOR_DANGER),
    }
    _SYMBOL_MAP = {
        _STATUS_PENDING: "○",
        _STATUS_RUNNING: "◑",
        _STATUS_COMPLETED: "●",
        _STATUS_FAILED: "✕",
    }

    def __init__(self, tool_id: str, status: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        circle_color, text_color = self._COLOR_MAP.get(status, self._COLOR_MAP[_STATUS_PENDING])
        symbol = self._SYMBOL_MAP.get(status, "○")

        dot = QLabel(symbol)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet(
            f"color: {circle_color}; font-size: 18px; font-weight: bold; background: transparent;"
        )

        label = QLabel(tool_id)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"color: {text_color}; font-size: 11px; font-weight: 600; background: transparent;"
        )

        layout.addWidget(dot)
        layout.addWidget(label)


class PipelineProgress(QWidget):
    """Pipeline progress bar built from stage nodes."""

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

        for idx, tool_id in enumerate(stages):
            status = stage_statuses.get(tool_id, _STATUS_PENDING)
            layout.addWidget(StageNode(tool_id, status))

            if idx < len(stages) - 1:
                line = QLabel("—")
                line.setAlignment(Qt.AlignmentFlag.AlignCenter)
                line.setStyleSheet(
                    f"color: {styles.COLOR_TEXT_MUTED}; font-size: 14px;"
                    "background: transparent; padding-bottom: 16px;"
                )
                layout.addWidget(line)


class SampleCard(QFrame):
    """Single sample card for the home page."""

    delete_requested = pyqtSignal(str)
    continue_requested = pyqtSignal(str)
    results_requested = pyqtSignal(str)

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

        self.setObjectName("SampleCard")
        self.setFixedWidth(260)
        self.setStyleSheet(
            f"""
            QFrame#SampleCard {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
            }}
            QFrame#SampleCard:hover {{
                border: 1px solid {styles.COLOR_TEXT_HINT};
            }}
            """
        )
        styles.apply_card_shadow(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {styles.COLOR_TEXT_TITLE};"
            "background: transparent; border: none;"
        )
        top_row.addWidget(name_label, stretch=1)

        delete_btn = QPushButton("×")
        delete_btn.setFixedSize(24, 24)
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {styles.COLOR_TEXT_HINT};
                font-size: 18px;
                font-weight: bold;
                border-radius: 12px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: #FEE2E2;
                color: {styles.COLOR_DANGER};
            }}
            """
        )
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._sample_id))
        top_row.addWidget(delete_btn)
        layout.addLayout(top_row)

        source_text = source or "无来源信息"
        if len(source_text) > 26:
            source_text = source_text[:24] + "…"
        source_label = QLabel(source_text)
        source_label.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {styles.COLOR_TEXT_SUB}; background: transparent; border: none;"
        )
        layout.addWidget(source_label)

        progress_container = QWidget()
        progress_container.setStyleSheet(f"background: {styles.COLOR_BG_APP}; border-radius: 8px;")
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(10, 10, 10, 10)
        progress = PipelineProgress(stages, stage_statuses)
        progress.setStyleSheet("background: transparent; border: none;")
        progress_layout.addWidget(progress)
        layout.addWidget(progress_container)

        time_label = QLabel(human_time_ago(last_activity) if last_activity else "未开始分析")
        time_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {styles.COLOR_TEXT_HINT}; background: transparent; border: none;"
        )
        layout.addWidget(time_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        all_done = all(stage_statuses.get(stage, _STATUS_PENDING) == _STATUS_COMPLETED for stage in stages)
        any_started = any(stage_statuses.get(stage, _STATUS_PENDING) != _STATUS_PENDING for stage in stages)
        action_text = "重新运行" if all_done else "继续分析" if any_started else "开始分析"

        action_btn = QPushButton(action_text)
        action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        action_btn.setStyleSheet(styles.BUTTON_PASTEL_PRIMARY)
        action_btn.clicked.connect(lambda: self.continue_requested.emit(self._sample_id))
        button_row.addWidget(action_btn)

        results_btn = QPushButton("查看结果")
        results_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        results_btn.setEnabled(any_started)
        results_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        results_btn.clicked.connect(lambda: self.results_requested.emit(self._sample_id))
        button_row.addWidget(results_btn)

        layout.addLayout(button_row)


class AddSamplePlaceholder(QFrame):
    """Placeholder card for adding a new sample."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("AddPlaceholder")
        self.setFixedWidth(260)
        self.setMinimumHeight(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QFrame#AddPlaceholder {{
                background: {styles.COLOR_BG_CARD_HIGHLIGHT};
                border: 2px dashed {styles.COLOR_BORDER_INPUT};
                border-radius: {styles.RADIUS_CARD};
            }}
            QFrame#AddPlaceholder:hover {{
                border-color: {styles.COLOR_PRIMARY};
                background: {styles.COLOR_BG_CARD_INTERPRET};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        plus = QLabel("+")
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet(
            f"font-size: 32px; font-weight: 300; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        layout.addWidget(plus)

        hint = QLabel("添加新样本")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class SampleAddDialog(QDialog):
    """Dialog for creating a sample."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("添加样本")
        self.setMinimumWidth(480)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {styles.COLOR_BG_CARD};
            }}
            QLabel {{
                font-size: 13px;
                color: {styles.COLOR_TEXT_DEFAULT};
                font-weight: 500;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例：sample_01")
        self._name_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        form.addRow("样本名称 *", self._name_edit)

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

        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText("例：SRR123456 / 城市污水 2024")
        self._source_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        form.addRow("来源/备注", self._source_edit)

        layout.addLayout(form)

        hint = QLabel("* 为必填项。FASTQ 文件将在分析时上传到远端服务器。")
        hint.setStyleSheet(f"font-size: 11px; color: {styles.COLOR_TEXT_HINT};")
        layout.addWidget(hint)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("确认添加")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        button_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(styles.BUTTON_PRIMARY)
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(styles.BUTTON_SECONDARY)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setCursor(Qt.CursorShape.PointingHandCursor)
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setCursor(Qt.CursorShape.PointingHandCursor)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

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
        if not self.sample_name:
            QMessageBox.warning(self, "提示", "样本名称不能为空")
            return
        if not self.r1_path:
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
