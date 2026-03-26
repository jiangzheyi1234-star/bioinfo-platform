from __future__ import annotations

import logging

import json

from PyQt6.QtCore import Qt, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtWidgets import QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from ui.widgets import styles
from ui.widgets.styles import (
    BUTTON_PRIMARY,
    COLOR_BG_PAGE,
    COLOR_TEXT_HINT,
    SCROLL_BAR_ELEGANT,
)

logger = logging.getLogger(__name__)


def cleanup_thread_pair(owner, thread_attr: str, worker_attr: str, wait_ms: int) -> None:
    """Stop/delete a (thread, worker) pair stored on an object."""
    worker = getattr(owner, worker_attr, None)
    if worker is not None:
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except RuntimeError:
                logger.debug("Worker already deleted during cancellation", exc_info=True)

    thread = getattr(owner, thread_attr, None)
    if thread is not None:
        if thread.isRunning():
            thread.quit()
            thread.wait(wait_ms)
        thread.deleteLater()
        try:
            delattr(owner, thread_attr)
        except AttributeError:
            pass

    worker = getattr(owner, worker_attr, None)
    if worker is not None:
        worker.deleteLater()
        try:
            delattr(owner, worker_attr)
        except AttributeError:
            pass


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ToolEnvBridge(QObject):
    """Bridge between Python and JavaScript via QWebChannel."""

    toolListLoaded = pyqtSignal(str, arguments=["json"])
    checkStarted = pyqtSignal(arguments=[])
    toolChecked = pyqtSignal(str, bool, arguments=["tool_id", "ok"])
    checkFinished = pyqtSignal(str, arguments=["result_json"])
    installStarted = pyqtSignal(str, arguments=["tool_id"])
    installFinished = pyqtSignal(str, bool, arguments=["tool_id", "success"])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tools: list[dict] = []
        self._parent_card = parent

    def set_tools(self, tools: list[dict]) -> None:
        self._tools = tools
        self.toolListLoaded.emit(json.dumps(tools, ensure_ascii=False))

    def get_tools(self) -> list[dict]:
        return self._tools

    @pyqtSlot(result=str)
    def getTools(self) -> str:
        return json.dumps(self._tools, ensure_ascii=False)

    @pyqtSlot()
    def startCheck(self) -> None:
        if self._parent_card:
            self._parent_card._on_batch_check_from_web()

    @pyqtSlot(str)
    def installTool(self, tool_id: str) -> None:
        if self._parent_card:
            self._parent_card._on_install_from_web(tool_id)

    @pyqtSlot(int)
    def setHeight(self, height: int) -> None:
        web_view = getattr(self._parent_card, "_web_view", None) if self._parent_card else None
        if web_view:
            web_view.setFixedHeight(max(45, min(height + 10, 400)))

    def emit_check_started(self) -> None:
        self.checkStarted.emit()

    def emit_tool_checked(self, tool_id: str, ok: bool) -> None:
        self.toolChecked.emit(tool_id, ok)

    def emit_check_finished(self, ready_count: int, total_count: int) -> None:
        result = {"ready_count": ready_count, "total_count": total_count}
        self.checkFinished.emit(json.dumps(result, ensure_ascii=False))

    def emit_install_started(self, tool_id: str) -> None:
        self.installStarted.emit(tool_id)

    def emit_install_finished(self, tool_id: str, success: bool) -> None:
        self.installFinished.emit(tool_id, success)


