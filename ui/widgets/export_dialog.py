"""导出对话框 — 调用 ProjectExporter 生成论文/归档输出。

支持两种导出模式:
  1. 论文导出 — methods.txt + parameters.csv
  2. 归档导出 — 完整项目快照 .zip
"""
import logging
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)


class _ExportWorker(QThread):
    """后台执行导出任务"""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)   # {filename: filepath}
    failed = pyqtSignal(str)

    def __init__(self, exporter, mode: str, output_dir: str, project_dir: str = ""):
        super().__init__()
        self._exporter = exporter
        self._mode = mode           # "paper" | "archive"
        self._output_dir = output_dir
        self._project_dir = project_dir

    def run(self) -> None:
        try:
            if self._mode == "paper":
                self.progress.emit("正在生成 methods.txt 和 parameters.csv...")
                result = self._exporter.export_for_paper(self._output_dir)
            else:
                self.progress.emit("正在打包项目归档...")
                result = self._exporter.export_archive(
                    self._output_dir, self._project_dir
                )
            self.finished.emit(result)
        except Exception as e:
            logger.exception("导出失败")
            self.failed.emit(str(e))


class ExportDialog(QDialog):
    """项目导出对话框

    用法::

        dialog = ExportDialog(exporter, project_dir, parent=self)
        dialog.exec()
    """

    def __init__(self, exporter, project_dir: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._exporter = exporter
        self._project_dir = project_dir
        self._worker: Optional[_ExportWorker] = None

        self.setWindowTitle("导出项目")
        self.setFixedSize(480, 340)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_CARD};")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # 标题
        title = QLabel("选择导出格式")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 选项卡片：论文导出
        paper_card = self._make_option_card(
            "论文导出",
            "生成 methods.txt（可直接粘贴到论文方法段）\n和 parameters.csv（完整参数表）",
            "导出",
            self._on_paper_export,
        )
        layout.addWidget(paper_card)

        # 选项卡片：归档导出
        archive_card = self._make_option_card(
            "归档导出",
            "将完整项目（数据库 + 执行记录）\n打包为 .zip 文件，用于长期保存或分享",
            "导出",
            self._on_archive_export,
        )
        layout.addWidget(archive_card)

        # 进度行
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(styles.LABEL_HINT)
        self._progress_label.hide()
        layout.addWidget(self._progress_label)

        self._pbar = QProgressBar()
        self._pbar.setRange(0, 0)
        self._pbar.setStyleSheet(styles.PROGRESS_BAR)
        self._pbar.setFixedHeight(4)
        self._pbar.hide()
        layout.addWidget(self._pbar)

        # 关闭按钮
        layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _make_option_card(
        self, title: str, desc: str, btn_text: str, callback
    ) -> QWidget:
        card = QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background: {styles.COLOR_BG_PAGE};
                border-radius: {styles.RADIUS_CARD};
                padding: 2px;
            }}
        """)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {styles.COLOR_TEXT_TITLE};"
            f" background: transparent;"
        )
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(
            f"font-size: 12px; color: {styles.COLOR_TEXT_SUB}; background: transparent;"
        )
        desc_lbl.setWordWrap(True)
        text_col.addWidget(title_lbl)
        text_col.addWidget(desc_lbl)
        row.addLayout(text_col, stretch=1)

        btn = QPushButton(btn_text)
        btn.setStyleSheet(styles.BUTTON_PRIMARY)
        btn.setFixedWidth(72)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        row.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        return card

    # ── 导出逻辑 ──────────────────────────────────────────────

    def _on_paper_export(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not output_dir:
            return
        self._start_export("paper", output_dir)

    def _on_archive_export(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if not output_dir:
            return
        self._start_export("archive", output_dir)

    def _start_export(self, mode: str, output_dir: str) -> None:
        self._progress_label.show()
        self._pbar.show()

        self._worker = _ExportWorker(
            self._exporter, mode, output_dir, self._project_dir
        )
        self._worker.progress.connect(self._progress_label.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, result: dict) -> None:
        self._pbar.hide()
        files = "\n".join(f"  • {os.path.basename(p)}" for p in result.values())
        self._progress_label.setText(f"导出完成！已生成 {len(result)} 个文件")
        QMessageBox.information(
            self, "导出成功",
            f"已生成以下文件:\n{files}\n\n保存至:\n{list(result.values())[0] if result else ''}",
        )
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def _on_failed(self, error: str) -> None:
        self._pbar.hide()
        self._progress_label.setText(f"导出失败: {error}")
        QMessageBox.critical(self, "导出失败", error)
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
