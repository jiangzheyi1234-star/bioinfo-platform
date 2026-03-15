"""项目首页 — 样本管理中心。

显示当前项目所有样本的分析进度，支持添加/删除样本、继续分析、查看最近执行。
"""

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)

from core.data.sample_service import SampleService
from core.utils import human_time_ago
from ui.controllers import HomePageController
from ui.page_base import BasePage
from ui.widgets import AddSamplePlaceholder, SampleAddDialog, SampleCard, styles

logger = logging.getLogger(__name__)

_DEFAULT_STAGES = ["fastp", "hostile", "kraken2"]
_RECENT_STATUS_ICONS = {
    "completed": "[成功]",
    "running": "[运行中]",
    "failed": "[失败]",
    "pending": "[排队中]",
    "retrying": "[重试中]",
}


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

class HomePage(BasePage):
    """样本管理中心首页。"""

    def __init__(self, main_window: Any = None, parent: Optional[QWidget] = None):
        super().__init__("项目首页")
        if hasattr(self, "label"):
            self.label.hide()
        self._main_window = main_window
        self._controller = HomePageController(main_window)
        self._stages = _load_read_based_stages()
        self._search_text = ""
        self._card_widgets: list[SampleCard] = []
        self._service: SampleService | None = None

        self.setStyleSheet("background-color: #F8FAFC;")
        self._build_ui()

    def refresh_context(self) -> None:
        """项目切换 / SSH 变化时由 MainWindow 调用。"""
        self._load_all()

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(24, 16, 24, 16)
        self.layout.setSpacing(0)

        self._header_widget = self._build_project_header()
        self.layout.addWidget(self._header_widget)

        toolbar = self._build_toolbar()
        self.layout.addWidget(toolbar)

        self.layout.addSpacing(12)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #F1F5F9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #CBD5E1;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
        """)

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(14)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll_area.setWidget(self._grid_container)
        self.layout.addWidget(self._scroll_area, stretch=1)

        self.layout.addSpacing(8)

        self._empty_label = QLabel('请先在\u201c项目管理\u201d中创建或选择一个项目')
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "font-size: 15px; font-weight: 500; color: #94A3B8; background: transparent; padding: 40px;"
        )
        self._empty_label.hide()
        self.layout.addWidget(self._empty_label)

        self._recent_bar = self._build_recent_bar()
        self.layout.addWidget(self._recent_bar)

        QTimer.singleShot(0, self._load_all)

    def _build_project_header(self) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        v = QVBoxLayout(widget)
        v.setContentsMargins(0, 0, 0, 16)
        v.setSpacing(10)

        name_row = QHBoxLayout()
        self._proj_name_label = QLabel("—")
        self._proj_name_label.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {styles.COLOR_TEXT_TITLE};"
            "background: transparent; letter-spacing: -0.5px;"
        )
        name_row.addWidget(self._proj_name_label)
        name_row.addStretch()
        v.addLayout(name_row)

        self._proj_desc_label = QLabel("")
        self._proj_desc_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        v.addWidget(self._proj_desc_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        self._stat_samples = self._make_stat_chip("样本数", "0", "#F0F9FF", "#0EA5E9")
        self._stat_execs = self._make_stat_chip("执行数", "0", "#F5F3FF", "#6D28D9")
        self._stat_success = self._make_stat_chip("成功数", "0", "#ECFDF5", "#047857")
        self._stat_disk = self._make_stat_chip("磁盘占用", "—", "#FFFBEB", "#B45309")

        for chip in (self._stat_samples, self._stat_execs, self._stat_success, self._stat_disk):
            stats_row.addWidget(chip)
        stats_row.addStretch()
        v.addLayout(stats_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #E2E8F0; max-height: 1px; border: none;")
        v.addWidget(line)

        return widget

    @staticmethod
    def _make_stat_chip(title: str, text: str, bg_color: str, text_color: str) -> QLabel:
        label = QLabel(f"{title}: {text}")
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 13px;
                font-weight: 600;
                color: {text_color};
                background: {bg_color};
                border: 1px solid rgba(0,0,0,0.03);
                border-radius: 6px;
                padding: 6px 14px;
            }}
        """)
        return label

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(12)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 搜索样本名称或来源…")
        self._search_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px 14px;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                background-color: #FFFFFF;
                color: #0F172A;
                font-size: 13px;
                font-weight: 500;
            }
            QLineEdit:hover {
                border-color: #94A3B8;
            }
            QLineEdit:focus {
                border-color: #7DD3FC;
                background-color: #F8FAFC;
            }
        """)
        self._search_edit.setMaximumWidth(320)
        self._search_edit.textChanged.connect(self._on_search_changed)
        row.addWidget(self._search_edit)
        row.addStretch()

        self._add_btn = QPushButton("+ 添加新样本")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7DD3FC, stop:1 #38BDF8);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #BAE6FD, stop:1 #7DD3FC);
            }
            QPushButton:pressed {
                background: #0EA5E9;
            }
        """)
        self._add_btn.clicked.connect(self._on_add_sample)
        row.addWidget(self._add_btn)

        return toolbar

    def _build_recent_bar(self) -> QWidget:
        widget = QFrame()
        widget.setObjectName("RecentBar")
        widget.setStyleSheet("""
            QFrame#RecentBar {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 10))
        shadow.setOffset(0, -2)
        widget.setGraphicsEffect(shadow)

        widget.setMaximumHeight(100)

        v = QVBoxLayout(widget)
        v.setContentsMargins(18, 12, 18, 12)
        v.setSpacing(8)

        header = QLabel("最近活动执行")
        header.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #475569;"
            "background: transparent; border: none; letter-spacing: 0.5px;"
        )
        v.addWidget(header)

        self._recent_rows_widget = QWidget()
        self._recent_rows_widget.setStyleSheet("background: transparent;")
        self._recent_rows_layout = QVBoxLayout(self._recent_rows_widget)
        self._recent_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_rows_layout.setSpacing(6)
        v.addWidget(self._recent_rows_widget)

        return widget

    def _get_project_manager(self):
        return self._controller.get_project_manager()

    def _get_service_locator(self):
        return self._controller.get_service_locator()

    def _ensure_service(self) -> SampleService | None:
        self._service = self._controller.ensure_service(self._service)
        return self._service

    def _load_all(self) -> None:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            self._show_no_project_state()
            return

        self._show_project_state(pm.current_project)

        service = self._ensure_service()
        if service is None:
            return

        self._load_stats(service)
        self._load_samples(service)
        self._load_recent(service)

    def _show_no_project_state(self) -> None:
        self._proj_name_label.setText("无活动项目")
        self._proj_desc_label.setText('请在\u201c项目管理\u201d中创建或选择一个项目')
        self._stat_samples.setText("样本数: —")
        self._stat_execs.setText("执行数: —")
        self._stat_success.setText("成功数: —")
        self._stat_disk.setText("磁盘占用: —")
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

    def _load_stats(self, service: SampleService) -> None:
        stats = service.get_project_stats()
        self._stat_samples.setText(f"样本数: {stats.sample_count}")
        self._stat_execs.setText(f"执行数: {stats.exec_count}")
        self._stat_success.setText(f"成功数: {stats.success_count}")

        disk = service.get_disk_usage()
        if disk:
            self._stat_disk.setText(f"磁盘占用: {disk[0]:.1f} / {disk[1]:.0f} GB")
        else:
            self._stat_disk.setText("磁盘占用: —")

    def _load_samples(self, service: SampleService) -> None:
        sample_cards = service.list_sample_cards(self._search_text)

        self._clear_grid()
        self._card_widgets.clear()

        col_count = 2
        for idx, sample in enumerate(sample_cards):
            card = SampleCard(
                sample_id=sample.sample_id,
                name=sample.name,
                source=sample.source,
                stage_statuses=sample.stage_statuses,
                stages=self._stages,
                last_activity=sample.last_activity,
            )
            card.delete_requested.connect(self._on_delete_sample)
            card.continue_requested.connect(self._on_continue_analysis)
            card.results_requested.connect(self._on_view_results)

            grid_row = idx // col_count
            grid_col = idx % col_count
            self._grid_layout.addWidget(card, grid_row, grid_col, Qt.AlignmentFlag.AlignTop)
            self._card_widgets.append(card)

        placeholder = AddSamplePlaceholder()
        placeholder.clicked.connect(self._on_add_sample)
        total = len(sample_cards)
        ph_row = total // col_count
        ph_col = total % col_count
        self._grid_layout.addWidget(placeholder, ph_row, ph_col, Qt.AlignmentFlag.AlignTop)

        if not sample_cards:
            self._empty_label.hide()

    def _load_recent(self, service: SampleService) -> None:
        self._clear_recent()
        recent = service.list_recent_executions(limit=5)

        if not recent:
            placeholder = QLabel("暂无执行记录")
            placeholder.setStyleSheet(
                "font-size: 13px; color: #94A3B8; background: transparent; font-weight: 500;"
            )
            self._recent_rows_layout.addWidget(placeholder)
            return

        for exec_info in recent:
            icon = _RECENT_STATUS_ICONS.get(exec_info.status, "[未知]")
            time_text = human_time_ago(exec_info.created_at) if exec_info.created_at else "—"
            text = f"{icon}  {exec_info.tool_id}  ·  {exec_info.sample_name}  ·  {time_text}"

            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"font-size: 12px; color: {styles.COLOR_TEXT_SUB}; background: transparent; font-weight: 500;"
            )
            self._recent_rows_layout.addWidget(lbl)

    def _clear_grid(self) -> None:
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear_recent(self) -> None:
        while self._recent_rows_layout.count():
            item = self._recent_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        service = self._ensure_service()
        if service:
            self._load_samples(service)

    def _on_add_sample(self) -> None:
        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            QMessageBox.information(self, "提示", "请先选择一个项目")
            return

        dialog = SampleAddDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            service = self._ensure_service()
            if service is None:
                return

            try:
                self._controller.add_sample(
                    name=dialog.sample_name,
                    source=dialog.source,
                    r1_path=dialog.r1_path,
                    r2_path=dialog.r2_path,
                    service=service,
                )
                self._load_all()
            except Exception as e:
                QMessageBox.critical(self, "数据库错误", str(e))
                logger.exception("添加样本失败")

    def _on_delete_sample(self, sample_id: str) -> None:
        pm = self._get_project_manager()
        if pm is None:
            return

        service = self._ensure_service()
        if service is None:
            return

        name = self._controller.get_sample_name(service, sample_id)

        reply = QMessageBox.question(
            self,
            "确认删除",
            f'确定要删除样本\u201c{name}\u201d及其所有执行记录吗？\n此操作不可撤销。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._controller.delete_sample(service, sample_id):
            self._load_all()
        else:
            QMessageBox.critical(self, "删除失败", "删除样本时发生错误")

    def _on_continue_analysis(self, sample_id: str) -> None:
        service = self._ensure_service()
        if service is None:
            return

        self._controller.open_analysis_for_sample(service, sample_id)

    def _on_view_results(self, sample_id: str) -> None:
        QMessageBox.information(
            self,
            "功能开发中",
            "结果浏览页正在开发中，敬请期待。",
        )
