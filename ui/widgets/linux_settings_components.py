from __future__ import annotations

import json
import logging

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.utils import get_app_root
from ui.install_log_parser import analyze_install_log, build_failure_guidance
from ui.qt_bootstrap import ensure_qt_webengine_ready
from ui.widgets import styles
from ui.widgets.report_view import create_report_web_view
from ui.widgets.styles import (
    BUTTON_PRIMARY,
    COLOR_BG_PAGE,
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


class InstallDialogBridge(QObject):
    """Bridge between Python install dialog shell and its Web UI."""

    snapshotUpdated = pyqtSignal(str, arguments=["json"])
    toolInfoReady = pyqtSignal(str, arguments=["json"])

    def __init__(self, dialog: "EnvInstallDialog"):
        super().__init__(dialog)
        self._dialog = dialog

    @pyqtSlot()
    def requestToolInfo(self) -> None:
        self.toolInfoReady.emit(self._dialog._tool_info_json)
        if self._dialog._latest_snapshot_json:
            self.snapshotUpdated.emit(self._dialog._latest_snapshot_json)

    @pyqtSlot()
    def requestInstall(self) -> None:
        self._dialog._on_start_install()

    @pyqtSlot()
    def requestClose(self) -> None:
        self._dialog._close_from_bridge()


class EnvInstallDialog(QDialog):
    """Tool conda-environment installation dialog rendered with Web UI."""

    install_requested = pyqtSignal(str)
    _INFO_SUBMITTING = "[INFO] 正在连接服务器，提交后台安装任务..."

    def __init__(self, tool_info: dict, conda_executable: str = "", parent=None):
        super().__init__(parent)
        self.tool_info = dict(tool_info or {})
        self._tool_id = str(self.tool_info.get("id", "") or "").strip()
        self._tool_info_json = json.dumps(self.tool_info, ensure_ascii=False)
        self._installing = False
        self._conda_executable = str(conda_executable or "")
        self._failure_hint_appended = False
        self._last_snapshot_updated_at = 0.0
        self._terminal_status = ""
        self._current_log_text = ""
        self._latest_snapshot_payload: dict[str, object] = {}
        self._latest_snapshot_json = ""

        self.setWindowTitle("安装工具环境")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(620)
        self.setMinimumHeight(420)
        self.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        self._build_ui()
        self._render_initial_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        ensure_qt_webengine_ready()
        from PyQt6.QtWebChannel import QWebChannel

        self._install_bridge = InstallDialogBridge(self)
        self._web_view = create_report_web_view(
            parent=self,
            background="#FFFFFF",
            disable_context_menu=True,
            allow_remote_resources=False,
        )
        self._web_view.setStyleSheet("background: #FFFFFF; border: none;")

        self._channel = QWebChannel(self)
        self._channel.registerObject("installBridge", self._install_bridge)
        self._web_view.page().setWebChannel(self._channel)

        html_path = get_app_root() / "ui" / "pages" / "settings_page_assets" / "install_dialog.html"
        if not html_path.exists():
            raise RuntimeError(f"安装弹窗 HTML 文件未找到: {html_path}")
        self._web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        layout.addWidget(self._web_view)

    def _on_start_install(self) -> None:
        if self._installing:
            return
        install_cmd = str(self.tool_info.get("install_cmd", "") or "").strip()
        if not install_cmd:
            self._emit_view_snapshot(
                status="IDLE",
                message="该工具未配置 install_cmd，无法自动安装。",
                primary_enabled=False,
            )
            return
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self._emit_view_snapshot(
                status="IDLE",
                message=f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。",
                primary_enabled=False,
            )
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
            message = message or "正在提交安装任务……"
        elif status in {"RUNNING", ""}:
            self._installing = True
            status = "RUNNING"
            message = message or "安装中……"
        elif status == "DONE":
            self._installing = False
            self._terminal_status = "DONE"
            message = message or "安装成功！"
        elif status == "FAILED":
            self._installing = False
            self._terminal_status = "FAILED"
            self._append_failure_guidance(exit_code)
            message = message or "安装失败，请检查详细日志后重试。"
            if exit_code and "exit_code" not in message:
                message = f"{message} (exit_code={exit_code})"
        else:
            raise RuntimeError(f"Unknown install snapshot status: {status!r}")

        self._emit_view_snapshot(
            status=status,
            message=message,
            exit_code=exit_code,
            updated_at=updated_at,
        )

    def _render_initial_state(self) -> None:
        install_cmd = str(self.tool_info.get("install_cmd", "") or "").strip()
        if not install_cmd:
            self._set_log_text("该工具未配置 install_cmd，无法自动安装。")
            self._emit_view_snapshot(
                status="IDLE",
                message="该工具未配置 install_cmd，无法自动安装。",
                primary_enabled=False,
            )
            return
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self._set_log_text(f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。")
            self._emit_view_snapshot(
                status="IDLE",
                message=f"运行环境未就绪，请先完成初始化（{H2O_CONDA_EXE}）。",
                primary_enabled=False,
            )
            return
        self._set_log_text("")
        self._emit_view_snapshot(status="IDLE", message="", primary_enabled=True)

    def _reset_attempt_state(self) -> None:
        self._installing = True
        self._failure_hint_appended = False
        self._last_snapshot_updated_at = 0.0
        self._terminal_status = ""
        self._set_log_text("")

    def _emit_view_snapshot(
        self,
        *,
        status: str,
        message: str,
        exit_code: str = "",
        updated_at: float | None = None,
        primary_enabled: bool | None = None,
    ) -> None:
        normalized_status = str(status or "").strip().upper() or "IDLE"
        analysis = analyze_install_log(
            normalized_status if normalized_status != "IDLE" else "RUNNING",
            message=message,
            log_text=self._current_log_text,
            exit_code=exit_code,
        )
        payload: dict[str, object] = {
            "status": normalized_status,
            "message": message,
            "log_text": self._current_log_text,
            "exit_code": exit_code,
            "updated_at": updated_at if updated_at is not None else self._last_snapshot_updated_at,
            "phase_text": self._build_phase_text(normalized_status, analysis, message),
            "progress": analysis.progress_value or 0,
            "progress_text": analysis.progress_text,
            "speed": analysis.speed_text,
            "log_auto_expand": normalized_status == "FAILED",
        }
        payload.update(self._button_payload(normalized_status, primary_enabled=primary_enabled))
        self._latest_snapshot_payload = payload
        self._latest_snapshot_json = json.dumps(payload, ensure_ascii=False)
        self._install_bridge.snapshotUpdated.emit(self._latest_snapshot_json)

    def _button_payload(self, status: str, *, primary_enabled: bool | None = None) -> dict[str, object]:
        normalized_status = str(status or "").strip().upper()
        primary_action = "install"
        primary_label = "开始安装"
        secondary_label = "取消"
        secondary_visible = True
        enabled = True if primary_enabled is None else bool(primary_enabled)

        if normalized_status in {"SUBMITTING", "RUNNING"}:
            primary_label = "开始安装"
            primary_action = "install"
            secondary_label = "关闭"
            enabled = False
        elif normalized_status == "DONE":
            primary_label = "关闭"
            primary_action = "close"
            secondary_visible = False
            enabled = True
        elif normalized_status == "FAILED":
            primary_label = "重试"
            primary_action = "install"
            secondary_label = "关闭"
            enabled = True

        return {
            "primary_label": primary_label,
            "primary_action": primary_action,
            "primary_enabled": enabled,
            "secondary_label": secondary_label,
            "secondary_visible": secondary_visible,
        }

    def _build_phase_text(self, status: str, analysis, message: str) -> str:
        normalized_status = str(status or "").strip().upper()
        if normalized_status == "IDLE":
            if message:
                return message
            return "点击「开始安装」执行安装"
        if normalized_status == "DONE":
            return "安装成功"
        if normalized_status == "FAILED":
            return "安装失败"
        if normalized_status == "SUBMITTING":
            return "正在连接服务器并提交任务"
        if message:
            return analysis.phase_text
        return analysis.phase_text

    def _set_log_text(self, text: str) -> None:
        self._current_log_text = str(text or "")

    def _append_log_block(self, text: str) -> None:
        block = str(text or "").strip()
        if not block:
            return
        current = self._current_log_text.rstrip()
        self._current_log_text = f"{current}\n\n{block}" if current else block

    def _append_failure_guidance(self, exit_code: str) -> None:
        if self._failure_hint_appended:
            return
        self._append_log_block(build_failure_guidance(exit_code))
        self._failure_hint_appended = True

    def _close_from_bridge(self) -> None:
        if self._terminal_status == "DONE":
            self.accept()
            return
        self.reject()

    @staticmethod
    def _parse_updated_at(snapshot: dict) -> float | None:
        raw = snapshot.get("updated_at")
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