class EnvInstallDialog(QDialog):
    """Tool conda-environment installation dialog (UI shell only)."""

    install_requested = pyqtSignal(str)

    def __init__(self, tool_info: dict, conda_executable: str = "", parent=None):
        super().__init__(parent)
        self.tool_info = tool_info
        self._tool_id = str(self.tool_info.get("id", "") or "").strip()
        self._installing = False
        self._conda_executable = str(conda_executable or "")

        self.setWindowTitle("安装工具环境")
        self.setMinimumWidth(580)
        self.setMinimumHeight(440)
        self.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        tool_name = self.tool_info.get("name", self.tool_info.get("id", ""))
        conda_env = self.tool_info.get("conda_env", "")
        install_cmd = self.tool_info.get("install_cmd", "")
        databases = self.tool_info.get("databases", [])

        info_frame = QFrame()
        info_frame.setStyleSheet(
            f"background: {styles.COLOR_BG_INFO}; border: 1px solid {styles.COLOR_BG_INFO_BORDER}; border-radius: 6px;"
        )
        info_layout = QFormLayout(info_frame)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setVerticalSpacing(8)

        def _info_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size: 13px; color: {styles.COLOR_TEXT_DEFAULT};")
            return lbl

        info_layout.addRow("工具:", _info_lbl(f"{tool_name}  ({conda_env})"))
        info_layout.addRow("命令:", _info_lbl(install_cmd or "（未配置）"))

        if databases:
            db_ids = "、".join(d.get("id", "") for d in databases)
            db_hint = QLabel(
                f"⚠ 该工具需要数据库：{db_ids}\n"
                "安装环境完成后，请在「数据库路径配置」卡片中填写数据库路径。"
            )
            db_hint.setWordWrap(True)
            db_hint.setStyleSheet(
                f"color: {styles.COLOR_BG_WARN_TEXT}; background: {styles.COLOR_BG_WARN};"
                f"border: 1px solid rgba(251,191,36,0.3); border-radius: 4px;"
                "padding: 8px; font-size: 12px;"
            )
            info_layout.addRow("", db_hint)
        else:
            info_layout.addRow("数据库:", _info_lbl("无（不需要额外数据库）"))

        layout.addWidget(info_frame)

        output_title = QLabel("安装输出：")
        output_title.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(output_title)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            f"background: {styles.COLOR_BG_TERMINAL}; color: {styles.COLOR_BG_TERMINAL_TEXT};"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; border-radius: 4px; border: none;"
        )
        self.output_edit.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)
        self.output_edit.setMinimumHeight(180)
        layout.addWidget(self.output_edit)

        self.status_lbl = QLabel("点击「开始安装」执行 conda create 命令。安装可能需要 5-30 分钟。")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.install_btn = QPushButton("开始安装")
        self.install_btn.setFixedWidth(100)
        self.install_btn.setStyleSheet(BUTTON_PRIMARY)
        self.install_btn.clicked.connect(self._on_start_install)

        if not install_cmd:
            self.install_btn.setEnabled(False)
            self.status_lbl.setText("该工具未配置 install_cmd，无法自动安装。")
        elif not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self.install_btn.setEnabled(False)
            self.status_lbl.setText(f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。")

        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)

    def _on_start_install(self):
        if self._installing:
            return
        install_cmd = self.tool_info.get("install_cmd", "")
        if not install_cmd:
            return
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self.install_btn.setEnabled(False)
            self._set_status(
                f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。",
                f"color: {styles.COLOR_DANGER}; font-size: 12px;",
            )
            return

        self._installing = True
        self.install_btn.setEnabled(False)
        self.cancel_btn.setText("关闭")
        self._set_status(
            "正在提交后台安装任务……（安装在服务器端运行，关闭窗口不影响）",
            f"color: {styles.COLOR_PRIMARY}; font-size: 12px;",
        )
        self.output_edit.clear()
        self.install_requested.emit(self._tool_id)

    @pyqtSlot(str, dict)
    def on_snapshot_updated(self, tool_id: str, snapshot: dict) -> None:
        if str(tool_id or "").strip() != self._tool_id:
            return
        self.apply_install_snapshot(snapshot)

    def apply_install_snapshot(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            return
        status = str(snapshot.get("status", "") or "").strip().upper()
        message = str(snapshot.get("message", "") or "").strip()
        log_text = str(snapshot.get("log_text", "") or "")
        exit_code = str(snapshot.get("exit_code", "") or "").strip()

        if log_text:
            self.output_edit.setPlainText(log_text)
            scroll_bar = self.output_edit.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.maximum())

        if status == "SUBMITTING":
            self._installing = True
            self.install_btn.setEnabled(False)
            self.cancel_btn.setText("关闭")
            self._set_status(
                message or "正在提交后台安装任务……",
                f"color: {styles.COLOR_PRIMARY}; font-size: 12px;",
            )
            return

        if status in ("RUNNING", ""):
            self._installing = True
            self.install_btn.setEnabled(False)
            self.cancel_btn.setText("关闭")
            self._set_status(
                message or "安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
                f"color: {styles.COLOR_PRIMARY}; font-size: 12px;",
            )
            return

        if status == "DONE":
            self._installing = False
            self.install_btn.setText("关闭")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self.accept)
            self.cancel_btn.setText("关闭")
            self._set_status(
                message or "安装成功！",
                f"color: {styles.COLOR_SUCCESS}; font-size: 13px; font-weight: bold;",
            )
            return

        if status == "FAILED":
            self._installing = False
            self.install_btn.setText("重试")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self._on_start_install)
            self.cancel_btn.setText("关闭")
            if exit_code:
                fail_msg = message or f"安装失败 (exit_code={exit_code})，请检查上方输出后重试。"
            else:
                fail_msg = message or "安装失败，请检查上方输出或网络后重试。"
            self._set_status(fail_msg, f"color: {styles.COLOR_DANGER}; font-size: 12px;")

    def _set_status(self, text: str, style: str = "") -> None:
        self.status_lbl.setText(text)
        if style:
            self.status_lbl.setStyleSheet(style)

    def _rebind_install_btn(self, handler) -> None:
        try:
            self.install_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.install_btn.clicked.connect(handler)

    def _on_cancel(self):
        self.reject()
