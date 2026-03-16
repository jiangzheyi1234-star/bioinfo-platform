from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    BUTTON_LINK,
    BUTTON_SUCCESS,
    CARD_FRAME,
    CARD_TITLE,
    INPUT_LINEEDIT,
    LABEL_MUTED,
)

# (config_key, 显示名称, 默认占位路径)
_DB_FIELDS: list[tuple[str, str, str]] = [
    ("kraken2",     "Kraken2 标准库",       "/h2ometa/databases/kraken2_standard"),
    ("centrifuge",  "Centrifuge HPVC 库",   "/home/zyserver/project/lcy_project/my_database/hpvc"),
    ("checkm2",    "CheckM2 数据库",        "/h2ometa/databases/checkm2"),
    ("gtdbtk",     "GTDB-Tk r220",         "/h2ometa/databases/gtdbtk/release220"),
    ("blast_nt",   "BLAST NT 库",           "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt"),
]


class DatabasePathsCard(QFrame):
    """参考数据库路径管理卡片。

    五条路径（kraken2 / centrifuge / checkm2 / gtdbtk / blast_nt），
    默认只读，点击「修改」后可编辑，点击「保存」发出 request_save 信号。
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DatabasePathsCard")
        self._in_edit_mode = False
        self._external_lock = False

        # 动态生成的输入框 {key: QLineEdit}
        self._edits: dict[str, QLineEdit] = {}

        self._build_ui()
        self._lock_inputs()

    # -------------------------
    # Public API
    # -------------------------
    def set_values(self, databases: dict) -> None:
        """回填路径数据。"""
        for key, _, _ in _DB_FIELDS:
            edit = self._edits.get(key)
            if edit is not None:
                edit.setText(str(databases.get(key, "") or ""))

    def get_values(self) -> dict:
        """返回 {key: path} 字典。"""
        return {key: (self._edits[key].text().strip() if key in self._edits else "")
                for key, _, _ in _DB_FIELDS}

    def set_external_lock(self, locked: bool) -> None:
        if self._external_lock == locked:
            return
        self._external_lock = locked
        if locked:
            for edit in self._edits.values():
                edit.setEnabled(False)
            self.modify_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
        else:
            self._lock_inputs()

    # -------------------------
    # Internal UI
    # -------------------------
    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("DatabasePathsCard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 卡片头部
        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 10)

        title = QLabel("参考数据库路径")
        title.setStyleSheet(CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setMinimumWidth(60)
        self.modify_btn.setStyleSheet(BUTTON_LINK)
        self.modify_btn.clicked.connect(self._unlock_inputs)

        self.save_btn = QPushButton("保存")
        self.save_btn.setMinimumWidth(60)
        self.save_btn.setStyleSheet(BUTTON_SUCCESS)
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.hide()

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_btn)
        header_layout.addWidget(self.save_btn)
        main_layout.addWidget(header)

        # 内容区
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 0, 20, 20)
        content_layout.setSpacing(10)

        # 每条数据库路径一行
        for key, label_text, placeholder in _DB_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(8)

            lbl = QLabel(label_text)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet("font-size: 12px; color: rgba(60,60,67,0.7); background: transparent;")

            edit = QLineEdit()
            edit.setStyleSheet(INPUT_LINEEDIT)
            edit.setPlaceholderText(placeholder)
            self._edits[key] = edit

            hint_btn = QPushButton("?")
            hint_btn.setFixedSize(22, 22)
            hint_btn.setStyleSheet(
                "QPushButton { border: 1px solid rgba(60,60,67,0.2); border-radius: 11px;"
                "  font-size: 11px; color: rgba(60,60,67,0.5); background: transparent; }"
                "QPushButton:hover { background: rgba(60,60,67,0.08); }"
            )
            hint_btn.setToolTip(f"填写服务器上 {label_text} 的绝对路径。\n留空则运行相关工具时会要求临时指定。")
            hint_btn.clicked.connect(lambda checked, btn=hint_btn: QToolTip.showText(
                btn.mapToGlobal(btn.rect().bottomLeft()), btn.toolTip()
            ))

            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(hint_btn)
            content_layout.addLayout(row)

        # 提示文字
        tip = QLabel("未填写的数据库在运行对应工具时会要求临时指定路径")
        tip.setStyleSheet(LABEL_MUTED)
        tip.setWordWrap(True)
        content_layout.addWidget(tip)

        main_layout.addWidget(content)

    def _lock_inputs(self) -> None:
        for edit in self._edits.values():
            edit.setEnabled(False)
        self._in_edit_mode = False
        self.modify_btn.show()
        self.save_btn.hide()

    def _unlock_inputs(self) -> None:
        if self._external_lock:
            return
        for edit in self._edits.values():
            edit.setEnabled(True)
        self._in_edit_mode = True
        self.modify_btn.hide()
        self.save_btn.show()

    def _on_save(self) -> None:
        self.request_save.emit()
        self._lock_inputs()
