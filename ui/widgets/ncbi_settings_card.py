from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    CARD_TITLE,
    FORM_LABEL,
    LABEL_MUTED,
    BUTTON_LINK,
    BUTTON_SUCCESS,
)


class NcbiSettingsCard(QFrame):
    """NCBI 设置卡片组件。

    Contract:
      - set_values()/get_values()：与 SettingsPage 做配置同步。
      - request_save：用户点“保存”时发出，让 SettingsPage 决定如何写入配置文件。
      - lock_if_needed：保存后按 key 是否为空自动锁定/解锁。
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NCBICard")
        self._in_edit_mode = False
        self._external_lock = False

        self._build_ui()
        self._lock_inputs()

    # -------------------------
    # Public API: config sync
    # -------------------------
    def set_values(self, ncbi_api_key: str = "") -> None:
        self.ncbi_api_key.setText(str(ncbi_api_key or ""))
        if (ncbi_api_key or "").strip():
            self._lock_inputs()
        else:
            self._unlock_inputs()

    def get_values(self) -> dict:
        return {"ncbi_api_key": self.ncbi_api_key.text().strip()}

    def lock_if_needed(self) -> None:
        if self.ncbi_api_key.text().strip():
            self._lock_inputs()
        else:
            self._unlock_inputs()

    def set_external_lock(self, locked: bool) -> None:
        if self._external_lock == locked:
            return
        self._external_lock = locked
        if locked:
            self.status_label.setText("系统设置已锁定")
            for w in [self.ncbi_api_key, self.modify_btn, self.save_btn]:
                w.setEnabled(False)
        else:
            self.lock_if_needed()

    # -------------------------
    # Internal UI
    # -------------------------
    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("NCBICard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 10)

        title = QLabel("NCBI 服务配置")
        title.setStyleSheet(CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setFixedWidth(60)
        self.modify_btn.setStyleSheet(BUTTON_LINK)
        self.modify_btn.clicked.connect(self._unlock_inputs)

        self.save_btn = QPushButton("保存")
        self.save_btn.setFixedWidth(60)
        self.save_btn.setStyleSheet(BUTTON_SUCCESS)
        self.save_btn.clicked.connect(self.request_save.emit)
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
        content_layout.setSpacing(12)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.ncbi_api_key = QLineEdit()
        self.ncbi_api_key.setStyleSheet(INPUT_LINEEDIT)
        self.ncbi_api_key.setPlaceholderText("可选：填写 NCBI API Key")

        label = QLabel("NCBI API Key")
        form.addRow(label, self.ncbi_api_key)
        content_layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(LABEL_MUTED)
        content_layout.addWidget(self.status_label)

        main_layout.addWidget(content)

    # -------------------------
    # State helpers
    # -------------------------
    def _lock_inputs(self) -> None:
        self.ncbi_api_key.setEnabled(False)
        self._in_edit_mode = False
        self.modify_btn.show()
        self.save_btn.hide()
        # 显示当前状态信息
        api_key = self.ncbi_api_key.text().strip()
        if api_key:
            self.status_label.setText("状态：已配置 API Key")
        else:
            self.status_label.setText("状态：未配置 API Key")

    def _unlock_inputs(self) -> None:
        if self._external_lock:
            return
        self.ncbi_api_key.setEnabled(True)
        self._in_edit_mode = True
        self.modify_btn.hide()
        self.save_btn.show()
        self.status_label.setText("请填写 NCBI API Key 并点击保存")
