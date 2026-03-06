"""分析流水线页面 — 配置并运行 fastp → hostile → kraken2 流水线。

布局:
  1. 样本选择区: 选择/创建样本，导入 FASTQ
  2. 流水线配置区: 3 个阶段（fastp/hostile/kraken2），各阶段可展开参数
  3. 运行按钮: SSH + 项目 + 数据全部就绪才启用 (Risk 3 缓解)
  4. 阶段状态显示: 实时显示 pending/running/completed/failed
"""

import logging
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles
from ui.widgets.execution_history_card import ExecutionHistoryCard
from ui.widgets.stage_status_widget import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    StageStatusWidget,
)

logger = logging.getLogger(__name__)

# 流水线阶段定义（硬编码 MVP 版本）
_PIPELINE_STAGES = [
    {
        "tool_id": "fastp",
        "name": "fastp — 质量控制",
        "input_type": "fastq",
        "params": [
            {"name": "qualified_quality_phred", "label": "最低质量值", "default": 15, "min": 1, "max": 40},
            {"name": "length_required", "label": "最短读长", "default": 50, "min": 10, "max": 500},
            {"name": "thread", "label": "线程数", "default": 4, "min": 1, "max": 64},
        ],
    },
    {
        "tool_id": "hostile",
        "name": "hostile — 去宿主",
        "input_type": "fastq",
        "params": [
            {"name": "threads", "label": "线程数", "default": 4, "min": 1, "max": 64},
        ],
    },
    {
        "tool_id": "kraken2",
        "name": "Kraken2 — 物种分类",
        "input_type": "fastq",
        "params": [
            {"name": "confidence", "label": "置信度阈值", "default": 0, "min": 0, "max": 100},
            {"name": "threads", "label": "线程数", "default": 8, "min": 1, "max": 64},
        ],
        "databases": [
            {"param_name": "db", "label": "Kraken2 数据库路径", "required": True},
        ],
    },
]


