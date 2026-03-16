"""项目管理页面：创建、打开、归档与导出项目。"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect
)
from PyQt6.QtGui import QColor

from core.pipeline.project_exporter import ProjectExporter
from core.data.project_manager import ProjectInfo, ProjectManager
from ui.page_base import BasePage
from ui.widgets import styles
from ui.widgets.export_dialog import ExportDialog

logger = logging.getLogger(__name__)


class CreateProjectDialog(QDialog):
    """创建新项目对话框。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("创建新项目")
        self.setFixedSize(420, 260)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_CARD};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        name_label = QLabel("项目名称")
        name_label.setStyleSheet(styles.FORM_LABEL)
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：人体肠道宏基因组分析")
        self.name_input.setStyleSheet(styles.INPUT_LINEEDIT)
        layout.addWidget(self.name_input)

        desc_label = QLabel("项目描述（可选）")
        desc_label.setStyleSheet(styles.FORM_LABEL)
        layout.addWidget(desc_label)

        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("简要描述分析目标...")
        self.desc_input.setMaximumHeight(70)
        self.desc_input.setStyleSheet(
            f"""
            QTextEdit {{
                padding: 8px 12px;
                border: 1px solid {styles.COLOR_BORDER_INPUT};
                border-radius: {styles.RADIUS_CTRL};
                background-color: {styles.COLOR_BG_CARD};
                color: {styles.COLOR_TEXT_DEFAULT};
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border: 1px solid {styles.COLOR_BORDER_FOCUS};
            }}
            """
        )
        layout.addWidget(self.desc_input)

        btn_box = QDialogButtonBox()
        self.btn_create = QPushButton("创建")
        self.btn_create.setStyleSheet(styles.BUTTON_PRIMARY)
        self.btn_create.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(styles.BUTTON_SECONDARY)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_box.addButton(self.btn_create, QDialogButtonBox.ButtonRole.AcceptRole)
        btn_box.addButton(self.btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_values(self) -> tuple[str, str]:
        return self.name_input.text().strip(), self.desc_input.toPlainText().strip()


class ProjectCard(QFrame):
    """单个项目卡片。"""

    open_clicked = pyqtSignal(str)
    archive_clicked = pyqtSignal(str)
    export_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, project: ProjectInfo, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._project = project
        self.setObjectName(f"ProjectCard_{project.project_id}")
        self.setStyleSheet(f"""
            QFrame#{self.objectName()} {{
                background: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: {styles.RADIUS_CARD};
            }}
            QFrame#{self.objectName()}:hover {{
                border: 1px solid {styles.COLOR_TEXT_HINT};
            }}
        """)
        styles.apply_card_shadow(self)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(20)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        name_label = QLabel(self._project.name)
        name_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {styles.COLOR_TEXT_TITLE};"
            f" background: transparent;"
        )
        info_layout.addWidget(name_label)

        desc_text = self._project.description or "无描述"
        if len(desc_text) > 80:
            desc_text = desc_text[:80] + "..."
        desc_label = QLabel(desc_text)
        desc_label.setStyleSheet(
            f"font-size: 13px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        info_layout.addWidget(desc_label)

        created = time.strftime("%Y-%m-%d", time.localtime(self._project.created_at))
        status_text = "活跃" if self._project.status == "active" else "已归档"
        meta_label = QLabel(f"创建于 {created} | {status_text}")
        meta_label.setStyleSheet(
            f"font-size: 11px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
        )
        info_layout.addWidget(meta_label)

        info_layout.addStretch()
        layout.addLayout(info_layout, stretch=1)

        action_row = QHBoxLayout()
        action_row.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        action_row.setSpacing(10)

        action_wrap = QWidget()
        action_wrap.setMinimumWidth(320)
        action_wrap.setMaximumWidth(360)
        action_wrap.setLayout(action_row)

        if self._project.status == "active":
            open_btn = QPushButton("打开")
            open_btn.setStyleSheet(styles.BUTTON_PASTEL_PRIMARY)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setMinimumWidth(86)
            open_btn.setMinimumHeight(34)
            open_btn.clicked.connect(lambda: self.open_clicked.emit(self._project.project_id))
            action_row.addWidget(open_btn)

            export_btn = QPushButton("导出")
            export_btn.setStyleSheet(styles.BUTTON_SECONDARY)
            export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            export_btn.setMinimumWidth(86)
            export_btn.setMinimumHeight(34)
            export_btn.clicked.connect(lambda: self.export_clicked.emit(self._project.project_id))
            action_row.addWidget(export_btn)

            archive_btn = QPushButton("归档")
            archive_btn.setStyleSheet(styles.BUTTON_DANGER)
            archive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            archive_btn.setMinimumWidth(86)
            archive_btn.setMinimumHeight(34)
            archive_btn.clicked.connect(lambda: self.archive_clicked.emit(self._project.project_id))
            action_row.addWidget(archive_btn)
        else:
            archived_label = QLabel("已归档")
            archived_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            archived_label.setMinimumWidth(96)
            archived_label.setStyleSheet(
                f"font-size: 13px; color: {styles.COLOR_TEXT_HINT}; background: transparent;"
            )
            action_row.addWidget(archived_label)

            # 已归档的项目可以删除
            delete_btn = QPushButton("删除")
            delete_btn.setStyleSheet(styles.BUTTON_DANGER)
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setMinimumWidth(86)
            delete_btn.setMinimumHeight(34)
            delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self._project.project_id))
            action_row.addWidget(delete_btn)

        layout.addWidget(action_wrap)


