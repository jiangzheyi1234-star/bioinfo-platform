"""组装分析流水线页面 — megahit/metaspades → binning → checkm2 → prokka/bakta。

布局:
  1. 样本选择区: 选择样本（来自读长分析输出的去宿主 fastq）
  2. 流水线配置区: 4 个阶段，可选工具
  3. 运行按钮: 条件启用
  4. 阶段状态 + 执行历史
"""
import logging
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.page_base import BasePage
from ui.widgets import styles
from ui.widgets.execution_history_card import ExecutionHistoryCard
from ui.widgets.stage_status_widget import (
    STATUS_PENDING,
    StageStatusWidget,
)

logger = logging.getLogger(__name__)

# 各阶段可选工具
_ASSEMBLY_TOOLS = ["megahit", "metaspades"]
_BINNING_TOOLS = ["metabat2", "maxbin2", "concoct"]
_QUALITY_TOOLS = ["checkm2", "busco"]
_ANNOTATION_TOOLS = ["prokka", "bakta"]

# 阶段默认参数
_STAGE_DEFAULTS: dict[str, list[dict]] = {
    "megahit": [{"name": "min_contig_len", "label": "最小 contig 长度", "default": 500, "min": 100, "max": 5000}],
    "metaspades": [{"name": "threads", "label": "线程数", "default": 8, "min": 1, "max": 64}],
    "metabat2": [{"name": "min_contig_size", "label": "最小 contig 长度", "default": 1500, "min": 1000, "max": 5000}],
    "maxbin2": [{"name": "thread", "label": "线程数", "default": 4, "min": 1, "max": 64}],
    "concoct": [{"name": "chunk_size", "label": "Chunk 大小", "default": 10000, "min": 1000, "max": 50000}],
    "checkm2": [{"name": "threads", "label": "线程数", "default": 8, "min": 1, "max": 64}],
    "busco": [{"name": "lineage", "label": "谱系", "default": 4, "min": 1, "max": 64}],
    "prokka": [{"name": "cpus", "label": "CPU 数", "default": 4, "min": 1, "max": 64}],
    "bakta": [{"name": "threads", "label": "线程数", "default": 4, "min": 1, "max": 64}],
}


class _ToolSelectorCard(QGroupBox):
    """可展开的工具选择 + 参数卡片"""

    def __init__(self, stage_label: str, tools: list[str], parent=None):
        super().__init__(stage_label, parent)
        self._tools = tools
        self._param_spinboxes: dict[str, QSpinBox] = {}
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 600;
                font-size: 13px;
                color: {styles.COLOR_TEXT_TITLE};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
                margin-top: 8px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {styles.COLOR_TEXT_TITLE};
                background: {styles.COLOR_BG_CARD};
            }}
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 12)
        layout.setSpacing(10)

        # 工具选择行
        tool_row = QHBoxLayout()
        tool_label = QLabel("选择工具")
        tool_label.setStyleSheet(styles.FORM_LABEL)
        tool_label.setFixedWidth(80)
        tool_row.addWidget(tool_label)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems(self._tools)
        self.tool_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        self.tool_combo.currentTextChanged.connect(self._on_tool_changed)
        tool_row.addWidget(self.tool_combo, stretch=1)
        layout.addLayout(tool_row)

        # 参数容器
        self._params_container = QWidget()
        self._params_layout = QVBoxLayout(self._params_container)
        self._params_layout.setContentsMargins(0, 0, 0, 0)
        self._params_layout.setSpacing(6)
        layout.addWidget(self._params_container)

        self._on_tool_changed(self._tools[0])

    def _on_tool_changed(self, tool_id: str) -> None:
        """切换工具时重建参数面板"""
        # 清空旧参数
        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._param_spinboxes.clear()

        params = _STAGE_DEFAULTS.get(tool_id, [])
        for param in params:
            row = QHBoxLayout()
            lbl = QLabel(param["label"])
            lbl.setStyleSheet(styles.FORM_LABEL)
            lbl.setFixedWidth(120)
            row.addWidget(lbl)

            spin = QSpinBox()
            spin.setRange(param.get("min", 1), param.get("max", 9999))
            spin.setValue(param["default"])
            spin.setStyleSheet(f"""
                QSpinBox {{
                    padding: 4px 8px;
                    border: 1px solid {styles.COLOR_BORDER_INPUT};
                    border-radius: {styles.RADIUS_CTRL};
                    background: {styles.COLOR_BG_CARD};
                    color: {styles.COLOR_TEXT_DEFAULT};
                    font-size: 13px;
                }}
            """)
            row.addWidget(spin, stretch=1)
            self._params_layout.addLayout(row)
            self._param_spinboxes[param["name"]] = spin

    def get_tool_id(self) -> str:
        return self.tool_combo.currentText()

    def get_parameters(self) -> dict[str, Any]:
        return {name: spin.value() for name, spin in self._param_spinboxes.items()}


