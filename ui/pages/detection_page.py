from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import get_database_path, get_runtime_setting
from core.data_importer import DataImporter
from ui.page_base import BasePage
from ui.widgets import styles
from ui.widgets.execution_history_card import ExecutionHistoryCard

logger = logging.getLogger(__name__)


class DetectionPage(BasePage):
    """病原检测页：插件卡片工作台 + 动态参数 + 执行历史。"""

    def __init__(self, main_window=None):
        super().__init__("病原检测")
        if hasattr(self, "label"):
            self.label.hide()

        self.main_window = main_window

        self._tool_catalog: dict[str, dict[str, Any]] = {}
        self._tool_order: list[str] = []
        self._tool_cards: dict[str, QFrame] = {}

        self._selected_tool_id: str = ""
        self._selected_descriptor: dict[str, Any] = {}

        self._input_defs: list[dict[str, Any]] = []
        self._input_widgets: dict[str, tuple[str, QLineEdit]] = {}
        self._param_widgets: dict[str, QWidget] = {}
        self._db_widgets: dict[str, QLineEdit] = {}

        self._running = False
        self._current_execution_id: Optional[str] = None
        self._current_sample_id: Optional[str] = None
        self._current_tool_id: str = ""
        self._current_descriptor: dict[str, Any] = {}
        self._current_local_output_dir: str = ""

        self._result_columns: list[str] = []

        self.execution_history: Optional[ExecutionHistoryCard] = None

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")

        self._load_tool_catalog()
        self._build_ui()
        self._connect_locator_signals()
        self.refresh_context()

    def _get_locator(self):
        if self.main_window and hasattr(self.main_window, "service_locator"):
            return self.main_window.service_locator
        return None

    def _analysis_paths_file(self) -> Path:
        return Path(__file__).resolve().parents[2] / "plugins" / "analysis_paths.yaml"

    def _set_settings_lock(self, locked: bool, reason: str = "SSH 任务执行中，设置暂时锁定") -> None:
        if self.main_window and hasattr(self.main_window, "set_settings_locked"):
            self.main_window.set_settings_locked(locked, reason)

    def _load_tool_catalog(self) -> None:
        locator = self._get_locator()
        reg = locator.plugin_registry if locator else None

        preferred_order: list[str] = []

        try:
            with self._analysis_paths_file().open("r", encoding="utf-8") as f:
                root = yaml.safe_load(f) or {}
            paths = root.get("paths") or {}
            for path_cfg in paths.values():
                for stage in (path_cfg or {}).get("stages") or []:
                    tid = str(stage.get("tool_id") or "").strip()
                    if tid and tid not in preferred_order:
                        preferred_order.append(tid)
        except Exception:
            logger.exception("读取 analysis_paths.yaml 失败")

        all_ids: list[str] = []
        if reg is not None:
            try:
                all_ids = list(reg.list_all_ids())
            except Exception:
                logger.exception("读取插件列表失败")

        for tid in all_ids:
            if tid not in preferred_order:
                preferred_order.append(tid)

        if reg is not None:
            for tid in preferred_order:
                try:
                    self._tool_catalog[tid] = reg.get_descriptor(tid)
                except Exception:
                    logger.exception("读取插件失败: %s", tid)

        if not self._tool_catalog:
            self._tool_catalog = {
                "blastn": {
                    "id": "blastn",
                    "name": "BLASTn",
                    "version": "unknown",
                    "category": "blast",
                    "description": "核酸序列比对工具",
                    "inputs": [{"name": "query", "type": "fasta", "required": True}],
                    "parameters": [],
                    "databases": [{"param_name": "db", "required": True}],
                    "outputs": [],
                }
            }
            preferred_order = ["blastn"]

        self._tool_order = [tid for tid in preferred_order if tid in self._tool_catalog]
        if not self._tool_order:
            self._tool_order = sorted(self._tool_catalog.keys())

        if "blastn" in self._tool_order:
            self._selected_tool_id = "blastn"
        else:
            self._selected_tool_id = self._tool_order[0]
        self._selected_descriptor = self._tool_catalog[self._selected_tool_id]

    def _connect_locator_signals(self) -> None:
        locator = self._get_locator()
        if locator is None:
            return
        locator.execution_completed.connect(self._on_execution_completed)
        locator.execution_failed.connect(self._on_execution_failed)

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(10)

        title = QLabel("病原检测")
        title.setStyleSheet(styles.PAGE_HEADER_TITLE)
        self.layout.addWidget(title)

        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_workbench = self._create_nav_button("插件工作台", 0)
        self.btn_history = self._create_nav_button("任务历史", 1)
        self.btn_other = self._create_nav_button("其他分析", 2)

        nav_layout.addWidget(self.btn_workbench)
        nav_layout.addWidget(self.btn_history)
        nav_layout.addWidget(self.btn_other)
        nav_layout.addStretch()
        self.layout.addWidget(nav)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(styles.DIVIDER)
        self.layout.addWidget(line)

        self.content_stack = QStackedWidget()
        self.layout.addWidget(self.content_stack)

        self.workbench_page = self._build_workbench_page()
        self.history_page = self._build_history_page()
        self.other_page = self._build_other_page()

        self.content_stack.addWidget(self.workbench_page)
        self.content_stack.addWidget(self.history_page)
        self.content_stack.addWidget(self.other_page)

        self.btn_workbench.setChecked(True)
        self.content_stack.setCurrentIndex(0)

        self._select_tool(self._selected_tool_id)
        self._refresh_history_db()

    def _create_nav_button(self, text: str, index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(styles.BUTTON_NAV_TOGGLE)
        btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(index))
        self.nav_group.addButton(btn)
        return btn

    def _build_workbench_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(12)

        cards_title = QLabel("插件功能卡片")
        cards_title.setStyleSheet(styles.CARD_TITLE)
        root.addWidget(cards_title)

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setMaximumHeight(200)
        cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_scroll.setStyleSheet("background: transparent;")

        cards_wrap = QWidget()
        cards_wrap.setStyleSheet("background: transparent;")
        cards_grid = QGridLayout(cards_wrap)
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(10)
        cards_grid.setVerticalSpacing(10)

        for i, tid in enumerate(self._tool_order):
            desc = self._tool_catalog[tid]
            card = self._build_tool_card(tid, desc)
            self._tool_cards[tid] = card
            cards_grid.addWidget(card, i // 3, i % 3)

        cards_scroll.setWidget(cards_wrap)
        root.addWidget(cards_scroll)

        self.meta_card = QFrame()
        self.meta_card.setObjectName("DetectionMetaCard")
        self.meta_card.setStyleSheet(styles.CARD_FRAME("DetectionMetaCard"))
        meta_layout = QVBoxLayout(self.meta_card)
        meta_layout.setContentsMargins(16, 12, 16, 12)
        meta_layout.setSpacing(4)

        self.meta_name = QLabel("工具: -")
        self.meta_name.setStyleSheet(styles.CARD_TITLE)
        self.meta_version = QLabel("版本: -")
        self.meta_version.setStyleSheet(styles.LABEL_HINT)
        self.meta_desc = QLabel("")
        self.meta_desc.setWordWrap(True)
        self.meta_desc.setStyleSheet(styles.LABEL_HINT)

        meta_layout.addWidget(self.meta_name)
        meta_layout.addWidget(self.meta_version)
        meta_layout.addWidget(self.meta_desc)
        root.addWidget(self.meta_card)

        self.form_card = QFrame()
        self.form_card.setObjectName("DetectionFormCard")
        self.form_card.setStyleSheet(styles.CARD_FRAME("DetectionFormCard"))
        self.form_grid = QGridLayout(self.form_card)
        self.form_grid.setContentsMargins(16, 12, 16, 12)
        self.form_grid.setHorizontalSpacing(10)
        self.form_grid.setVerticalSpacing(10)
        root.addWidget(self.form_card)

        run_row = QHBoxLayout()
        self._run_btn = QPushButton("运行")
        self._run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self._run_btn.setMinimumHeight(36)
        self._run_btn.clicked.connect(self._on_start)
        run_row.addWidget(self._run_btn)
        run_row.addStretch()
        root.addLayout(run_row)

        self._status_label = QLabel("请先连接 SSH、选择项目并填写输入")
        self._status_label.setStyleSheet(styles.LABEL_HINT)
        root.addWidget(self._status_label)

        self._result_label = QLabel("")
        self._result_label.setStyleSheet(styles.LABEL_HINT)
        self._result_label.hide()
        root.addWidget(self._result_label)

        self._result_table = QTableWidget()
        self._result_table.setStyleSheet(styles.TABLE_WIDGET)
        self._result_table.hide()
        root.addWidget(self._result_table)

        return page

    def _build_tool_card(self, tool_id: str, descriptor: dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{styles.COLOR_BG_CARD}; border:1px solid {styles.COLOR_BORDER}; border-radius:{styles.RADIUS_CARD}; }}"
        )

        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        name = str(descriptor.get("name") or tool_id)
        category = str(descriptor.get("category") or "unknown")
        desc = str(descriptor.get("description") or "")

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(styles.CARD_TITLE)
        lay.addWidget(name_lbl)

        id_lbl = QLabel(f"{tool_id} · {category}")
        id_lbl.setStyleSheet(styles.LABEL_MUTED)
        lay.addWidget(id_lbl)

        short_desc = desc[:44] + ("..." if len(desc) > 44 else "")
        desc_lbl = QLabel(short_desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(styles.LABEL_HINT)
        lay.addWidget(desc_lbl)

        btn = QPushButton("使用该工具")
        btn.setStyleSheet(styles.BUTTON_SECONDARY)
        btn.clicked.connect(lambda: self._select_tool(tool_id))
        lay.addWidget(btn)

        return card

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        self.execution_history = ExecutionHistoryCard()
        layout.addWidget(self.execution_history)

        return page

    def _build_other_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        hint = QLabel("按路径分组展示插件入口，新增 tool.yaml 后可自动出现在这里。")
        hint.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(hint)

        groups = self._load_path_groups()
        if not groups:
            empty = QLabel("未找到路径定义")
            empty.setStyleSheet(styles.LABEL_MUTED)
            layout.addWidget(empty)
            layout.addStretch()
            return page

        for group in groups:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background:{styles.COLOR_BG_CARD}; border:1px solid {styles.COLOR_BORDER}; border-radius:{styles.RADIUS_CARD}; }}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            title = QLabel(str(group.get("name") or group.get("path_id") or "未命名路径"))
            title.setStyleSheet(styles.CARD_TITLE)
            card_layout.addWidget(title)

            desc = QLabel(str(group.get("description") or ""))
            desc.setStyleSheet(styles.LABEL_HINT)
            desc.setWordWrap(True)
            card_layout.addWidget(desc)

            chips = QWidget()
            chips_layout = QGridLayout(chips)
            chips_layout.setContentsMargins(0, 0, 0, 0)
            chips_layout.setHorizontalSpacing(6)
            chips_layout.setVerticalSpacing(6)

            tool_ids = group.get("tool_ids") or []
            for idx, tid in enumerate(tool_ids):
                entry = self._tool_catalog.get(tid, {})
                name = str(entry.get("name") or tid)

                chip = QPushButton(name)
                chip.setStyleSheet(styles.BUTTON_SECONDARY)
                chip.setMinimumHeight(30)
                chip.clicked.connect(lambda _=False, t=tid: self._select_tool(t))
                chips_layout.addWidget(chip, idx // 4, idx % 4)

            card_layout.addWidget(chips)
            layout.addWidget(card)

        layout.addStretch()
        return page

    def _load_path_groups(self) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        try:
            with self._analysis_paths_file().open("r", encoding="utf-8") as f:
                root = yaml.safe_load(f) or {}
        except Exception:
            logger.exception("读取 analysis_paths.yaml 失败")
            return groups

        for path_id, path_cfg in (root.get("paths") or {}).items():
            tool_ids: list[str] = []
            for stage in (path_cfg or {}).get("stages") or []:
                tid = str(stage.get("tool_id") or "").strip()
                if tid and tid in self._tool_catalog and tid not in tool_ids:
                    tool_ids.append(tid)
            groups.append(
                {
                    "path_id": str(path_id),
                    "name": str((path_cfg or {}).get("name") or path_id),
                    "description": str((path_cfg or {}).get("description") or ""),
                    "tool_ids": tool_ids,
                }
            )
        return groups

    def _set_card_selected(self, selected_tool_id: str) -> None:
        for tid, card in self._tool_cards.items():
            if tid == selected_tool_id:
                card.setStyleSheet(
                    f"QFrame {{ background:{styles.COLOR_BG_SIDEBAR_SELECTED}; border:1px solid {styles.COLOR_PRIMARY}; border-radius:{styles.RADIUS_CARD}; }}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame {{ background:{styles.COLOR_BG_CARD}; border:1px solid {styles.COLOR_BORDER}; border-radius:{styles.RADIUS_CARD}; }}"
                )

    def _clear_form(self) -> None:
        while self.form_grid.count():
            item = self.form_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _select_tool(self, tool_id: str) -> None:
        if tool_id not in self._tool_catalog:
            return

        self._selected_tool_id = tool_id
        self._selected_descriptor = self._tool_catalog[tool_id]
        self._set_card_selected(tool_id)

        name = str(self._selected_descriptor.get("name") or tool_id)
        version = str(self._selected_descriptor.get("version") or "unknown")
        desc = str(self._selected_descriptor.get("description") or "")

        self.meta_name.setText(f"工具: {name} ({tool_id})")
        self.meta_version.setText(f"版本: {version}")
        self.meta_desc.setText(desc)
        self._run_btn.setText(f"运行 {name}")

        self._clear_form()
        self._input_widgets.clear()
        self._param_widgets.clear()
        self._db_widgets.clear()

        self._input_defs = list(self._selected_descriptor.get("inputs") or [])

        row = 0

        self.form_grid.addWidget(QLabel("样本名称", styleSheet=styles.FORM_LABEL), row, 0)
        self._sample_name_input = QLineEdit()
        self._sample_name_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._sample_name_input.setPlaceholderText("留空将自动生成")
        self.form_grid.addWidget(self._sample_name_input, row, 1, 1, 2)
        row += 1

        for inp in self._input_defs:
            in_name = str(inp.get("name") or "")
            in_type = str(inp.get("type") or "file")
            required = bool(inp.get("required", False))

            self.form_grid.addWidget(QLabel(f"输入({in_name}){' *' if required else ''}", styleSheet=styles.FORM_LABEL), row, 0)

            path_edit = QLineEdit()
            path_edit.setReadOnly(False)
            path_edit.setStyleSheet(styles.INPUT_LINEEDIT)
            if in_type == "directory":
                path_edit.setPlaceholderText("本地目录或远端绝对路径")
            else:
                path_edit.setPlaceholderText(f"本地{in_type}文件或远端绝对路径")
            self.form_grid.addWidget(path_edit, row, 1)

            browse_btn = QPushButton("浏览")
            browse_btn.setStyleSheet(styles.BUTTON_SECONDARY)
            browse_btn.clicked.connect(lambda _=False, n=in_name: self._on_browse_input(n))
            self.form_grid.addWidget(browse_btn, row, 2)

            self._input_widgets[in_name] = (in_type, path_edit)
            row += 1

        self.form_grid.addWidget(QLabel("结果目录", styleSheet=styles.FORM_LABEL), row, 0)
        self._output_dir_input = QLineEdit()
        self._output_dir_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._output_dir_input.setText(str(get_runtime_setting("local_output_dir", "") or ""))
        self.form_grid.addWidget(self._output_dir_input, row, 1)

        output_btn = QPushButton("选择")
        output_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        output_btn.clicked.connect(self._on_browse_output)
        self.form_grid.addWidget(output_btn, row, 2)
        row += 1

        for db in self._selected_descriptor.get("databases", []):
            param_name = str(db.get("param_name") or "db")
            required = bool(db.get("required", False))

            self.form_grid.addWidget(QLabel(f"数据库({param_name}){' *' if required else ''}", styleSheet=styles.FORM_LABEL), row, 0)
            db_edit = QLineEdit()
            db_edit.setStyleSheet(styles.INPUT_LINEEDIT)
            db_edit.setPlaceholderText("远端数据库路径")
            if param_name == "db":
                db_edit.setText(get_database_path("blast_nt", ""))
            self.form_grid.addWidget(db_edit, row, 1, 1, 2)

            self._db_widgets[param_name] = db_edit
            row += 1

        for param in self._selected_descriptor.get("parameters", []):
            pname = str(param.get("name") or "")
            if not pname or pname == "outfmt":
                continue

            self.form_grid.addWidget(QLabel(str(param.get("label") or pname), styleSheet=styles.FORM_LABEL), row, 0)
            widget = self._create_param_widget(param)
            self.form_grid.addWidget(widget, row, 1, 1, 2)
            self._param_widgets[pname] = widget
            row += 1

        self._prepare_result_table()
        self._wire_form_signals()
        self._update_run_state()

    def _prepare_result_table(self) -> None:
        outfmt = ""
        for p in self._selected_descriptor.get("parameters", []):
            if p.get("name") == "outfmt":
                outfmt = str(p.get("default") or "")
                break

        if outfmt:
            cols = outfmt.split()
            if cols and cols[0] == "6":
                cols = cols[1:]
            self._result_columns = cols
            self._result_table.setColumnCount(len(cols))
            self._result_table.setHorizontalHeaderLabels(cols)
            self._result_table.setRowCount(0)
            self._result_table.show()
        else:
            self._result_columns = []
            self._result_table.setRowCount(0)
            self._result_table.hide()

    def _create_param_widget(self, param: dict[str, Any]) -> QWidget:
        ptype = str(param.get("type", "string"))
        default = param.get("default")

        if ptype == "int":
            widget = QSpinBox()
            rng = param.get("range", [1, 9999])
            if isinstance(rng, list) and len(rng) == 2:
                widget.setRange(int(rng[0]), int(rng[1]))
            else:
                widget.setRange(1, 9999)
            if default is not None:
                widget.setValue(int(default))
            return widget

        if ptype == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(8)
            rng = param.get("range", [0.0, 1000000.0])
            if isinstance(rng, list) and len(rng) == 2:
                widget.setRange(float(rng[0]), float(rng[1]))
            else:
                widget.setRange(0.0, 1000000.0)
            if default is not None:
                widget.setValue(float(default))
            return widget

        if ptype == "bool":
            widget = QComboBox()
            widget.setStyleSheet(styles.INPUT_COMBOBOX)
            widget.addItem("是", True)
            widget.addItem("否", False)
            if default is False:
                widget.setCurrentIndex(1)
            return widget

        if ptype == "choice":
            widget = QComboBox()
            widget.setStyleSheet(styles.INPUT_COMBOBOX)
            choices = list(param.get("choices") or [])
            for c in choices:
                widget.addItem(str(c), c)
            if default in choices:
                widget.setCurrentIndex(choices.index(default))
            return widget

        widget = QLineEdit()
        widget.setStyleSheet(styles.INPUT_LINEEDIT)
        widget.setText("" if default is None else str(default))
        return widget

    @staticmethod
    def _read_param_widget(widget: QWidget) -> Any:
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return None

    @staticmethod
    def _file_filter(input_type: str) -> str:
        if input_type == "fastq":
            return "FASTQ 文件 (*.fq *.fq.gz *.fastq *.fastq.gz);;所有文件 (*)"
        if input_type == "fasta":
            return "FASTA 文件 (*.fasta *.fa *.fna *.fas *.txt);;所有文件 (*)"
        return "所有文件 (*)"

    def _on_browse_input(self, input_name: str) -> None:
        if input_name not in self._input_widgets:
            return

        input_type, path_edit = self._input_widgets[input_name]
        if input_type == "directory":
            selected = QFileDialog.getExistingDirectory(self, f"选择目录输入: {input_name}", "")
            if selected:
                path_edit.setText(selected)
            return

        selected, _ = QFileDialog.getOpenFileName(
            self,
            f"选择输入文件: {input_name}",
            "",
            self._file_filter(input_type),
        )
        if selected:
            path_edit.setText(selected)

    def _on_browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择结果目录", self._output_dir_input.text())
        if selected:
            self._output_dir_input.setText(selected)


    def _wire_form_signals(self) -> None:
        self._sample_name_input.textChanged.connect(self._update_run_state)
        self._output_dir_input.textChanged.connect(self._update_run_state)

        for _, widget in self._input_widgets.values():
            widget.textChanged.connect(self._update_run_state)
        for widget in self._db_widgets.values():
            widget.textChanged.connect(self._update_run_state)

        for widget in self._param_widgets.values():
            if isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._update_run_state)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._update_run_state)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._update_run_state)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._update_run_state)

    def _update_run_state(self, *_args) -> None:
        if self._running:
            self._run_btn.setEnabled(False)
            self._status_label.setStyleSheet(styles.LABEL_HINT)
            return

        reasons: list[str] = []
        locator = self._get_locator()

        if locator is None:
            reasons.append("初始化服务")
        else:
            ssh = locator.ssh_service
            if ssh is None or not getattr(ssh, "is_connected", False):
                reasons.append("连接 SSH")
            if locator.project_manager.current_project is None:
                reasons.append("打开项目")
            if locator.data_registry is None or locator.tool_engine is None:
                reasons.append("项目服务就绪")

        for inp in self._input_defs:
            in_name = str(inp.get("name") or "")
            required = bool(inp.get("required", False))
            pair = self._input_widgets.get(in_name)
            if not pair:
                continue
            value = pair[1].text().strip()
            if required and not value:
                reasons.append(f"输入: {in_name}")

        for db in self._selected_descriptor.get("databases", []):
            if not bool(db.get("required", False)):
                continue
            param_name = str(db.get("param_name") or "db")
            widget = self._db_widgets.get(param_name)
            if widget and not widget.text().strip():
                reasons.append(f"数据库: {param_name}")

        if reasons:
            self._run_btn.setEnabled(False)
            self._status_label.setText("请先: " + "、".join(reasons))
            self._status_label.setStyleSheet(styles.LABEL_HINT)
        else:
            self._run_btn.setEnabled(True)
            self._status_label.setText("已就绪，可执行当前插件任务")
            self._status_label.setStyleSheet(styles.STATUS_SUCCESS)

    def refresh_context(self) -> None:
        self._refresh_history_db()
        self._update_run_state()

    def _refresh_history_db(self) -> None:
        if self.execution_history is None:
            return

        locator = self._get_locator()
        if locator is None:
            return

        pm = locator.project_manager
        if pm is None or pm.current_project is None:
            return

        try:
            self.execution_history.set_db_connection(pm.db)
        except Exception:
            logger.exception("刷新执行历史失败")

    def _validate_before_run(self) -> tuple[bool, str]:
        locator = self._get_locator()
        if locator is None:
            return False, "未初始化服务容器"

        ssh = locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            return False, "请先连接 SSH"

        pm = locator.project_manager
        if pm.current_project is None:
            return False, "请先打开项目"

        if locator.data_registry is None or locator.tool_engine is None:
            return False, "请先打开项目"

        for inp in self._input_defs:
            name = str(inp.get("name") or "")
            required = bool(inp.get("required", False))
            pair = self._input_widgets.get(name)
            if not pair:
                continue
            text = pair[1].text().strip()
            if required and not text:
                return False, f"缺少必填输入: {name}"

        for db in self._selected_descriptor.get("databases", []):
            if not bool(db.get("required", False)):
                continue
            param_name = str(db.get("param_name") or "db")
            widget = self._db_widgets.get(param_name)
            if widget and not widget.text().strip():
                return False, f"缺少必填数据库路径: {param_name}"

        return True, ""

    def _on_start(self) -> None:
        if self._running:
            return

        ok, msg = self._validate_before_run()
        if not ok:
            QMessageBox.warning(self, "提示", msg)
            self._status_label.setText(msg)
            return

        locator = self._get_locator()
        if locator is None:
            return

        ssh = locator.ssh_service
        pm = locator.project_manager
        registry = locator.data_registry
        engine = locator.tool_engine
        project = pm.current_project

        tool_id = self._selected_tool_id
        descriptor = self._selected_descriptor

        sample_name = self._sample_name_input.text().strip()
        if not sample_name:
            sample_name = f"{tool_id}_{time.strftime('%Y%m%d_%H%M%S')}"

        try:
            sample_id = registry.add_sample(sample_name)

            importer = DataImporter(ssh_service=ssh, registry=registry)
            input_data_ids: list[str] = []

            for inp in self._input_defs:
                in_name = str(inp.get("name") or "")
                in_type = str(inp.get("type") or "file")

                pair = self._input_widgets.get(in_name)
                if pair is None:
                    continue
                raw_path = pair[1].text().strip()
                if not raw_path:
                    continue

                if os.path.exists(raw_path):
                    if os.path.isdir(raw_path):
                        raise ValueError(
                            f"输入 {in_name} 为本地目录。当前仅支持远端目录路径，请填写 / 开头的远端绝对路径"
                        )

                    data_id = importer.import_file(
                        local_path=raw_path,
                        sample_id=sample_id,
                        data_type=in_type,
                        project_remote_base=project.remote_base,
                        tier="raw",
                    )
                    input_data_ids.append(data_id)
                else:
                    if not raw_path.startswith("/"):
                        raise ValueError(
                            f"输入 {in_name} 既不是本地文件，也不是远端绝对路径: {raw_path}"
                        )

                    data_id = registry.register_input(
                        file_path=raw_path,
                        sample_id=sample_id,
                        data_type=in_type,
                        tier="intermediate",
                    )
                    input_data_ids.append(data_id)

            parameters: dict[str, Any] = {}
            for name, widget in self._param_widgets.items():
                value = self._read_param_widget(widget)
                if value in (None, ""):
                    continue
                parameters[name] = value

            db_paths: dict[str, str] = {}
            for name, widget in self._db_widgets.items():
                text = widget.text().strip()
                if text:
                    db_paths[name] = text

            execution_id = engine.execute(
                tool_id=tool_id,
                input_data_ids=input_data_ids,
                parameters=parameters,
                sample_id=sample_id,
                triggered_by="manual",
                database_paths=db_paths or None,
            )

            self._running = True
            self._current_execution_id = execution_id
            self._current_sample_id = sample_id
            self._current_tool_id = tool_id
            self._current_descriptor = descriptor
            self._current_local_output_dir = self._output_dir_input.text().strip()

            self._run_btn.setEnabled(False)
            self._set_settings_lock(True)
            self._status_label.setText(f"任务已提交: {execution_id}，正在执行...")
            self._result_label.hide()

            self._refresh_history_db()

        except Exception as exc:
            logger.exception("启动任务失败")
            self._finish_run()
            self._status_label.setText(f"启动失败: {exc}")
            QMessageBox.warning(self, "启动失败", str(exc))

    def _find_output_remote_paths(self, descriptor: dict[str, Any], sample_id: str, remote_output_dir: str) -> list[str]:
        outputs = descriptor.get("outputs") or []
        if not outputs:
            return []

        paths: list[str] = []
        for out_def in outputs:
            pattern = str(out_def.get("pattern") or "").strip()
            name = str(out_def.get("name") or "result")
            if pattern:
                try:
                    remote_path = pattern.format(output_dir=remote_output_dir, sample_id=sample_id)
                except Exception:
                    remote_path = f"{remote_output_dir}/{sample_id}.{name}"
            else:
                remote_path = f"{remote_output_dir}/{sample_id}.{name}"
            paths.append(remote_path)

        dedup: list[str] = []
        for p in paths:
            if p not in dedup:
                dedup.append(p)
        return dedup

    def _load_result_table(self, local_paths: list[str]) -> None:
        if not self._result_columns:
            return

        candidate = ""
        for p in local_paths:
            if p.lower().endswith((".tsv", ".txt")) and os.path.exists(p):
                candidate = p
                break

        if not candidate:
            return

        rows: list[list[str]] = []
        try:
            with open(candidate, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    text = line.strip()
                    if not text:
                        continue
                    rows.append(text.split("\t"))
        except Exception:
            logger.exception("读取结果表失败: %s", candidate)
            return

        self._result_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c in range(min(len(row), self._result_table.columnCount())):
                self._result_table.setItem(r, c, QTableWidgetItem(row[c]))

    def _finish_run(self) -> None:
        self._running = False
        self._current_execution_id = None
        self._current_sample_id = None
        self._current_tool_id = ""
        self._current_descriptor = {}
        self._current_local_output_dir = ""
        self._set_settings_lock(False)
        self._update_run_state()

    def _on_execution_completed(self, execution_id: str) -> None:
        if execution_id != self._current_execution_id:
            return

        local_paths: list[str] = []
        try:
            locator = self._get_locator()
            if locator is None:
                self._status_label.setText(f"任务完成: {execution_id}")
                return

            pm = locator.project_manager
            project = pm.current_project
            if project is None or not self._current_sample_id or not self._current_tool_id:
                self._status_label.setText(f"任务完成: {execution_id}")
                return

            remote_output_dir = f"{project.remote_base}/intermediate/{self._current_sample_id}/{self._current_tool_id}"
            remote_paths = self._find_output_remote_paths(
                descriptor=self._current_descriptor,
                sample_id=self._current_sample_id,
                remote_output_dir=remote_output_dir,
            )

            local_dir = self._current_local_output_dir or str(get_runtime_setting("local_output_dir", "") or "")
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)

            ssh = locator.ssh_service
            for remote in remote_paths:
                if not local_dir:
                    break
                local = os.path.join(local_dir, os.path.basename(remote))
                try:
                    ssh.download(remote, local)
                    local_paths.append(local)
                except Exception:
                    logger.warning("下载输出失败: %s", remote, exc_info=True)

            self._load_result_table(local_paths)

            self._status_label.setText(f"任务完成: {execution_id}")
            if local_paths:
                self._result_label.setText(f"已同步 {len(local_paths)} 个结果文件到: {local_dir}")
            else:
                self._result_label.setText("任务完成，但未下载到可见结果文件（可能为目录输出或输出尚未就绪）")
            self._result_label.show()

        finally:
            self._refresh_history_db()
            self._finish_run()

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        if execution_id != self._current_execution_id:
            return

        self._status_label.setText(f"任务失败: {error}")
        self._result_label.hide()

        self._refresh_history_db()
        self._finish_run()