class ProjectPage(BasePage):
    """项目管理页面。"""

    project_switched = pyqtSignal(str)

    def __init__(
        self,
        project_manager: ProjectManager,
        main_window: Optional[QWidget] = None,
        service_locator=None,
    ):
        super().__init__("项目管理")
        if hasattr(self, "label"):
            self.label.hide()

        self._pm = project_manager
        self.main_window = main_window
        self._locator = service_locator

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()
        self._refresh_list()

        self._pm.project_created.connect(lambda _: self._refresh_list())
        self._pm.project_archived.connect(lambda _: self._refresh_list())
        self._pm.project_deleted.connect(lambda _: self._refresh_list())

    def _build_ui(self) -> None:
        self.layout.setContentsMargins(30, 20, 30, 20)
        self.layout.setSpacing(16)

        header_row = QHBoxLayout()
        header = QLabel("项目管理")
        header.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {styles.COLOR_TEXT_TITLE};"
            "background: transparent; letter-spacing: -0.5px;"
        )
        header_row.addWidget(header)
        header_row.addStretch()

        self.btn_create = QPushButton("+ 新建项目")
        self.btn_create.setStyleSheet(styles.BUTTON_PRIMARY + """
            QPushButton {
                padding: 10px 20px;
                font-size: 14px;
            }
        """)
        self.btn_create.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_create.clicked.connect(self._on_create)
        header_row.addWidget(self.btn_create)
        self.layout.addLayout(header_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {styles.COLOR_BORDER}; max-height: 1px; border: none;")
        self.layout.addWidget(line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.verticalScrollBar().setStyleSheet(styles.SCROLL_BAR_ELEGANT)

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background-color: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 10, 0)
        self._cards_layout.setSpacing(16)

        scroll.setWidget(self._cards_container)
        self.layout.addWidget(scroll)

    def _refresh_list(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._pm.reload_index()
        projects = self._pm.list_projects()
        if not projects:
            empty_label = QLabel("暂无项目，点击上方按钮创建")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(
                f"color: {styles.COLOR_TEXT_HINT}; font-size: 15px; font-weight: 500; padding: 60px;"
                f" background: transparent;"
            )
            self._cards_layout.addWidget(empty_label)
        else:
            for project in projects:
                card = ProjectCard(project)
                card.open_clicked.connect(self._on_open)
                card.archive_clicked.connect(self._on_archive)
                card.export_clicked.connect(self._on_export)
                card.delete_clicked.connect(self._on_delete)
                self._cards_layout.addWidget(card)

        self._cards_layout.addStretch()

    def _on_create(self) -> None:
        dialog = CreateProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, desc = dialog.get_values()
            if not name:
                QMessageBox.warning(self, "提示", "项目名称不能为空")
                return
            try:
                project_id = self._pm.create_project(name, desc)
                self._pm.open_project(project_id)
                self.project_switched.emit(project_id)
            except Exception as e:
                logger.error("创建项目失败: %s", e)
                QMessageBox.critical(self, "错误", f"创建项目失败: {e}")

    def _on_open(self, project_id: str) -> None:
        try:
            self._pm.open_project(project_id)
            self.project_switched.emit(project_id)
            self._refresh_list()
        except Exception as e:
            logger.error("打开项目失败: %s", e)
            QMessageBox.critical(self, "错误", f"打开项目失败: {e}")

    def _on_archive(self, project_id: str) -> None:
        result = QMessageBox.question(
            self,
            "确认归档",
            "归档后项目将无法打开，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            try:
                self._pm.archive_project(project_id)
            except Exception as e:
                logger.error("归档项目失败: %s", e)
                QMessageBox.critical(self, "错误", f"归档失败: {e}")

    def _on_export(self, project_id: str) -> None:
        current = self._pm.current_project
        if current is None or current.project_id != project_id:
            QMessageBox.information(self, "提示", "请先打开该项目再导出")
            return

        try:
            db = self._pm.db
            plugin_descriptors: dict = {}
            if self._locator and self._locator.plugin_registry:
                reg = self._locator.plugin_registry
                for tid in reg.list_all_ids():
                    try:
                        plugin_descriptors[tid] = reg.get_descriptor(tid)
                    except Exception:
                        pass

            exporter = ProjectExporter(
                conn=db,
                plugin_descriptors=plugin_descriptors,
                project_name=current.name,
            )

            from pathlib import Path

            project_dir = str(Path.home() / ".h2ometa" / "projects" / project_id)
            dialog = ExportDialog(exporter, project_dir=project_dir, parent=self)
            dialog.exec()

        except Exception as e:
            logger.error("打开导出对话框失败: %s", e)
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _on_delete(self, project_id: str) -> None:
        """删除项目（包括文件和索引记录）"""
        result = QMessageBox.question(
            self,
            "确认删除",
            "删除后项目文件将被永久删除，无法恢复，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            try:
                self._pm.delete_project(project_id)
                QMessageBox.information(self, "成功", "项目已删除")
            except Exception as e:
                logger.error("删除项目失败: %s", e)
                QMessageBox.critical(self, "错误", f"删除失败: {e}")



