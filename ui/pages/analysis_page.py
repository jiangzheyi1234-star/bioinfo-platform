"""分析工作台（向导优先）：按 analysis_paths.yaml 动态构建 read_based 流程。"""

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import QColor

from core.pipeline.pipeline_runner import PipelineRunner, PipelineStage
from ui.widgets import styles
from ui.widgets.chart_widget import ResultsPanel
from ui.widgets.execution_history_card import ExecutionHistoryCard
from ui.widgets.stage_status_widget import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    StageStatusWidget,
)

logger = logging.getLogger(__name__)


class AnalysisPage(QFrame):
    """按 read_based 路径执行 fastp -> hostile -> kraken2 等流程。"""

    def __init__(self, main_window: Any = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._main_window = main_window

        self._running = False
        self._pipeline_run_id: Optional[str] = None
        self._runner: Optional[PipelineRunner] = None

        self._pipeline_stages: list[dict[str, Any]] = []
        self._stage_widgets: list[StageStatusWidget] = []
        self._param_widgets: dict[str, dict[str, QWidget]] = {}
        self._db_widgets: dict[str, dict[str, QLineEdit]] = {}

        self._selected_sample_id: Optional[str] = None
        self._selected_project_id: Optional[str] = None
        self._r1_path: Optional[str] = None
        self._r2_path: Optional[str] = None

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self._load_pipeline_definitions(path_id="read_based")
        self._build_ui()
        self._connect_signals()
        self.refresh_context()

    def _get_locator(self):
        if self._main_window and hasattr(self._main_window, "service_locator"):
            return self._main_window.service_locator
        return None

    def _analysis_paths_file(self) -> Path:
        return Path(__file__).resolve().parents[2] / "plugins" / "analysis_paths.yaml"

    def _load_pipeline_definitions(self, path_id: str) -> None:
        self._pipeline_stages = []

        locator = self._get_locator()
        reg = locator.plugin_registry if locator else None

        stages: list[dict[str, Any]] = []
        try:
            with self._analysis_paths_file().open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            stages = ((data.get("paths", {}).get(path_id) or {}).get("stages") or [])
        except Exception:
            logger.exception("读取 analysis_paths.yaml 失败，回退为空流程")
            stages = []

        for stage in stages:
            tool_id = stage.get("tool_id")
            if not tool_id:
                continue

            descriptor = {}
            if reg is not None:
                try:
                    descriptor = reg.get_descriptor(tool_id)
                except Exception:
                    logger.warning("插件未找到或读取失败: %s", tool_id)

            self._pipeline_stages.append(
                {
                    "tool_id": tool_id,
                    "name": descriptor.get("name", tool_id),
                    "input_type": stage.get("input_type", "fastq"),
                    "required": stage.get("required", True),
                    "parameters": descriptor.get("parameters", []),
                    "databases": descriptor.get("databases", []),
                }
            )

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 20, 30, 20)
        main_layout.setSpacing(16)

        title = QLabel("分析工作台")
        title.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {styles.COLOR_TEXT_TITLE};"
            "background: transparent; letter-spacing: -0.5px;"
        )
        main_layout.addWidget(title)

        desc = QLabel("按预设路径执行分析流程，参数与数据库字段来自插件定义。")
        desc.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        main_layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.verticalScrollBar().setStyleSheet(styles.SCROLL_BAR_ELEGANT)

        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(16)

        self._build_sample_section(layout)
        self._build_pipeline_section(layout)
        self._build_run_section(layout)

        self._execution_history = ExecutionHistoryCard()
        layout.addWidget(self._execution_history)

        self._results_panel = ResultsPanel()
        layout.addWidget(self._results_panel)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

    def _build_sample_section(self, parent_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("SampleCard")
        card.setStyleSheet(f"""
            QFrame#SampleCard {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
            }}
        """)
        styles.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        title = QLabel("样本输入")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {styles.COLOR_TEXT_TITLE}; background: transparent;"
        )
        layout.addWidget(title)

        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_label = QLabel("样本名:")
        name_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        name_label.setMinimumWidth(80)
        name_row.addWidget(name_label)

        self._sample_name_input = QLineEdit()
        self._sample_name_input.setPlaceholderText("例如 WaterSample01")
        self._sample_name_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._sample_name_input.textChanged.connect(self._on_sample_name_changed)
        name_row.addWidget(self._sample_name_input)
        layout.addLayout(name_row)

        file_row = QHBoxLayout()
        file_row.setSpacing(10)
        file_label = QLabel("R1 文件:")
        file_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        file_label.setMinimumWidth(80)
        file_row.addWidget(file_label)

        self._r1_path_label = QLabel("未选择")
        self._r1_path_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        file_row.addWidget(self._r1_path_label, stretch=1)

        self._btn_browse_r1 = QPushButton("浏览...")
        self._btn_browse_r1.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_browse_r1.clicked.connect(lambda: self._browse_file("r1"))
        file_row.addWidget(self._btn_browse_r1)
        layout.addLayout(file_row)

        file_row2 = QHBoxLayout()
        file_row2.setSpacing(10)
        file_label2 = QLabel("R2 文件:")
        file_label2.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        file_label2.setMinimumWidth(80)
        file_row2.addWidget(file_label2)

        self._r2_path_label = QLabel("未选择（单端可留空）")
        self._r2_path_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        file_row2.addWidget(self._r2_path_label, stretch=1)

        self._btn_browse_r2 = QPushButton("浏览...")
        self._btn_browse_r2.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_browse_r2.clicked.connect(lambda: self._browse_file("r2"))
        file_row2.addWidget(self._btn_browse_r2)
        layout.addLayout(file_row2)

        parent_layout.addWidget(card)

    def _create_param_widget(self, param: dict[str, Any]) -> QWidget:
        ptype = str(param.get("type", "string"))
        default = param.get("default")

        if ptype == "int":
            w = QSpinBox()
            value_range = param.get("range", [1, 9999])
            if isinstance(value_range, list) and len(value_range) == 2:
                w.setRange(int(value_range[0]), int(value_range[1]))
            else:
                w.setRange(1, 9999)
            if default is not None:
                w.setValue(int(default))
            w.setMinimumWidth(120)
            return w

        if ptype == "float":
            w = QDoubleSpinBox()
            w.setDecimals(6)
            value_range = param.get("range", [0.0, 1000000.0])
            if isinstance(value_range, list) and len(value_range) == 2:
                w.setRange(float(value_range[0]), float(value_range[1]))
            else:
                w.setRange(0.0, 1000000.0)
            if default is not None:
                w.setValue(float(default))
            w.setMinimumWidth(140)
            return w

        if ptype == "bool":
            w = QComboBox()
            w.addItem("是", True)
            w.addItem("否", False)
            if bool(default) is False:
                w.setCurrentIndex(1)
            w.setStyleSheet(styles.INPUT_COMBOBOX)
            w.setMinimumWidth(120)
            return w

        if ptype == "choice":
            w = QComboBox()
            choices = param.get("choices", [])
            for c in choices:
                w.addItem(str(c), c)
            if default in choices:
                w.setCurrentIndex(choices.index(default))
            w.setStyleSheet(styles.INPUT_COMBOBOX)
            w.setMinimumWidth(160)
            return w

        w = QLineEdit()
        w.setText("" if default is None else str(default))
        w.setStyleSheet(styles.INPUT_LINEEDIT)
        w.setMinimumWidth(220)
        return w

    def _read_param_widget(self, widget: QWidget) -> Any:
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return None

    def _build_pipeline_section(self, parent_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("PipelineCard")
        card.setStyleSheet(f"""
            QFrame#PipelineCard {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
            }}
        """)
        styles.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        title = QLabel("流程配置（来自插件）")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {styles.COLOR_TEXT_TITLE}; background: transparent;"
        )
        layout.addWidget(title)

        self._stage_widgets = []
        self._param_widgets = {}
        self._db_widgets = {}

        for i, stage in enumerate(self._pipeline_stages):
            tool_id = stage["tool_id"]
            stage_widget = StageStatusWidget(tool_id=tool_id, tool_name=stage["name"], stage_index=i)
            self._stage_widgets.append(stage_widget)
            layout.addWidget(stage_widget)

            self._param_widgets[tool_id] = {}
            for p in stage.get("parameters", []):
                row = QHBoxLayout()
                row.setSpacing(10)
                row.setContentsMargins(24, 0, 0, 0)

                label = QLabel(f"  {p.get('label') or p.get('name')}: ")
                label.setStyleSheet(
                    f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
                )
                label.setMinimumWidth(160)
                row.addWidget(label)

                widget = self._create_param_widget(p)
                row.addWidget(widget)
                row.addStretch()
                self._param_widgets[tool_id][p["name"]] = widget
                layout.addLayout(row)

            self._db_widgets[tool_id] = {}
            for db in stage.get("databases", []):
                row = QHBoxLayout()
                row.setSpacing(10)
                row.setContentsMargins(24, 0, 0, 0)

                pname = db.get("param_name")
                label = QLabel(f"  数据库({pname}):")
                label.setStyleSheet(
                    f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
                )
                label.setMinimumWidth(160)
                row.addWidget(label)

                db_input = QLineEdit()
                db_input.setPlaceholderText("请输入远端数据库路径")
                db_input.setStyleSheet(styles.INPUT_LINEEDIT)
                db_input.textChanged.connect(self._update_run_button_state)
                row.addWidget(db_input)

                self._db_widgets[tool_id][str(pname)] = db_input
                layout.addLayout(row)

        parent_layout.addWidget(card)

    def _build_run_section(self, parent_layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        self._status_text = QLabel()
        self._status_text.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        row.addWidget(self._status_text, stretch=1)

        self._btn_run = QPushButton("运行流程")
        self._btn_run.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7DD3FC, stop:1 #38BDF8);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #BAE6FD, stop:1 #7DD3FC);
            }}
            QPushButton:pressed {{
                background: #0EA5E9;
            }}
            QPushButton:disabled {{
                background: #E2E8F0;
                color: #94A3B8;
            }}
        """)
        self._btn_run.setMinimumHeight(42)
        self._btn_run.setMinimumWidth(160)
        self._btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_run.clicked.connect(self._on_run_clicked)
        row.addWidget(self._btn_run)

        parent_layout.addLayout(row)

    def _connect_signals(self) -> None:
        locator = self._get_locator()
        if locator is None:
            return
        locator.execution_completed.connect(self._on_execution_completed)
        locator.execution_failed.connect(self._on_execution_failed)

    def _browse_file(self, which: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 FASTQ 文件",
            "",
            "FASTQ 文件 (*.fq *.fq.gz *.fastq *.fastq.gz);;所有文件 (*)",
        )
        if not path:
            return

        self._selected_sample_id = None
        if which == "r1":
            self._r1_path = path
            self._set_path_label(self._r1_path_label, path, "未选择")
        elif which == "r2":
            self._r2_path = path
            self._set_path_label(self._r2_path_label, path, "未选择（单端可留空）")

        self.refresh_context()

    def _on_run_clicked(self) -> None:
        locator = self._get_locator()
        if locator is None:
            QMessageBox.warning(self, "错误", "未初始化服务容器")
            return

        ssh = locator.ssh_service
        if not ssh or not getattr(ssh, "is_connected", False):
            QMessageBox.warning(self, "错误", "请先连接 SSH")
            return

        pm = locator.project_manager
        if pm.current_project is None:
            QMessageBox.warning(self, "错误", "请先打开项目")
            return

        registry = locator.data_registry
        engine = locator.tool_engine
        if registry is None or engine is None:
            QMessageBox.warning(self, "错误", "请先打开项目")
            return

        sample_name = self._sample_name_input.text().strip()
        if not sample_name:
            QMessageBox.warning(self, "错误", "请输入样本名")
            return

        if not self._r1_path:
            QMessageBox.warning(self, "错误", "请选择 R1 FASTQ 文件")
            return

        for stage in self._pipeline_stages:
            for db in stage.get("databases", []):
                pname = str(db.get("param_name"))
                required = bool(db.get("required", False))
                if not required:
                    continue
                widget = self._db_widgets.get(stage["tool_id"], {}).get(pname)
                if widget and not widget.text().strip():
                    QMessageBox.warning(self, "错误", f"请填写数据库路径: {stage['name']} / {pname}")
                    return

        try:
            self._running = True
            self._btn_run.setEnabled(False)
            self._btn_run.setText("运行中...")
            self._status_text.setText("正在上传输入文件...")
            self._results_panel.reset()

            sample_id = self._selected_sample_id
            if sample_id:
                existing = registry.get_sample(sample_id)
                if existing is None:
                    sample_id = None

            if sample_id is None:
                sample_id = registry.add_sample(
                    sample_name,
                    metadata={"r1": self._r1_path, "r2": self._r2_path},
                )
                self._selected_sample_id = sample_id

            from core.data.data_importer import DataImporter

            importer = DataImporter(ssh_service=ssh, registry=registry)
            data_ids = []
            data_ids.append(
                importer.import_file(
                    local_path=self._r1_path,
                    sample_id=sample_id,
                    data_type="fastq",
                    project_remote_base=pm.current_project.remote_base,
                )
            )
            if self._r2_path:
                data_ids.append(
                    importer.import_file(
                        local_path=self._r2_path,
                        sample_id=sample_id,
                        data_type="fastq",
                        project_remote_base=pm.current_project.remote_base,
                    )
                )

            stages: list[PipelineStage] = []
            for stage in self._pipeline_stages:
                tool_id = stage["tool_id"]
                params = {
                    k: self._read_param_widget(w)
                    for k, w in self._param_widgets.get(tool_id, {}).items()
                }
                db_paths: dict[str, str] = {}
                for name, line_edit in self._db_widgets.get(tool_id, {}).items():
                    v = line_edit.text().strip()
                    if v:
                        db_paths[name] = v

                stages.append(
                    PipelineStage(
                        tool_id=tool_id,
                        parameters=params,
                        database_paths=db_paths,
                        input_type=str(stage.get("input_type", "fastq")),
                        required=bool(stage.get("required", True)),
                    )
                )

            self._runner = PipelineRunner(tool_engine=engine, data_registry=registry)
            self._runner.stage_completed.connect(self._on_stage_completed)
            self._runner.pipeline_completed.connect(self._on_pipeline_completed)
            self._runner.pipeline_failed.connect(self._on_pipeline_failed)

            for sw in self._stage_widgets:
                sw.set_status(STATUS_PENDING)
            if self._stage_widgets:
                self._stage_widgets[0].set_status(STATUS_RUNNING)

            self._pipeline_run_id = self._runner.run(stages, sample_id, data_ids)
            self._status_text.setText(f"流程已提交: {self._pipeline_run_id}")

        except Exception as e:
            logger.exception("提交流程失败")
            QMessageBox.critical(self, "提交失败", str(e))
            self._running = False
            self._btn_run.setEnabled(True)
            self._btn_run.setText("运行流程")
            self._status_text.setText(f"提交失败: {e}")

    def _on_stage_completed(self, run_id: str, stage_idx: int, total: int) -> None:
        if run_id != self._pipeline_run_id:
            return

        if stage_idx < len(self._stage_widgets):
            self._stage_widgets[stage_idx].set_status(STATUS_COMPLETED)

        next_idx = stage_idx + 1
        if next_idx < len(self._stage_widgets) and next_idx < total:
            self._stage_widgets[next_idx].set_status(STATUS_RUNNING)

        self._status_text.setText(f"阶段 {stage_idx + 1}/{total} 完成")

    def _on_pipeline_completed(self, run_id: str) -> None:
        if run_id != self._pipeline_run_id:
            return

        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_run.setText("运行流程")
        self._status_text.setText("流程执行完成")
        self._status_text.setStyleSheet(styles.STATUS_SUCCESS)

        for sw in self._stage_widgets:
            sw.set_status(STATUS_COMPLETED)

        self._refresh_execution_history()
        self._load_pipeline_results()

    def _on_pipeline_failed(self, run_id: str, stage_idx: int, error: str) -> None:
        if run_id != self._pipeline_run_id:
            return

        self._running = False
        self._btn_run.setEnabled(True)
        self._btn_run.setText("运行流程")
        self._status_text.setText(f"阶段 {stage_idx + 1} 失败: {error}")
        self._status_text.setStyleSheet(styles.STATUS_ERROR)

        if stage_idx < len(self._stage_widgets):
            self._stage_widgets[stage_idx].set_status(STATUS_FAILED)

        self._refresh_execution_history()

    def _on_execution_completed(self, execution_id: str) -> None:
        _ = execution_id

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        _ = (execution_id, error)

    def _load_pipeline_results(self) -> None:
        """流程完成后，下载 fastp json 和 kraken2 kreport 并加载结果图表。"""
        locator = self._get_locator()
        if not locator:
            return
        sample_id = self._selected_sample_id
        if not sample_id:
            return

        registry = locator.data_registry
        ssh = locator.ssh_service
        if registry is None or ssh is None:
            return

        pm = locator.project_manager
        if pm is None or pm.current_project is None:
            return

        project_dir = pm._projects_root / pm.current_project.project_id
        dl_dir = project_dir / "downloads" / sample_id
        dl_dir.mkdir(parents=True, exist_ok=True)

        fastp_local = self._download_latest(
            registry, ssh, sample_id, "json", dl_dir
        )
        kreport_local = self._download_latest(
            registry, ssh, sample_id, "kreport", dl_dir
        )
        self._results_panel.load_results(fastp_local, kreport_local)

    def _download_latest(
        self, registry, ssh, sample_id: str, data_type: str, dl_dir: Path
    ) -> Optional[str]:
        """下载指定类型的最新数据项到本地目录，返回本地路径。"""
        items = registry.find_compatible(sample_id, data_type)
        if not items:
            return None
        remote_path = items[0].file_path
        file_name = Path(remote_path).name
        local_path = dl_dir / file_name
        try:
            ssh.download(remote_path, str(local_path))
            return str(local_path)
        except Exception:
            logger.exception("下载 %s 失败: %s", data_type, remote_path)
            return None

    def _on_sample_name_changed(self, *_args) -> None:
        if self._selected_sample_id is not None:
            self._selected_sample_id = None
        self._update_run_button_state()

    def _update_run_button_state(self, *_args) -> None:
        if self._running:
            self._btn_run.setEnabled(False)
            return

        reasons: list[str] = []

        if not self._sample_name_input.text().strip():
            reasons.append("输入样本名")
        if not self._r1_path:
            reasons.append("选择 R1 文件")

        locator = self._get_locator()
        if locator:
            ssh = locator.ssh_service
            if not ssh or not getattr(ssh, "is_connected", False):
                reasons.append("连接 SSH")
            if locator.project_manager.current_project is None:
                reasons.append("打开项目")

        for stage in self._pipeline_stages:
            for db in stage.get("databases", []):
                pname = str(db.get("param_name"))
                required = bool(db.get("required", False))
                if not required:
                    continue
                widget = self._db_widgets.get(stage["tool_id"], {}).get(pname)
                if widget and not widget.text().strip():
                    reasons.append(f"填写数据库: {stage['name']}")

        if reasons:
            self._btn_run.setEnabled(False)
            self._status_text.setText("请先: " + "、".join(reasons))
            self._status_text.setStyleSheet(styles.LABEL_HINT)
        else:
            self._btn_run.setEnabled(True)
            self._status_text.setText("已就绪，可执行流程")
            self._status_text.setStyleSheet(styles.STATUS_SUCCESS)

    def set_sample_context(
        self,
        sample_id: str,
        sample_name: str,
        r1_path: Optional[str],
        r2_path: Optional[str] = None,
    ) -> None:
        """从首页复用现有样本上下文，避免重复建样本。"""
        self._selected_sample_id = sample_id
        self._sample_name_input.blockSignals(True)
        self._sample_name_input.setText(sample_name)
        self._sample_name_input.blockSignals(False)
        self._r1_path = r1_path or None
        self._r2_path = r2_path or None
        self._set_path_label(self._r1_path_label, self._r1_path, "未选择")
        self._set_path_label(self._r2_path_label, self._r2_path, "未选择（单端可留空）")
        self._update_run_button_state()

    def clear_sample_context(self) -> None:
        self._selected_sample_id = None
        self._sample_name_input.blockSignals(True)
        self._sample_name_input.clear()
        self._sample_name_input.blockSignals(False)
        self._r1_path = None
        self._r2_path = None
        self._set_path_label(self._r1_path_label, None, "未选择")
        self._set_path_label(self._r2_path_label, None, "未选择（单端可留空）")

    def refresh_context(self) -> None:
        locator = self._get_locator()
        project_id = None
        if locator and locator.project_manager.current_project is not None:
            project_id = locator.project_manager.current_project.project_id

        if project_id != self._selected_project_id:
            if self._selected_project_id is not None:
                self.clear_sample_context()
            self._selected_project_id = project_id

        self._refresh_execution_history()
        self._update_run_button_state()

    def _refresh_execution_history(self) -> None:
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

    def _set_path_label(self, label: QLabel, path: Optional[str], placeholder: str) -> None:
        if path:
            label.setText(Path(path).name)
            label.setStyleSheet(
                f"font-size: 12px; color: {styles.COLOR_TEXT_DEFAULT};"
                f"background: {styles.COLOR_BG_BLANK};"
            )
            return

        label.setText(placeholder)
        label.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_HINT};"
            f"background: {styles.COLOR_BG_BLANK};"
        )
