"""组装分析页：按 analysis_paths.yaml 的 assembly_based 路径动态构建流程。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
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
from PyQt6.QtGui import QColor

from core.pipeline.pipeline_runner import PipelineRunner, PipelineStage
from ui.page_base import BasePage
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


class _StageEditorCard(QGroupBox):
    """单阶段配置卡：可替换同类工具，参数/数据库字段动态生成。"""

    selection_changed = pyqtSignal()

    def __init__(
        self,
        title: str,
        default_tool_id: str,
        required: bool,
        tool_choices: list[tuple[str, str]],
        descriptor_provider,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(title, parent)
        self._required = required
        self._default_tool_id = default_tool_id
        self._descriptor_provider = descriptor_provider
        self._param_widgets: dict[str, QWidget] = {}
        self._db_widgets: dict[str, QLineEdit] = {}

        self.setStyleSheet(
            f"""
            QGroupBox {{
                font-weight: 600;
                font-size: 13px;
                color: {styles.COLOR_TEXT_TITLE};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
                margin-top: 8px;
                padding-top: 12px;
                background: {styles.COLOR_BG_CARD};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {styles.COLOR_TEXT_TITLE};
                background: {styles.COLOR_BG_CARD};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 12)
        root.setSpacing(10)

        tool_row = QHBoxLayout()
        tool_label = QLabel("工具")
        tool_label.setStyleSheet(styles.FORM_LABEL)
        tool_label.setMinimumWidth(80)
        tool_row.addWidget(tool_label)

        self.tool_combo = QComboBox()
        self.tool_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        if not required:
            self.tool_combo.addItem("跳过该阶段", None)

        for tool_id, name in tool_choices:
            self.tool_combo.addItem(name, tool_id)

        default_index = self.tool_combo.findData(default_tool_id)
        if default_index >= 0:
            self.tool_combo.setCurrentIndex(default_index)

        self.tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        tool_row.addWidget(self.tool_combo, stretch=1)
        root.addLayout(tool_row)

        self._fields_container = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_container)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(6)
        root.addWidget(self._fields_container)

        self._on_tool_changed()

        # 添加卡片阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

    @property
    def selected_tool_id(self) -> Optional[str]:
        value = self.tool_combo.currentData()
        if value is None:
            return None
        return str(value)

    @property
    def selected_tool_name(self) -> str:
        return self.tool_combo.currentText()

    def _clear_fields(self) -> None:
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self._param_widgets.clear()
        self._db_widgets.clear()

    def _create_param_widget(self, param_def: dict[str, Any]) -> QWidget:
        ptype = str(param_def.get("type", "string"))
        default = param_def.get("default")

        if ptype == "int":
            spin = QSpinBox()
            value_range = param_def.get("range", [1, 9999])
            if isinstance(value_range, list) and len(value_range) == 2:
                spin.setRange(int(value_range[0]), int(value_range[1]))
            else:
                spin.setRange(1, 9999)
            if default is not None:
                spin.setValue(int(default))
            spin.setMinimumWidth(140)
            return spin

        if ptype == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            value_range = param_def.get("range", [0.0, 1000000.0])
            if isinstance(value_range, list) and len(value_range) == 2:
                spin.setRange(float(value_range[0]), float(value_range[1]))
            else:
                spin.setRange(0.0, 1000000.0)
            if default is not None:
                spin.setValue(float(default))
            spin.setMinimumWidth(160)
            return spin

        if ptype == "bool":
            combo = QComboBox()
            combo.setStyleSheet(styles.INPUT_COMBOBOX)
            combo.addItem("是", True)
            combo.addItem("否", False)
            if default is False:
                combo.setCurrentIndex(1)
            combo.setMinimumWidth(120)
            return combo

        if ptype == "choice":
            combo = QComboBox()
            combo.setStyleSheet(styles.INPUT_COMBOBOX)
            choices = param_def.get("choices", [])
            for choice in choices:
                combo.addItem(str(choice), choice)
            if default in choices:
                combo.setCurrentIndex(choices.index(default))
            combo.setMinimumWidth(180)
            return combo

        line_edit = QLineEdit()
        line_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        line_edit.setText("" if default is None else str(default))
        return line_edit

    def _read_widget_value(self, widget: QWidget) -> Any:
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return None

    def _on_tool_changed(self) -> None:
        self._clear_fields()

        tool_id = self.selected_tool_id
        if tool_id is None:
            self.selection_changed.emit()
            return

        try:
            descriptor = self._descriptor_provider(tool_id)
        except Exception:
            logger.exception("读取插件描述失败: %s", tool_id)
            self.selection_changed.emit()
            return

        for param_def in descriptor.get("parameters", []):
            row = QHBoxLayout()
            row.setSpacing(8)

            label_text = str(param_def.get("label") or param_def.get("name") or "参数")
            label = QLabel(label_text)
            label.setStyleSheet(styles.FORM_LABEL)
            label.setMinimumWidth(160)
            row.addWidget(label)

            widget = self._create_param_widget(param_def)
            row.addWidget(widget)
            row.addStretch()
            self._fields_layout.addLayout(row)

            name = str(param_def.get("name") or "")
            if name:
                self._param_widgets[name] = widget

        for db_def in descriptor.get("databases", []):
            row = QHBoxLayout()
            row.setSpacing(8)

            param_name = str(db_def.get("param_name") or "")
            required = bool(db_def.get("required", False))
            label = QLabel(f"数据库({param_name}){' *' if required else ''}")
            label.setStyleSheet(styles.FORM_LABEL)
            label.setMinimumWidth(160)
            row.addWidget(label)

            line_edit = QLineEdit()
            line_edit.setStyleSheet(styles.INPUT_LINEEDIT)
            line_edit.setPlaceholderText("请输入远端数据库路径")
            line_edit.textChanged.connect(self.selection_changed.emit)
            row.addWidget(line_edit)

            self._fields_layout.addLayout(row)
            self._db_widgets[param_name] = line_edit

        self.selection_changed.emit()

    def get_stage_parameters(self) -> dict[str, Any]:
        return {name: self._read_widget_value(widget) for name, widget in self._param_widgets.items()}

    def get_stage_database_paths(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name, widget in self._db_widgets.items():
            text = widget.text().strip()
            if text:
                values[name] = text
        return values

    def validate_required_databases(self) -> list[str]:
        tool_id = self.selected_tool_id
        if tool_id is None:
            return []

        missing: list[str] = []
        descriptor = self._descriptor_provider(tool_id)
        for db_def in descriptor.get("databases", []):
            if not bool(db_def.get("required", False)):
                continue
            param_name = str(db_def.get("param_name") or "")
            widget = self._db_widgets.get(param_name)
            if widget and not widget.text().strip():
                missing.append(param_name)
        return missing


class AssemblyPage(BasePage):
    """组装分析页：按路径驱动阶段，支持同类工具替换。"""

    def __init__(self, main_window=None):
        super().__init__("组装分析")
        if hasattr(self, "label"):
            self.label.hide()

        self.main_window = main_window
        self._runner: Optional[PipelineRunner] = None
        self._pipeline_run_id: Optional[str] = None
        self._active_stage_ui_indices: list[int] = []

        self._path_stages: list[dict[str, Any]] = []
        self._stage_cards: list[_StageEditorCard] = []
        self._stage_widgets: list[StageStatusWidget] = []

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")

        self._load_path_definitions()
        self._build_ui()
        self.refresh_context()

    def _get_locator(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator
        return None

    def _analysis_paths_file(self) -> Path:
        return Path(__file__).resolve().parents[2] / "plugins" / "analysis_paths.yaml"

    def _descriptor(self, tool_id: str) -> dict[str, Any]:
        locator = self._get_locator()
        if locator is None or locator.plugin_registry is None:
            return {"id": tool_id, "name": tool_id, "parameters": [], "databases": [], "category": "unknown"}
        return locator.plugin_registry.get_descriptor(tool_id)

    def _load_path_definitions(self) -> None:
        self._path_stages = []
        locator = self._get_locator()
        reg = locator.plugin_registry if locator else None

        try:
            with self._analysis_paths_file().open("r", encoding="utf-8") as f:
                root = yaml.safe_load(f) or {}
            path_def = (root.get("paths", {}).get("assembly_based") or {})
            raw_stages = path_def.get("stages") or []
        except Exception:
            logger.exception("读取 analysis_paths.yaml 失败")
            raw_stages = []

        for stage in raw_stages:
            default_tool_id = str(stage.get("tool_id") or "").strip()
            if not default_tool_id:
                continue

            try:
                descriptor = self._descriptor(default_tool_id)
            except Exception:
                logger.exception("读取默认工具描述失败: %s", default_tool_id)
                descriptor = {"id": default_tool_id, "name": default_tool_id, "category": "unknown"}

            category = str(descriptor.get("category") or "unknown")
            tool_choices: list[tuple[str, str]] = []
            if reg is not None and category and category != "unknown":
                for entry in reg.list_by_category(category):
                    tool_choices.append((entry["id"], str(entry.get("name") or entry["id"])))

            if not any(tool_id == default_tool_id for tool_id, _ in tool_choices):
                tool_choices.insert(0, (default_tool_id, str(descriptor.get("name") or default_tool_id)))

            # 默认工具排在首位
            tool_choices.sort(key=lambda item: 0 if item[0] == default_tool_id else 1)

            display_name = str(descriptor.get("name") or default_tool_id)
            stage_title = str(stage.get("description") or display_name)

            self._path_stages.append(
                {
                    "title": stage_title,
                    "default_tool_id": default_tool_id,
                    "default_tool_name": display_name,
                    "input_type": str(stage.get("input_type") or "fastq"),
                    "required": bool(stage.get("required", True)),
                    "tool_choices": tool_choices,
                }
            )

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel("组装分析工作台")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        header_row.addWidget(header)
        header_row.addStretch()
        self.layout.addLayout(header_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(styles.DIVIDER)
        self.layout.addWidget(line)

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

        content_layout.addWidget(self._build_sample_group())

        path_title = QLabel("流程阶段（路径驱动 + 同类工具替换）")
        path_title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {styles.COLOR_TEXT_TITLE};"
            f" background: transparent;"
        )
        content_layout.addWidget(path_title)

        self._stage_cards.clear()
        self._stage_widgets.clear()

        for idx, stage in enumerate(self._path_stages):
            stage_widget = StageStatusWidget(
                tool_id=stage["default_tool_id"],
                tool_name=stage["default_tool_name"],
                stage_index=idx,
            )
            self._stage_widgets.append(stage_widget)
            content_layout.addWidget(stage_widget)

            card = _StageEditorCard(
                title=f"第 {idx + 1} 步：{stage['title']}",
                default_tool_id=stage["default_tool_id"],
                required=stage["required"],
                tool_choices=stage["tool_choices"],
                descriptor_provider=self._descriptor,
            )
            card.selection_changed.connect(lambda _=None, i=idx: self._on_stage_selection_changed(i))
            card.selection_changed.connect(self._update_run_state)
            self._stage_cards.append(card)
            content_layout.addWidget(card)

        run_row = QHBoxLayout()
        run_row.addStretch()
        self._run_btn = QPushButton("启动组装流程")
        self._run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._on_run)
        run_row.addWidget(self._run_btn)
        content_layout.addLayout(run_row)

        self._status_label = QLabel("请先打开项目并选择样本")
        self._status_label.setStyleSheet(styles.LABEL_HINT)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(self._status_label)

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

    def _build_sample_group(self) -> QGroupBox:
        sample_group = QGroupBox("样本输入")
        sample_group.setStyleSheet(
            f"""
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
        )

        inner = QVBoxLayout(sample_group)
        inner.setContentsMargins(14, 8, 14, 12)

        row = QHBoxLayout()
        sample_lbl = QLabel("选择样本")
        sample_lbl.setStyleSheet(styles.FORM_LABEL)
        sample_lbl.setMinimumWidth(80)
        row.addWidget(sample_lbl)

        self._sample_combo = QComboBox()
        self._sample_combo.setPlaceholderText("请先打开项目...")
        self._sample_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        self._sample_combo.currentIndexChanged.connect(self._update_run_state)
        row.addWidget(self._sample_combo, stretch=1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        refresh_btn.setMinimumWidth(60)
        refresh_btn.clicked.connect(self._refresh_samples)
        row.addWidget(refresh_btn)

        inner.addLayout(row)

        hint = QLabel("输入数据来自当前项目样本，首阶段输入类型由路径定义自动匹配。")
        hint.setStyleSheet(styles.LABEL_HINT)
        inner.addWidget(hint)

        # 添加卡片阴影
        shadow = QGraphicsDropShadowEffect(sample_group)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        sample_group.setGraphicsEffect(shadow)

        return sample_group


    def refresh_context(self) -> None:
        self._refresh_samples()
        self._refresh_history()
        self._update_run_state()

    def _refresh_samples(self) -> None:
        locator = self._get_locator()
        self._sample_combo.clear()

        if locator is None or locator.data_registry is None:
            self._sample_combo.setPlaceholderText("请先打开项目...")
            self._update_run_state()
            return

        samples = locator.data_registry.list_samples()
        for sample in samples:
            self._sample_combo.addItem(sample.name, sample.sample_id)

        try:
            self._history_card.set_db_connection(locator.project_manager.db)
        except Exception:
            pass

        self._update_run_state()

    def _on_stage_selection_changed(self, stage_index: int) -> None:
        if stage_index < 0 or stage_index >= len(self._stage_cards):
            return
        card = self._stage_cards[stage_index]
        widget = self._stage_widgets[stage_index]

        tool_name = card.selected_tool_name if card.selected_tool_id else "已跳过"
        if hasattr(widget, "_name_label"):
            widget._name_label.setText(f"阶段 {stage_index + 1}: {tool_name}")

    def _collect_pipeline_stages(self) -> tuple[list[PipelineStage], list[int]]:
        stages: list[PipelineStage] = []
        ui_indices: list[int] = []

        for idx, stage_def in enumerate(self._path_stages):
            card = self._stage_cards[idx]
            tool_id = card.selected_tool_id
            if tool_id is None:
                continue

            stage = PipelineStage(
                tool_id=tool_id,
                parameters=card.get_stage_parameters(),
                database_paths=card.get_stage_database_paths(),
                input_type=stage_def["input_type"],
                required=stage_def["required"],
            )
            stages.append(stage)
            ui_indices.append(idx)

        return stages, ui_indices

    def _first_stage_initial_inputs(self, sample_id: str, first_input_type: str) -> list[str]:
        locator = self._get_locator()
        registry = locator.data_registry if locator else None
        if registry is None:
            return []

        compatible = registry.find_compatible(sample_id, first_input_type)
        if not compatible:
            return []

        if first_input_type == "fastq":
            return [item.data_id for item in compatible[:2]]
        return [compatible[0].data_id]

    def _on_run(self) -> None:
        locator = self._get_locator()
        if locator is None:
            QMessageBox.warning(self, "提示", "服务容器未初始化")
            return

        ssh = locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            QMessageBox.warning(self, "提示", "请先在设置页连接 SSH")
            return

        if locator.project_manager.current_project is None:
            QMessageBox.warning(self, "提示", "请先打开项目")
            return

        if locator.data_registry is None or locator.tool_engine is None:
            QMessageBox.warning(self, "提示", "项目服务未就绪")
            return

        sample_id = self._sample_combo.currentData()
        if not sample_id:
            QMessageBox.warning(self, "提示", "请选择样本")
            return

        pipeline_stages, ui_indices = self._collect_pipeline_stages()
        if not pipeline_stages:
            QMessageBox.warning(self, "提示", "当前没有可执行阶段，请至少选择一个工具")
            return

        # 校验数据库必填项
        for idx, card in enumerate(self._stage_cards):
            if card.selected_tool_id is None:
                continue
            missing = card.validate_required_databases()
            if missing:
                QMessageBox.warning(self, "提示", f"第 {idx + 1} 步缺少数据库路径: {', '.join(missing)}")
                return

        initial_input_ids = self._first_stage_initial_inputs(sample_id, pipeline_stages[0].input_type)
        if not initial_input_ids:
            QMessageBox.warning(
                self,
                "提示",
                f"未找到可用于首阶段({pipeline_stages[0].input_type})的输入数据，请先准备样本数据。",
            )
            return

        try:
            for widget in self._stage_widgets:
                widget.set_status(STATUS_PENDING)

            self._runner = PipelineRunner(tool_engine=locator.tool_engine, data_registry=locator.data_registry)
            self._runner.stage_completed.connect(self._on_stage_completed)
            self._runner.pipeline_completed.connect(self._on_pipeline_completed)
            self._runner.pipeline_failed.connect(self._on_pipeline_failed)

            self._pipeline_run_id = self._runner.run(
                stages=pipeline_stages,
                sample_id=sample_id,
                initial_input_ids=initial_input_ids,
            )
            self._active_stage_ui_indices = ui_indices

            first_ui_idx = self._active_stage_ui_indices[0]
            self._stage_widgets[first_ui_idx].set_status(STATUS_RUNNING)

            self._run_btn.setEnabled(False)
            self._run_btn.setText("运行中...")
            self._status_label.setText(f"流程已提交: {self._pipeline_run_id}")

        except Exception as e:
            logger.exception("启动组装流程失败")
            QMessageBox.critical(self, "启动失败", str(e))
            self._run_btn.setEnabled(True)
            self._run_btn.setText("启动组装流程")
            self._status_label.setText(f"启动失败: {e}")

    def _on_stage_completed(self, run_id: str, stage_idx: int, total: int) -> None:
        if run_id != self._pipeline_run_id:
            return

        if stage_idx < len(self._active_stage_ui_indices):
            ui_idx = self._active_stage_ui_indices[stage_idx]
            self._stage_widgets[ui_idx].set_status(STATUS_COMPLETED)

        next_stage = stage_idx + 1
        if next_stage < len(self._active_stage_ui_indices):
            next_ui_idx = self._active_stage_ui_indices[next_stage]
            self._stage_widgets[next_ui_idx].set_status(STATUS_RUNNING)

        self._status_label.setText(f"阶段 {stage_idx + 1}/{total} 完成")

    def _on_pipeline_completed(self, run_id: str) -> None:
        if run_id != self._pipeline_run_id:
            return

        self._run_btn.setEnabled(True)
        self._run_btn.setText("启动组装流程")
        self._status_label.setText("组装流程执行完成")
        self._status_label.setStyleSheet(styles.STATUS_SUCCESS)

        for ui_idx in self._active_stage_ui_indices:
            self._stage_widgets[ui_idx].set_status(STATUS_COMPLETED)

        self._refresh_history()
        self._update_run_state()

    def _on_pipeline_failed(self, run_id: str, stage_idx: int, error: str) -> None:
        if run_id != self._pipeline_run_id:
            return

        self._run_btn.setEnabled(True)
        self._run_btn.setText("启动组装流程")
        self._status_label.setText(f"阶段 {stage_idx + 1} 失败: {error}")
        self._status_label.setStyleSheet(styles.STATUS_ERROR)

        if stage_idx < len(self._active_stage_ui_indices):
            failed_ui_idx = self._active_stage_ui_indices[stage_idx]
            self._stage_widgets[failed_ui_idx].set_status(STATUS_FAILED)

        self._refresh_history()
        self._update_run_state()

    def _refresh_history(self) -> None:
        locator = self._get_locator()
        if locator is None:
            return

        try:
            self._history_card.set_db_connection(locator.project_manager.db)
            self._history_card.refresh()
        except Exception:
            pass

    def _update_run_state(self) -> None:
        locator = self._get_locator()
        reasons: list[str] = []

        if self._sample_combo.count() == 0 or not self._sample_combo.currentData():
            reasons.append("选择样本")

        if locator is None:
            reasons.append("初始化服务")
        else:
            ssh = locator.ssh_service
            if ssh is None or not getattr(ssh, "is_connected", False):
                reasons.append("连接 SSH")
            if locator.project_manager.current_project is None:
                reasons.append("打开项目")

        for idx, card in enumerate(self._stage_cards):
            if card.selected_tool_id is None:
                continue
            missing = card.validate_required_databases()
            if missing:
                reasons.append(f"第 {idx + 1} 步数据库")

        has_active_stage = any(card.selected_tool_id is not None for card in self._stage_cards)
        if not has_active_stage:
            reasons.append("至少选择一个阶段工具")

        if reasons:
            self._run_btn.setEnabled(False)
            self._status_label.setText("请先: " + "、".join(reasons))
            self._status_label.setStyleSheet(styles.LABEL_HINT)
        else:
            self._run_btn.setEnabled(True)
            self._status_label.setText("已就绪，可启动组装流程")
            self._status_label.setStyleSheet(styles.STATUS_SUCCESS)

