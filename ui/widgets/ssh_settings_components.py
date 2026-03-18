from __future__ import annotations

from typing import Callable, Protocol

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from core.remote.ssh_connector import run_diagnostics
from ui.widgets.styles import (
    BUTTON_SECONDARY,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_HINT,
    COLOR_WARNING,
)


class NoArgSignal(Protocol):
    def connect(self, slot: Callable[[], None]) -> None: ...
    def emit(self) -> None: ...


class SSHDiagnosticWorker(QObject):
    """Thin worker that forwards diagnostics results from ssh_connector."""

    log = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, ip: str, port: int, user: str, pwd: str, key_file: str = "", parent=None):
        super().__init__(parent)
        self.ip, self.port, self.user, self.pwd = ip, port, user, pwd
        self.key_file = key_file

    @pyqtSlot()
    def run(self):
        self.log.emit("=" * 45)
        self.log.emit(f"  SSH 连接诊断 — {self.ip}:{self.port}")
        self.log.emit("=" * 45 + "\n")

        steps = run_diagnostics(
            ip=self.ip,
            port=self.port,
            user=self.user,
            password=self.pwd,
            key_file=self.key_file,
        )

        step_names = ["① 检查主机地址格式", "② TCP 连接", "③ SSH 协议握手", "④ 身份验证"]

        for idx, step in enumerate(steps):
            if idx < len(step_names):
                self.log.emit(f"{step_names[idx]}...")
            color_icon = '<span style="color: #A6E3A1;">✓</span>' if step.status == "ok" else '<span style="color: #F38BA8;">✗</span>'
            self.log.emit(f"   {color_icon} {step.message}\n")
            if step.status == "fail":
                break

        if all(step.status == "ok" for step in steps):
            self.log.emit("─" * 45)
            self.log.emit('<span style="color: #F9E2AF; font-weight: bold;">结论：所有检查通过，连接配置正常。</span>')
        else:
            failed = [step for step in steps if step.status == "fail"]
            self.log.emit(f"\n结论：{failed[0].message if failed else '检查失败'}")

        self.done.emit()


class SSHDiagnosticDialog(QDialog):
    """SSH diagnostics dialog."""

    def __init__(self, ip: str, port: int, user: str, pwd: str, key_file: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH 连接诊断")
        self.setMinimumSize(520, 400)
        self.resize(560, 440)
        self._close_requested = False
        self.setStyleSheet(
            """
            QDialog {
                background-color: #F0F7FF;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            """
            QTextEdit {
                font-family: 'Consolas', 'Microsoft YaHei UI', monospace;
                font-size: 13px;
                background-color: #F5F5F5;
                color: #333333;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QTextEdit QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 10px;
                margin: 0;
            }
            QTextEdit QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.15);
                border-radius: 5px;
                min-height: 40px;
            }
            QTextEdit QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.25);
            }
            QTextEdit QScrollBar::handle:vertical:pressed {
                background: rgba(0, 0, 0, 0.35);
            }
            QTextEdit QScrollBar::add-line:vertical, QTextEdit QScrollBar::sub-line:vertical {
                height: 0;
                background: transparent;
                border: none;
            }
            QTextEdit QScrollBar::add-page:vertical, QTextEdit QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )
        layout.addWidget(self.output)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.setStyleSheet(BUTTON_SECONDARY)
        self.close_btn.setMinimumWidth(80)
        self.close_btn.clicked.connect(self._on_close_requested)
        self.close_btn.setEnabled(False)
        button_row.addWidget(self.close_btn)
        layout.addLayout(button_row)

        self._thread = QThread(self)
        self._worker = SSHDiagnosticWorker(ip, port, user, pwd, key_file)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._worker.done.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _append_log(self, text: str) -> None:
        html = text.replace("✓", '<span style="color: #A6E3A1;">✓</span>')
        html = html.replace("✗", '<span style="color: #F38BA8;">✗</span>')
        if html.startswith("结论"):
            html = f'<span style="color: #F9E2AF; font-weight: bold;">{html}</span>'
        self.output.append(html)

    def _on_done(self) -> None:
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")
        if self._close_requested:
            self.accept()

    def _on_close_requested(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._close_requested = True
            self.close_btn.setEnabled(False)
            self.close_btn.setText("Running...")
            return
        self.accept()

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._close_requested = True
            self.close_btn.setEnabled(False)
            self.close_btn.setText("Running...")
            event.ignore()
            return
        super().closeEvent(event)


class ClickableHeader(QFrame):
    clicked: NoArgSignal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StepIndicator(QWidget):
    """Three-step SSH progress indicator."""

    STEP_LABELS = ["TCP 连接", "SSH 握手", "身份验证"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(0)

        self._icons: list[QLabel] = []
        self._labels: list[QLabel] = []

        for idx, label_text in enumerate(self.STEP_LABELS):
            if idx > 0:
                arrow = QLabel("  →  ")
                arrow.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")
                layout.addWidget(arrow)

            icon = QLabel("○")
            icon.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 13px; background: transparent;")
            icon.setFixedWidth(16)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._icons.append(icon)

            label = QLabel(label_text)
            label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")
            self._labels.append(label)

            layout.addWidget(icon)
            layout.addWidget(label)

        layout.addStretch()

    def reset(self) -> None:
        for icon, label in zip(self._icons, self._labels):
            icon.setText("○")
            icon.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")

    def set_step(self, index: int, status: str) -> None:
        if index < 0 or index >= len(self._icons):
            return

        icon = self._icons[index]
        label = self._labels[index]

        if status == "running":
            icon.setText("●")
            icon.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; background: transparent;")
        elif status == "ok":
            icon.setText("✓")
            icon.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 12px; font-weight: 600; background: transparent;")
        elif status == "fail":
            icon.setText("✗")
            icon.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 12px; font-weight: 600; background: transparent;")