class AssemblyPage(BasePage):
    """组装分析流水线页面

    流程: 去宿主 reads → 组装 → Binning → 质量评估 → 注释
    """

    def __init__(self, main_window=None):
        super().__init__("组装分析")
        if hasattr(self, "label"):
            self.label.hide()

        self.main_window = main_window
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()

    def _get_locator(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator
        return None

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(12)

        # 标题
        header_row = QHBoxLayout()
        header = QLabel("组装分析流水线")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        header_row.addWidget(header)
        header_row.addStretch()
        self.layout.addLayout(header_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(styles.DIVIDER)
        self.layout.addWidget(line)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.verticalScrollBar().setStyleSheet(styles.SCROLL_BAR_ELEGANT)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(14)

        # ── 样本选择 ──────────────────────────────────────────
        sample_group = QGroupBox("样本输入")
        sample_group.setStyleSheet(self._group_style())
        sample_inner = QVBoxLayout(sample_group)
        sample_inner.setContentsMargins(14, 8, 14, 12)

        sample_row = QHBoxLayout()
        sample_lbl = QLabel("选择样本")
        sample_lbl.setStyleSheet(styles.FORM_LABEL)
        sample_lbl.setFixedWidth(80)
        sample_row.addWidget(sample_lbl)

        self._sample_combo = QComboBox()
        self._sample_combo.setPlaceholderText("请先打开项目...")
        self._sample_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        sample_row.addWidget(self._sample_combo, stretch=1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        refresh_btn.setFixedWidth(60)
        refresh_btn.clicked.connect(self._refresh_samples)
        sample_row.addWidget(refresh_btn)
        sample_inner.addLayout(sample_row)

        hint = QLabel("输入数据：来自去宿主（hostile）阶段输出的 fastq 文件")
        hint.setStyleSheet(styles.LABEL_HINT)
        sample_inner.addWidget(hint)
        content_layout.addWidget(sample_group)

        # ── 流水线配置 ─────────────────────────────────────────
        pipeline_lbl = QLabel("流水线配置")
        pipeline_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.COLOR_TEXT_TITLE};"
            f" background: transparent;"
        )
        content_layout.addWidget(pipeline_lbl)

        # 阶段1: 组装
        self._assembly_card = _ToolSelectorCard("第 1 步  组装", _ASSEMBLY_TOOLS)
        self._stage1 = StageStatusWidget(_ASSEMBLY_TOOLS[0], "组装", 0)
        content_layout.addWidget(self._stage1)
        content_layout.addWidget(self._assembly_card)

        # 阶段2: Binning
        self._binning_card = _ToolSelectorCard("第 2 步  Binning", _BINNING_TOOLS)
        self._stage2 = StageStatusWidget(_BINNING_TOOLS[0], "Binning", 1)
        content_layout.addWidget(self._stage2)
        content_layout.addWidget(self._binning_card)

        # 阶段3: 质量评估
        self._quality_card = _ToolSelectorCard("第 3 步  质量评估", _QUALITY_TOOLS)
        self._stage3 = StageStatusWidget(_QUALITY_TOOLS[0], "质量评估", 2)
        content_layout.addWidget(self._stage3)
        content_layout.addWidget(self._quality_card)

        # 阶段4: 注释
        self._annotation_card = _ToolSelectorCard("第 4 步  基因注释", _ANNOTATION_TOOLS)
        self._stage4 = StageStatusWidget(_ANNOTATION_TOOLS[0], "基因注释", 3)
        content_layout.addWidget(self._stage4)
        content_layout.addWidget(self._annotation_card)

        # ── 运行按钮 ──────────────────────────────────────────
        run_row = QHBoxLayout()
        run_row.addStretch()
        self._run_btn = QPushButton("启动组装流水线")
        self._run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFixedHeight(36)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        content_layout.addLayout(run_row)

        self._status_label = QLabel("请先打开项目并选择样本")
        self._status_label.setStyleSheet(styles.LABEL_HINT)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(self._status_label)

        # ── 执行历史 ──────────────────────────────────────────
        history_lbl = QLabel("执行历史")
        history_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.COLOR_TEXT_TITLE};"
            f" background: transparent;"
        )
        content_layout.addWidget(history_lbl)

        self._history_card = ExecutionHistoryCard()
        content_layout.addWidget(self._history_card)

        content_layout.addStretch()
        scroll.setWidget(content)
        self.layout.addWidget(scroll)

    @staticmethod
    def _group_style() -> str:
        return f"""
            QGroupBox {{
                font-weight: 600;
                font-size: 13px;
                color: {styles.COLOR_TEXT_TITLE};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
                margin-top: 8px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {styles.COLOR_TEXT_TITLE};
                background: {styles.COLOR_BG_CARD};
            }}
        """

    def _refresh_samples(self) -> None:
        """从 DataRegistry 加载样本列表"""
        locator = self._get_locator()
        if locator is None or locator.data_registry is None:
            self._sample_combo.setPlaceholderText("请先打开项目...")
            return

        registry = locator.data_registry
        samples = registry.list_samples()
        self._sample_combo.clear()
        for s in samples:
            self._sample_combo.addItem(s.name, s.sample_id)

        can_run = self._sample_combo.count() > 0
        self._run_btn.setEnabled(can_run)
        self._status_label.setText(
            "选择样本后点击启动" if can_run else "暂无样本，请先在分析流水线页面运行读长分析"
        )

        # 刷新执行历史
        try:
            self._history_card.set_db_connection(locator.project_manager.db)
        except Exception:
            pass

    def _on_run(self) -> None:
        """启动组装流水线"""
        locator = self._get_locator()
        if locator is None or locator.tool_engine is None:
            QMessageBox.warning(self, "提示", "请先连接 SSH 并打开项目")
            return

        sample_id = self._sample_combo.currentData()
        if not sample_id:
            QMessageBox.warning(self, "提示", "请选择样本")
            return

        registry = locator.data_registry
        if registry is None:
            QMessageBox.warning(self, "提示", "请先打开项目")
            return

        # 查找去宿主输出 fastq 作为组装输入
        inputs = registry.find_compatible(sample_id, "fastq")
        if not inputs:
            QMessageBox.warning(
                self, "提示",
                "未找到该样本的 fastq 文件。\n请先在「分析流水线」页面完成读长分析（fastp→hostile）。"
            )
            return

        # 选最新的 fastq 作为输入
        input_data_id = inputs[0].data_id
        engine = locator.tool_engine

        # 按顺序提交阶段（简化：逐步提交，监听完成后自动提交下一步）
        assembly_tool = self._assembly_card.get_tool_id()
        assembly_params = self._assembly_card.get_parameters()

        self._stage1.set_status("running")
        self._run_btn.setEnabled(False)
        self._status_label.setText(f"正在提交 {assembly_tool}...")

        try:
            exec_id = engine.execute(
                tool_id=assembly_tool,
                input_data_ids=[input_data_id],
                parameters=assembly_params,
                sample_id=sample_id,
                triggered_by="manual",
            )
            self._status_label.setText(f"第 1 步已提交 (ID: {exec_id[:16]})")

            # 连接完成信号，自动推进到下一步
            if locator.tool_engine:
                locator.tool_engine.execution_completed.connect(
                    lambda eid: self._on_stage_completed(eid, exec_id, sample_id)
                )
                locator.tool_engine.execution_failed.connect(
                    lambda eid, err: self._on_stage_failed(eid, exec_id, err)
                )
        except Exception as e:
            self._stage1.set_status("failed")
            self._run_btn.setEnabled(True)
            QMessageBox.critical(self, "提交失败", str(e))

    def _on_stage_completed(self, execution_id: str, expected_id: str, sample_id: str) -> None:
        """某阶段完成后更新状态"""
        if execution_id != expected_id:
            return

        # 更新第 1 步状态
        self._stage1.set_status("completed")
        self._status_label.setText("第 1 步（组装）完成。如需继续，请手动提交后续阶段。")
        self._run_btn.setEnabled(True)

        # 刷新执行历史
        locator = self._get_locator()
        if locator:
            try:
                self._history_card.set_db_connection(locator.project_manager.db)
                self._history_card.refresh()
            except Exception:
                pass

    def _on_stage_failed(self, execution_id: str, expected_id: str, error: str) -> None:
        if execution_id != expected_id:
            return
        self._stage1.set_status("failed")
        self._run_btn.setEnabled(True)
        self._status_label.setText(f"第 1 步失败: {error}")
