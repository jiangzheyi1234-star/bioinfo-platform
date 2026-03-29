from __future__ import annotations

import json
import logging

from PyQt6.QtCore import Qt, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
)
import qtawesome as qta

from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from ui.install_log_parser import build_failure_guidance
from ui.widgets import styles
from ui.widgets.styles import (
    BUTTON_PRIMARY,
    BUTTON_SECONDARY,
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
    _INFO_SUBMITTING = "[INFO] 正在连接服务器，提交后台安装任务..."
    _EXPANDED_LOG_MAX_HEIGHT = 16777215

    def __init__(self, tool_info: dict, conda_executable: str = "", parent=None):
        super().__init__(parent)
        self.tool_info = tool_info
        self._tool_id = str(self.tool_info.get("id", "") or "").strip()
        self._installing = False
        self._conda_executable = str(conda_executable or "")
        self._user_expanded_log = False
        self._failure_hint_appended = False
        self._last_snapshot_updated_at = 0.0
        self._terminal_status = ""

        self.setWindowTitle("安装工具环境")
        self.setMinimumWidth(580)
        self.setMinimumHeight(360)
        self.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        self._build_ui()
        self._render_initial_state()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
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

        self._log_toggle_row = QFrame()
        self._log_toggle_row.setStyleSheet(
            f"QFrame {{ background: {styles.COLOR_BG_CARD}; border-top: 1px solid {styles.COLOR_BORDER}; "
            f"border-bottom: 1px solid {styles.COLOR_BORDER}; border-radius: 8px; }}"
        )
        toggle_layout = QHBoxLayout(self._log_toggle_row)
        toggle_layout.setContentsMargins(10, 4, 10, 4)
        toggle_layout.setSpacing(0)

        self.log_toggle_btn = QPushButton("")
        self.log_toggle_btn.setStyleSheet(
            BUTTON_SECONDARY
            + f" QPushButton {{ text-align: left; color: {styles.COLOR_PRIMARY}; padding: 4px 10px; }}"
        )
        self.log_toggle_btn.clicked.connect(self._toggle_log_drawer)
        toggle_layout.addWidget(self.log_toggle_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        toggle_layout.addStretch()
        layout.addWidget(self._log_toggle_row)

        self._log_drawer = QFrame()
        self._log_drawer.setStyleSheet("QFrame { border: none; background: transparent; }")
        drawer_layout = QVBoxLayout(self._log_drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self._log_content = QFrame()
        self._log_content.setStyleSheet("QFrame { border: none; background: transparent; }")
        self._log_content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        content_layout = QVBoxLayout(self._log_content)
        content_layout.setContentsMargins(0, 6, 0, 0)
        content_layout.setSpacing(6)

        output_title = QLabel("详细日志：")
        output_title.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        content_layout.addWidget(output_title)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            f"background: {styles.COLOR_BG_TERMINAL}; color: {styles.COLOR_BG_TERMINAL_TEXT};"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; border-radius: 4px; border: none;"
        )
        self.output_edit.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)
        self.output_edit.setMinimumHeight(180)
        content_layout.addWidget(self.output_edit)

        drawer_layout.addWidget(self._log_content)
        layout.addWidget(self._log_drawer)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.install_btn = QPushButton("开始安装")
        self.install_btn.setFixedWidth(100)
        self.install_btn.setStyleSheet(BUTTON_PRIMARY)
        self.install_btn.clicked.connect(self._on_start_install)

        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)
        self._set_log_visible(False, user_initiated=False)

    def _on_start_install(self):
        if self._installing:
            return
        install_cmd = self.tool_info.get("install_cmd", "")
        if not install_cmd:
            return
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self.install_btn.setEnabled(False)
            self.install_btn.setToolTip(f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。")
            return

        self._reset_attempt_state()
        self._set_log_text(self._INFO_SUBMITTING)
        self.apply_install_snapshot({"status": "SUBMITTING", "message": "正在提交安装任务……"})
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
        updated_at = self._parse_updated_at(snapshot)
        if updated_at is not None and updated_at < self._last_snapshot_updated_at:
            return
        if self._terminal_status in {"DONE", "FAILED"} and status in {"", "SUBMITTING", "RUNNING"}:
            return

        if updated_at is not None:
            self._last_snapshot_updated_at = updated_at

        if log_text:
            self._set_log_text(log_text)

        if status == "SUBMITTING":
            self._installing = True
            self._set_action_mode("running")
        elif status in {"RUNNING", ""}:
            self._installing = True
            self._set_action_mode("running")
        elif status == "DONE":
            self._installing = False
            self._terminal_status = "DONE"
            self._set_action_mode("success")
        elif status == "FAILED":
            self._installing = False
            self._terminal_status = "FAILED"
            self._set_action_mode("failed")
            self._append_failure_guidance(exit_code)
        else:
            raise RuntimeError(f"Unknown install snapshot status: {status!r}")

        self._sync_log_visibility(status)

    def _rebind_install_btn(self, handler) -> None:
        try:
            self.install_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.install_btn.clicked.connect(handler)

    def _render_initial_state(self) -> None:
        install_cmd = str(self.tool_info.get("install_cmd", "") or "").strip()
        self._set_action_mode("idle")
        self._set_log_visible(False, user_initiated=False)
        self.output_edit.clear()

        if not install_cmd:
            self.install_btn.setEnabled(False)
            self.install_btn.setToolTip("该工具未配置 install_cmd，无法自动安装。")
            self._set_log_text("该工具未配置 install_cmd，无法自动安装。")
            return
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self.install_btn.setEnabled(False)
            self.install_btn.setToolTip(f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。")
            self._set_log_text(f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。")
            return

        self.install_btn.setEnabled(True)
        self.install_btn.setToolTip("")
        self.output_edit.clear()

    def _reset_attempt_state(self) -> None:
        self._installing = True
        self._failure_hint_appended = False
        self._last_snapshot_updated_at = 0.0
        self._terminal_status = ""
        self._user_expanded_log = False
        self.output_edit.clear()
        self._set_log_visible(False, user_initiated=False)

    def _set_action_mode(self, mode: str) -> None:
        if mode == "idle":
            self.cancel_btn.show()
            self.cancel_btn.setText("取消")
            self.install_btn.show()
            self.install_btn.setText("开始安装")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self._on_start_install)
            return
        if mode == "running":
            self.cancel_btn.show()
            self.cancel_btn.setText("关闭")
            self.install_btn.hide()
            return
        if mode == "success":
            self.cancel_btn.hide()
            self.install_btn.show()
            self.install_btn.setText("完成")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self.accept)
            return
        if mode == "failed":
            self.cancel_btn.show()
            self.cancel_btn.setText("关闭")
            self.install_btn.show()
            self.install_btn.setText("重试")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self._on_start_install)
            return
        raise RuntimeError(f"Unknown action mode: {mode!r}")

    def _toggle_log_drawer(self) -> None:
        self._set_log_visible(self._log_content.isHidden(), user_initiated=True)

    def _set_log_visible(self, visible: bool, *, user_initiated: bool) -> None:
        self._log_drawer.setVisible(True)
        self._log_content.setVisible(visible)
        self._log_content.setMaximumHeight(self._EXPANDED_LOG_MAX_HEIGHT if visible else 0)
        self._log_content.setMinimumHeight(0)
        vertical_policy = QSizePolicy.Policy.Preferred if visible else QSizePolicy.Policy.Fixed
        self._log_content.setSizePolicy(QSizePolicy.Policy.Preferred, vertical_policy)
        if user_initiated:
            self._user_expanded_log = visible
        icon_name = "ph.caret-down" if visible else "ph.caret-right"
        self.log_toggle_btn.setIcon(qta.icon(icon_name, color=styles.COLOR_PRIMARY))
        self.log_toggle_btn.setText("隐藏详细日志" if visible else "查看详细日志")

    def _sync_log_visibility(self, status: str) -> None:
        normalized = str(status or "").strip().upper()
        if self._user_expanded_log:
            self._set_log_visible(True, user_initiated=False)
            return
        self._set_log_visible(normalized == "FAILED", user_initiated=False)

    def _set_log_text(self, text: str) -> None:
        self.output_edit.setPlainText(text)
        self._scroll_log_to_bottom()

    def _append_log_block(self, text: str) -> None:
        block = str(text or "").strip()
        if not block:
            return
        current = self.output_edit.toPlainText()
        merged = f"{current.rstrip()}\n\n{block}" if current.strip() else block
        self.output_edit.setPlainText(merged)
        self._scroll_log_to_bottom()

    def _append_failure_guidance(self, exit_code: str) -> None:
        if self._failure_hint_appended:
            return
        self._append_log_block(build_failure_guidance(exit_code))
        self._failure_hint_appended = True

    def _scroll_log_to_bottom(self) -> None:
        scroll_bar = self.output_edit.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    @staticmethod
    def _parse_updated_at(snapshot: dict) -> float | None:
        raw = snapshot.get("updated_at")
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _on_cancel(self):
        self.reject()
