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
    FORM_LABEL,
    INPUT_LINEEDIT,
    LABEL_MUTED,
)

# (config_key, 显示名称, 默认占位路径)
_DB_FIELDS: list[tuple[str, str, str]] = [
    ("kraken2", "Kraken2 标准库", "/home/zyserver/project_ssd/common_data/kraken2_standard"),
    ("centrifuge", "Centrifuge HPVC 库", "/home/zyserver/project/lcy_project/my_database/hpvc"),
    ("checkm2", "CheckM2 数据库", "/h2ometa/databases/checkm2"),
    ("gtdbtk", "GTDB-Tk r220", "/h2ometa/databases/gtdbtk/release220"),
    ("blast_nt", "BLAST NT 库", "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt"),
]


class DatabasePathsCard(QFrame):
    """参考数据库路径管理卡片。

    五条路径（kraken2 / centrifuge / checkm2 / gtdbtk / blast_nt），
    默认只读，点击“修改”后可编辑，点击“保存”发出 request_save 信号。
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DatabasePathsCard")
        self._in_edit_mode = False
        self._external_lock = False

        # 动态生成的输入框和状态标签
        self._edits: dict[str, QLineEdit] = {}
        self._state_labels: dict[str, QLabel] = {}

        self._build_ui()
        self._lock_inputs()

    def set_values(self, databases: dict) -> None:
        """回填路径数据。"""
        for key, _, _ in _DB_FIELDS:
            edit = self._edits.get(key)
            if edit is not None:
                edit.setText(str(databases.get(key, "") or ""))
                self._apply_field_state(key)

    def get_values(self) -> dict:
        """返回 {key: path} 字典。"""
        return {
            key: (self._edits[key].text().strip() if key in self._edits else "")
            for key, _, _ in _DB_FIELDS
        }

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

    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("DatabasePathsCard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

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

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 0, 20, 20)
        content_layout.setSpacing(10)

        for key, label_text, placeholder in _DB_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(8)

            lbl = QLabel(label_text)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet(FORM_LABEL)

            edit = QLineEdit()
            edit.setStyleSheet(INPUT_LINEEDIT)
            edit.setPlaceholderText(placeholder)
            edit.textChanged.connect(lambda _=None, k=key: self._apply_field_state(k))
            self._edits[key] = edit

            state_lbl = QLabel("未配置")
            state_lbl.setFixedWidth(52)
            state_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
            self._state_labels[key] = state_lbl

            hint_btn = QPushButton("?")
            hint_btn.setFixedSize(22, 22)
            hint_btn.setStyleSheet(
                "QPushButton { border: 1px solid #D6EAF8; border-radius: 11px;"
                "  font-size: 11px; color: #4A7A90; background: transparent; }"
                "QPushButton:hover { background: #EFF6FF; }"
            )
            hint_btn.setToolTip(f"填写服务器上 {label_text} 的绝对路径。\n留空则运行相关工具时会要求临时指定。")
            hint_btn.clicked.connect(
                lambda checked, btn=hint_btn: QToolTip.showText(
                    btn.mapToGlobal(btn.rect().bottomLeft()), btn.toolTip()
                )
            )

            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(state_lbl)
            row.addWidget(hint_btn)
            content_layout.addLayout(row)
            self._apply_field_state(key)

        tip = QLabel("未填写的数据库在运行对应工具时会要求临时指定路径")
        tip.setStyleSheet(LABEL_MUTED)
        tip.setWordWrap(True)
        content_layout.addWidget(tip)

        main_layout.addWidget(content)

    def _lock_inputs(self) -> None:
        for edit in self._edits.values():
            edit.setEnabled(False)
        for key in self._edits.keys():
            self._apply_field_state(key)
        self._in_edit_mode = False
        self.modify_btn.show()
        self.save_btn.hide()

    def _unlock_inputs(self) -> None:
        if self._external_lock:
            return
        for edit in self._edits.values():
            edit.setEnabled(True)
        for key in self._edits.keys():
            self._apply_field_state(key)
        self._in_edit_mode = True
        self.modify_btn.hide()
        self.save_btn.show()

    def _on_save(self) -> None:
        self.request_save.emit()
        self._lock_inputs()

    def _apply_field_state(self, key: str) -> None:
        edit = self._edits.get(key)
        state_lbl = self._state_labels.get(key)
        if edit is None:
            return

        configured = bool(edit.text().strip())
        if configured:
            edit.setStyleSheet(
                INPUT_LINEEDIT
                + "QLineEdit { border: 1px solid #34D399; background: rgba(16,185,129,0.10); color: #065F46; }"
                + "QLineEdit:disabled { border: 1px solid #34D399; background: rgba(16,185,129,0.08); color: #065F46; }"
            )
            if state_lbl is not None:
                state_lbl.setText("已配置")
                state_lbl.setStyleSheet("font-size: 11px; color: #059669; font-weight: 600;")
        else:
            edit.setStyleSheet(INPUT_LINEEDIT)
            if state_lbl is not None:
                state_lbl.setText("未配置")
                state_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