class AnalysisPage(QFrame):
    """分析流水线页面"""

    def __init__(
        self,
        main_window: Any = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._main_window = main_window
        self._running = False  # 流水线运行中标记
        self._pipeline_run_id: Optional[str] = None
        self._stage_widgets: list[StageStatusWidget] = []
        self._param_widgets: dict[str, dict[str, QSpinBox]] = {}
        self._db_widgets: dict[str, dict[str, QLineEdit]] = {}

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self._build_ui()
        self._connect_signals()
        self._update_run_button_state()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(16)

        # 标题
        title = QLabel("分析流水线")
        title.setStyleSheet(styles.PAGE_HEADER_TITLE)
        main_layout.addWidget(title)

        desc = QLabel("配置并运行 FASTQ 质控 → 去宿主 → 物种分类 流水线")
        desc.setStyleSheet(styles.LABEL_HINT)
        main_layout.addWidget(desc)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")

        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        # 1. 样本选择区
        self._build_sample_section(scroll_layout)

        # 2. 流水线阶段配置区
        self._build_pipeline_section(scroll_layout)

        # 3. 运行按钮区
        self._build_run_section(scroll_layout)

        # 4. 执行历史卡片
        self._execution_history = ExecutionHistoryCard()
        scroll_layout.addWidget(self._execution_history)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, stretch=1)

    # ── 样本选择区 ────────────────────────────────────────────

    def _build_sample_section(self, parent_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("SampleCard")
        card.setStyleSheet(styles.CARD_FRAME("SampleCard"))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("样本与数据")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 样本名称
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = QLabel("样本名称:")
        name_label.setStyleSheet(styles.FORM_LABEL)
        name_label.setFixedWidth(80)
        name_row.addWidget(name_label)

        self._sample_name_input = QLineEdit()
        self._sample_name_input.setPlaceholderText("输入样本名称（如 WaterSample01）")
        self._sample_name_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._sample_name_input.textChanged.connect(self._update_run_button_state)
        name_row.addWidget(self._sample_name_input)
        layout.addLayout(name_row)

        # FASTQ 文件导入
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_label = QLabel("R1 文件:")
        file_label.setStyleSheet(styles.FORM_LABEL)
        file_label.setFixedWidth(80)
        file_row.addWidget(file_label)

        self._r1_path_label = QLabel("未选择")
        self._r1_path_label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_HINT}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        file_row.addWidget(self._r1_path_label, stretch=1)

        self._btn_browse_r1 = QPushButton("浏览...")
        self._btn_browse_r1.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_browse_r1.clicked.connect(lambda: self._browse_file("r1"))
        file_row.addWidget(self._btn_browse_r1)
        layout.addLayout(file_row)

        # R2 (可选)
        file_row2 = QHBoxLayout()
        file_row2.setSpacing(8)
        file_label2 = QLabel("R2 文件:")
        file_label2.setStyleSheet(styles.FORM_LABEL)
        file_label2.setFixedWidth(80)
        file_row2.addWidget(file_label2)

        self._r2_path_label = QLabel("未选择（可选，双端测序）")
        self._r2_path_label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_HINT}; "
            f"background: {styles.COLOR_BG_BLANK};"
        )
        file_row2.addWidget(self._r2_path_label, stretch=1)

        self._btn_browse_r2 = QPushButton("浏览...")
        self._btn_browse_r2.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_browse_r2.clicked.connect(lambda: self._browse_file("r2"))
        file_row2.addWidget(self._btn_browse_r2)
        layout.addLayout(file_row2)

        # 路径缓存
        self._r1_path: Optional[str] = None
        self._r2_path: Optional[str] = None

        parent_layout.addWidget(card)

    # ── 流水线阶段配置区 ──────────────────────────────────────

    def _build_pipeline_section(self, parent_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("PipelineCard")
        card.setStyleSheet(styles.CARD_FRAME("PipelineCard"))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("流水线配置")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        for i, stage_def in enumerate(_PIPELINE_STAGES):
            tool_id = stage_def["tool_id"]

            # 阶段状态 widget
            stage_widget = StageStatusWidget(
                tool_id=tool_id,
                tool_name=stage_def["name"],
                stage_index=i,
            )
            self._stage_widgets.append(stage_widget)
            layout.addWidget(stage_widget)

            # 参数面板
            self._param_widgets[tool_id] = {}
            for param_def in stage_def.get("params", []):
                param_row = QHBoxLayout()
                param_row.setSpacing(8)
                param_row.setContentsMargins(24, 0, 0, 0)

                label = QLabel(f"  {param_def['label']}:")
                label.setStyleSheet(styles.FORM_LABEL)
                label.setFixedWidth(120)
                param_row.addWidget(label)

                spin = QSpinBox()
                spin.setMinimum(param_def.get("min", 0))
                spin.setMaximum(param_def.get("max", 999))
                spin.setValue(param_def["default"])
                spin.setFixedWidth(100)
                spin.setStyleSheet(
                    f"QSpinBox {{ padding: 4px 8px; border: 1px solid {styles.COLOR_BORDER_INPUT}; "
                    f"border-radius: {styles.RADIUS_CTRL}; background: {styles.COLOR_BG_CARD}; "
                    f"color: {styles.COLOR_TEXT_DEFAULT}; font-size: 13px; }}"
                )
                param_row.addWidget(spin)
                param_row.addStretch()
                self._param_widgets[tool_id][param_def["name"]] = spin

                layout.addLayout(param_row)

            # 数据库路径输入
            self._db_widgets[tool_id] = {}
            for db_def in stage_def.get("databases", []):
                db_row = QHBoxLayout()
                db_row.setSpacing(8)
                db_row.setContentsMargins(24, 0, 0, 0)

                label = QLabel(f"  {db_def['label']}:")
                label.setStyleSheet(styles.FORM_LABEL)
                label.setFixedWidth(120)
                db_row.addWidget(label)

                db_input = QLineEdit()
                db_input.setPlaceholderText("输入远程数据库绝对路径")
                db_input.setStyleSheet(styles.INPUT_LINEEDIT)
                db_input.textChanged.connect(self._update_run_button_state)
                db_row.addWidget(db_input)
                self._db_widgets[tool_id][db_def["param_name"]] = db_input

                layout.addLayout(db_row)

        parent_layout.addWidget(card)

    # ── 运行按钮区 ────────────────────────────────────────────

    def _build_run_section(self, parent_layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        self._status_text = QLabel()
        self._status_text.setStyleSheet(styles.LABEL_HINT)
        row.addWidget(self._status_text, stretch=1)

        self._btn_run = QPushButton("运行流水线")
        self._btn_run.setStyleSheet(styles.BUTTON_SUCCESS)
        self._btn_run.setFixedHeight(40)
        self._btn_run.setFixedWidth(160)
        self._btn_run.clicked.connect(self._on_run_clicked)
        row.addWidget(self._btn_run)

        parent_layout.addLayout(row)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        """连接 ServiceLocator 信号"""
        locator = self._get_locator()
        if locator is None:
            return

        locator.execution_completed.connect(self._on_execution_completed)
        locator.execution_failed.connect(self._on_execution_failed)

    def _get_locator(self):
        """获取 ServiceLocator"""
        if self._main_window and hasattr(self._main_window, 'service_locator'):
            return self._main_window.service_locator
        return None

    # ── 事件处理 ──────────────────────────────────────────────

    def _browse_file(self, which: str) -> None:
        """打开文件选择对话框"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 FASTQ 文件", "",
            "FASTQ 文件 (*.fq *.fq.gz *.fastq *.fastq.gz);;所有文件 (*)",
        )
        if not path:
            return

        filename = Path(path).name
        if which == "r1":
            self._r1_path = path
            self._r1_path_label.setText(filename)
            self._r1_path_label.setStyleSheet(
                f"font-size: 12px; color: {styles.COLOR_TEXT_DEFAULT}; "
                f"background: {styles.COLOR_BG_BLANK};"
            )
        elif which == "r2":
            self._r2_path = path
            self._r2_path_label.setText(filename)
            self._r2_path_label.setStyleSheet(
                f"font-size: 12px; color: {styles.COLOR_TEXT_DEFAULT}; "
                f"background: {styles.COLOR_BG_BLANK};"
            )
        self._update_run_button_state()

    def _on_run_clicked(self) -> None:
        """运行流水线"""
        locator = self._get_locator()
        if locator is None:
            QMessageBox.warning(self, "错误", "服务未初始化")
            return

        ssh = locator.ssh_service
        if not ssh or not getattr(ssh, 'is_connected', False):
            QMessageBox.warning(self, "错误", "请先在设置页连接 SSH")
            return

        pm = locator.project_manager
        if pm.current_project is None:
            QMessageBox.warning(self, "错误", "请先选择或创建项目")
            return

        registry = locator.data_registry
        engine = locator.tool_engine
        if registry is None or engine is None:
            QMessageBox.warning(self, "错误", "请先打开项目")
            return

        sample_name = self._sample_name_input.text().strip()
        if not sample_name:
            QMessageBox.warning(self, "错误", "请输入样本名称")
            return

        if not self._r1_path:
            QMessageBox.warning(self, "错误", "请选择 R1 FASTQ 文件")
            return

        # 验证 kraken2 数据库路径
        k2_db = self._db_widgets.get("kraken2", {}).get("db")
        if k2_db and not k2_db.text().strip():
            QMessageBox.warning(self, "错误", "请输入 Kraken2 数据库路径")
            return

        try:
            self._running = True
            self._btn_run.setEnabled(False)
            self._btn_run.setText("运行中...")
            self._status_text.setText("正在导入数据...")

            # 1. 创建样本
            sample_id = registry.add_sample(sample_name)

            # 2. 导入文件
            from core.data_importer import DataImporter
            importer = DataImporter(ssh_service=ssh, registry=registry)

            data_ids = []
            data_id_r1 = importer.import_file(
                local_path=self._r1_path,
                sample_id=sample_id,
                data_type="fastq",
                project_remote_base=pm.current_project.remote_base,
            )
            data_ids.append(data_id_r1)

            if self._r2_path:
                data_id_r2 = importer.import_file(
                    local_path=self._r2_path,
                    sample_id=sample_id,
                    data_type="fastq",
                    project_remote_base=pm.current_project.remote_base,
                )
                data_ids.append(data_id_r2)

            # 3. 收集参数
            self._status_text.setText("正在启动流水线...")

            # 4. 创建 PipelineRunner 并运行
            from core.pipeline_runner import PipelineRunner, PipelineStage

            stages = []
            for stage_def in _PIPELINE_STAGES:
                tool_id = stage_def["tool_id"]
                params = {}
                for pname, spin in self._param_widgets.get(tool_id, {}).items():
                    params[pname] = spin.value()

                db_paths = {}
                for dbname, line_edit in self._db_widgets.get(tool_id, {}).items():
                    val = line_edit.text().strip()
                    if val:
                        db_paths[dbname] = val

                stages.append(PipelineStage(
                    tool_id=tool_id,
                    parameters=params,
                    database_paths=db_paths,
                    input_type=stage_def.get("input_type", "fastq"),
                ))

            runner = PipelineRunner(
                tool_engine=engine,
                data_registry=registry,
            )
            runner.stage_completed.connect(self._on_stage_completed)
            runner.pipeline_completed.connect(self._on_pipeline_completed)
            runner.pipeline_failed.connect(self._on_pipeline_failed)

            # 重置阶段状态
            for sw in self._stage_widgets:
                sw.set_status(STATUS_PENDING)
            if self._stage_widgets:
                self._stage_widgets[0].set_status(STATUS_RUNNING)

            self._pipeline_run_id = runner.run(stages, sample_id, data_ids)
            self._status_text.setText(f"流水线已启动: {self._pipeline_run_id}")

        except Exception as e:
            logger.exception("启动流水线失败")
            QMessageBox.critical(self, "启动失败", str(e))
            self._running = False
            self._btn_run.setEnabled(True)
            self._btn_run.setText("运行流水线")
            self._status_text.setText(f"启动失败: {e}")

    def _on_stage_completed(self, run_id: str, stage_idx: int, total: int) -> None:
        """阶段完成回调"""
        if run_id != self._pipeline_run_id:
            return

        if stage_idx < len(self._stage_widgets):
            self._stage_widgets[stage_idx].set_status(STATUS_COMPLETED)

        # 下一阶段设为运行中
        next_idx = stage_idx + 1
        if next_idx < len(self._stage_widgets) and next_idx < total:
            self._stage_widgets[next_idx].set_status(STATUS_RUNNING)

        self._status_text.setText(f"阶段 {stage_idx + 1}/{total} 已完成")

    def _on_pipeline_completed(self, run_id: str) -> None:
        """流水线完成"""
        if run_id != self._pipeline_run_id:
            return

        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_run.setText("运行流水线")
        self._status_text.setText("流水线执行完成！")
        self._status_text.setStyleSheet(styles.STATUS_SUCCESS)

        # 所有阶段标记完成
        for sw in self._stage_widgets:
            sw.set_status(STATUS_COMPLETED)

        # 刷新执行历史
        self._refresh_execution_history()

    def _on_pipeline_failed(self, run_id: str, stage_idx: int, error: str) -> None:
        """流水线失败"""
        if run_id != self._pipeline_run_id:
            return

        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_run.setText("运行流水线")
        self._status_text.setText(f"阶段 {stage_idx + 1} 失败: {error}")
        self._status_text.setStyleSheet(styles.STATUS_ERROR)

        if stage_idx < len(self._stage_widgets):
            self._stage_widgets[stage_idx].set_status(STATUS_FAILED)

        # 刷新执行历史
        self._refresh_execution_history()

    def _on_execution_completed(self, execution_id: str) -> None:
        """ToolEngine 完成信号（通过 ServiceLocator 转发）"""
        pass  # PipelineRunner 内部处理

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        """ToolEngine 失败信号"""
        pass  # PipelineRunner 内部处理

    # ── Risk 3 缓解: 按钮状态管理 ─────────────────────────────

    def _update_run_button_state(self, *_args) -> None:
        """更新运行按钮状态 — SSH + 项目 + 数据全部就绪才启用"""
        if self._running:
            self._btn_run.setEnabled(False)
            return

        reasons: list[str] = []

        # 检查样本名称
        if not self._sample_name_input.text().strip():
            reasons.append("输入样本名称")

        # 检查 R1 文件
        if not self._r1_path:
            reasons.append("选择 R1 文件")

        # 检查 kraken2 数据库
        k2_db = self._db_widgets.get("kraken2", {}).get("db")
        if k2_db and not k2_db.text().strip():
            reasons.append("输入 Kraken2 数据库路径")

        # 检查 SSH 连接
        locator = self._get_locator()
        if locator:
            ssh = locator.ssh_service
            if not ssh or not getattr(ssh, 'is_connected', False):
                reasons.append("连接 SSH")
            pm = locator.project_manager
            if pm.current_project is None:
                reasons.append("选择项目")

        if reasons:
            self._btn_run.setEnabled(False)
            self._status_text.setText("请先: " + "、".join(reasons))
            self._status_text.setStyleSheet(styles.LABEL_HINT)
        else:
            self._btn_run.setEnabled(True)
            self._status_text.setText("就绪，点击运行")
            self._status_text.setStyleSheet(styles.STATUS_SUCCESS)

    # ── 执行历史 ──────────────────────────────────────────────

    def _refresh_execution_history(self) -> None:
        """刷新执行历史卡片的数据库连接和内容"""
        locator = self._get_locator()
        if locator is None:
            return
        pm = locator.project_manager
        if pm and pm.current_project is not None:
            try:
                self._execution_history.set_db_connection(pm.db)
            except Exception:
                self._execution_history.refresh()
        else:
            self._execution_history.refresh()
