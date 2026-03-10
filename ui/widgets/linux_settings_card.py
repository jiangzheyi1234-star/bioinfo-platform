from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer, QUrl
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    BUTTON_PRIMARY,
    CARD_TITLE,
    COLOR_TEXT_HINT,
    COLOR_BG_PAGE,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
    BUTTON_LINK,
    SCROLL_BAR_ELEGANT,
)

from core import env_detector
from core.env_detector import CondaStatus
from core.env_installer import EnvInstaller, INSTALL_BASE as _INSTALL_BASE

logger = logging.getLogger(__name__)


def _cleanup_thread_pair(owner, thread_attr: str, worker_attr: str, wait_ms: int) -> None:
    """Stop/delete a (thread, worker) pair stored on an object."""
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


# ANSI 转义码正则 (ESC[ ... 终止字母) + OSC 序列
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _sanitize_terminal_line(text: str) -> str:
    """清理终端输出：去 ANSI 转义码，处理 \\r 覆写。

    conda 的 spinner / 进度条使用 ``\\r`` 在同一行反复覆写，
    多包下载区域使用 ``ESC[A`` 光标上移重绘。
    直接 insertPlainText 会导致乱码。这里只保留最后一段有意义的内容。
    """
    text = _ANSI_RE.sub("", text)
    # \r 覆写：保留最后一个 \r 后的内容
    if "\r" in text:
        parts = text.split("\r")
        last = ""
        for p in reversed(parts):
            if p.strip():
                last = p
                break
        if text.endswith("\n") and not last.endswith("\n"):
            last += "\n"
        text = last
    # 过滤纯空白行（大量空行来自光标上移清屏）
    if not text.strip():
        return ""
    return text


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ── Conda 检测 Worker ─────────────────────────────────────────────


class CondaDetectWorker(QObject):
    """在 QThread 中运行 env_detector.detect()，避免阻塞主线程。"""

    finished = pyqtSignal(object)  # CondaDetectResult
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, configured_path=""):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._configured_path = configured_path

    @pyqtSlot()
    def run(self):
        try:
            result = env_detector.detect(self._ssh_run_fn, self._configured_path)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("CondaDetectWorker 出错")
            self.error.emit(str(e))


# ── Miniforge 安装 Worker ─────────────────────────────────────────


class MiniforgeInstallWorker(QObject):
    """在 QThread 中运行 env_detector.install_miniforge()。"""

    output_line = pyqtSignal(str)
    finished = pyqtSignal(object)  # CondaDetectResult
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, install_dir="~/.h2ometa/conda"):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._install_dir = install_dir

    @pyqtSlot()
    def run(self):
        try:
            # 包装 ssh_run_fn 以输出日志
            original_fn = self._ssh_run_fn

            def logging_fn(cmd, timeout=15):
                self.output_line.emit(f"$ {cmd}\n")
                rc, stdout, stderr = original_fn(cmd, timeout)
                if stdout.strip():
                    clean = _sanitize_terminal_line(stdout)
                    if clean:
                        self.output_line.emit(clean)
                if stderr.strip():
                    clean = _sanitize_terminal_line(stderr)
                    if clean:
                        self.output_line.emit(f"[stderr] {clean}")
                return rc, stdout, stderr

            result = env_detector.install_miniforge(
                logging_fn, self._install_dir,
            )
            self.finished.emit(result)
        except Exception as e:
            logger.exception("MiniforgeInstallWorker 出错")
            self.error.emit(str(e))


# ── 工具环境 Bridge (Python ↔ JS) ───────────────────────────────────

class ToolEnvBridge(QObject):
    """Bridge between Python and JavaScript via QWebChannel for tool environment detection."""

    # Python → JS 信号
    toolListLoaded = pyqtSignal(str, arguments=["json"])  # JSON数组
    checkStarted = pyqtSignal(arguments=[])
    toolChecked = pyqtSignal(str, bool, arguments=["tool_id", "ok"])
    checkFinished = pyqtSignal(str, arguments=["result_json"])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tools: list[dict] = []
        self._parent_card = parent  # LinuxSettingsCard 引用

    def set_tools(self, tools: list[dict]) -> None:
        """设置工具列表。"""
        self._tools = tools
        self.toolListLoaded.emit(json.dumps(tools, ensure_ascii=False))

    def get_tools(self) -> list[dict]:
        """获取工具列表。"""
        return self._tools

    @pyqtSlot(result=str)
    def getTools(self) -> str:
        """JS 调用：获取工具列表 JSON。"""
        return json.dumps(self._tools, ensure_ascii=False)

    @pyqtSlot()
    def startCheck(self) -> None:
        """JS 调用：开始一键检测。"""
        if self._parent_card:
            self._parent_card._on_batch_check_from_web()

    @pyqtSlot(str)
    def installTool(self, tool_id: str) -> None:
        """JS 调用：安装工具。"""
        if self._parent_card:
            self._parent_card._on_install_from_web(tool_id)

    @pyqtSlot(int)
    def setHeight(self, height: int) -> None:
        """JS 调用：动态调整 WebView 高度。"""
        if self._parent_card and hasattr(self._parent_card, '_web_view'):
            web_view = self._parent_card._web_view
            if web_view:
                # 限制高度范围
                new_height = max(45, min(height + 10, 400))
                web_view.setFixedHeight(new_height)

    def emit_check_started(self) -> None:
        """Python 调用：通知 JS 检测开始。"""
        self.checkStarted.emit()

    def emit_tool_checked(self, tool_id: str, ok: bool) -> None:
        """Python 调用：通知 JS 单个工具检测完成。"""
        self.toolChecked.emit(tool_id, ok)

    def emit_check_finished(self, ready_count: int, total_count: int) -> None:
        """Python 调用：通知 JS 检测完成。"""
        result = {"ready_count": ready_count, "total_count": total_count}
        self.checkFinished.emit(json.dumps(result, ensure_ascii=False))


# ── 批量环境检测 Worker ─────────────────────────────────────────────


class EnvBatchCheckWorker(QObject):
    """SSH 批量检测工具 conda 环境是否就绪。

    检测策略：运行 `conda env list --json`，解析环境路径列表，
    逐个比对工具 descriptor 中的 `conda_env` 字段。

    Signals:
        tool_checked(tool_id, env_name, ok): 单个工具检测完成
        finished(conda_envs_list): 全部完成，返回已有环境路径列表
        error(message): 检测出错
    """

    tool_checked = pyqtSignal(str, str, bool)   # tool_id, env_name, ok
    finished = pyqtSignal(list)                  # conda_envs_list
    error = pyqtSignal(str)                      # error_message

    def __init__(self, client, tools: list[dict], conda_executable: str = ""):
        """
        Args:
            client: paramiko SSHClient
            tools: [{"id": ..., "conda_env": ...}, ...]
            conda_executable: 检测到的 conda 绝对路径
        """
        super().__init__()
        self.client = client
        self.tools = tools
        self._conda_executable = conda_executable or "conda"

    @pyqtSlot()
    def run(self):
        try:
            import json as _json

            # ── 获取远程 conda 环境列表 ──────────────────────────────
            conda_envs: list[str] = []
            cmd = f"{self._conda_executable} env list --json"

            try:
                _, stdout, stderr = self.client.exec_command(cmd, timeout=30)
                # ★ 等待命令真正执行完毕
                exit_code = stdout.channel.recv_exit_status()
                output = stdout.read().decode("utf-8", errors="ignore").strip()
                err_out = stderr.read().decode("utf-8", errors="ignore").strip()

                logger.debug("conda cmd=%r exit=%d out_len=%d err=%s",
                             cmd, exit_code, len(output), err_out[:80])

                if exit_code == 0 and output:
                    json_start = output.find("{")
                    if json_start >= 0:
                        data = _json.loads(output[json_start:])
                        conda_envs = data.get("envs", [])
                        logger.info("conda env list 成功，共 %d 个环境", len(conda_envs))

            except _json.JSONDecodeError as e:
                logger.warning("JSON 解析失败 cmd=%r: %s", cmd, e)
            except Exception as e:
                logger.debug("cmd=%r 失败: %s", cmd, e)

            if not conda_envs:
                logger.warning("所有候选命令均未取到 conda 环境列表")

            # ── 构建环境名集合（取路径末尾段）───────────────────────
            env_names_set: set[str] = set()
            for path in conda_envs:
                name = path.rstrip("/").split("/")[-1]
                env_names_set.add(name)

            logger.debug("已知环境名: %s", env_names_set)

            # ── 逐个比对工具的 conda_env 字段 ──────────────────────
            for tool in self.tools:
                tool_id = tool.get("id", "")
                conda_env = tool.get("conda_env", "")

                if not conda_env:
                    self.tool_checked.emit(tool_id, "(系统路径)", True)
                    continue

                ok = conda_env in env_names_set
                logger.debug("tool=%s conda_env=%s ok=%s", tool_id, conda_env, ok)
                self.tool_checked.emit(tool_id, conda_env, ok)

            self.finished.emit(conda_envs)

        except Exception as e:
            logger.exception("EnvBatchCheckWorker 出错")
            self.error.emit(str(e))


# ── 安装状态轮询 Worker ────────────────────────────────────────────


class EnvInstallPollWorker(QObject):
    """在 QThread 中轮询安装状态和日志（避免阻塞 UI）。

    由 QTimer 驱动，每次触发 poll() 时读取远端 status.txt + task.log。

    Signals:
        status_updated(dict): {"status": "RUNNING"/"DONE"/"FAILED", "exit_code": str}
        log_updated(str): 清理后的最新日志文本
        poll_error(str): 轮询出错
    """

    status_updated = pyqtSignal(dict)
    log_updated = pyqtSignal(str)
    poll_error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, task_dir: str):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._task_dir = task_dir

    @pyqtSlot()
    def poll(self):
        try:
            status = EnvInstaller.check_status(self._ssh_run_fn, self._task_dir)
            self.status_updated.emit(status)
            log_text = EnvInstaller.read_log(self._ssh_run_fn, self._task_dir)
            if log_text:
                self.log_updated.emit(log_text)
        except Exception as e:
            self.poll_error.emit(str(e))


# ── 环境安装对话框 ─────────────────────────────────────────────────


class EnvInstallDialog(QDialog):
    """安装工具 conda 环境的确认 + 进度对话框（screen 后台模式）。

    安装通过 screen -dmS 在服务器后台运行，SSH 断线或关闭窗口不影响安装进程。
    重新打开同一工具的安装对话框会自动接续显示进度。

    用法::
        dlg = EnvInstallDialog(ssh_run_fn, tool_info, parent=self)
        dlg.install_succeeded.connect(callback)
        dlg.exec()
    """

    install_succeeded = pyqtSignal(str)  # tool_id

    # 轮询间隔（毫秒）
    POLL_INTERVAL_MS = 3000

    def __init__(self, ssh_run_fn, tool_info: dict, parent=None):
        """
        Args:
            ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
            tool_info: {"id", "name", "conda_env", "install_cmd", "databases"}
        """
        super().__init__(parent)
        self._ssh_run_fn = ssh_run_fn
        self.tool_info = tool_info
        self._installing = False
        self._task_dir: str = ""
        self._job_id: str = ""

        # 轮询相关
        self._poll_timer: Optional[QTimer] = None
        self._poll_thread: Optional[QThread] = None
        self._poll_worker: Optional[EnvInstallPollWorker] = None

        # 从父级 LinuxSettingsCard 获取 conda_executable
        self._conda_executable = ""
        if parent and hasattr(parent, "_conda_executable"):
            self._conda_executable = parent._conda_executable

        self.setWindowTitle("安装工具环境")
        self.setMinimumWidth(580)
        self.setMinimumHeight(440)
        self.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        self._build_ui()

        # 检查是否已有正在运行的安装
        self._check_existing_install()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        tool_name = self.tool_info.get("name", self.tool_info.get("id", ""))
        conda_env = self.tool_info.get("conda_env", "")
        install_cmd = self.tool_info.get("install_cmd", "")
        databases = self.tool_info.get("databases", [])

        # ── 工具信息区 ──
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "background: #f0f4ff; border: 1px solid #c5d0e8; border-radius: 6px;"
        )
        info_layout = QFormLayout(info_frame)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setVerticalSpacing(8)

        def _info_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 13px; color: #333;")
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
                "color: #8a6300; background: #fff8e1;"
                "border: 1px solid #ffe082; border-radius: 4px;"
                "padding: 8px; font-size: 12px;"
            )
            info_layout.addRow("", db_hint)
        else:
            info_layout.addRow("数据库:", _info_lbl("无（不需要额外数据库）"))

        layout.addWidget(info_frame)

        # ── 安装输出区 ──
        output_title = QLabel("安装输出：")
        output_title.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(output_title)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4;"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; border-radius: 4px; border: none;"
        )
        self.output_edit.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)
        self.output_edit.setMinimumHeight(180)
        layout.addWidget(self.output_edit)

        # ── 状态行 ──
        self.status_lbl = QLabel('点击「开始安装」执行 conda create 命令。安装可能需要 5-30 分钟。')
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        # ── 按钮行 ──
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

        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)

    def _check_existing_install(self):
        """检查是否已有正在运行的安装，自动接续轮询。"""
        tool_id = self.tool_info.get("id", "")
        if not tool_id:
            return
        try:
            task_dir = f"{_INSTALL_BASE}/{tool_id}"
            status = EnvInstaller.check_status(self._ssh_run_fn, task_dir)
            if status["status"] == "RUNNING":
                self._task_dir = task_dir
                self._job_id = f"h2o_install_{tool_id}"
                self._installing = True
                self.install_btn.setEnabled(False)
                self.cancel_btn.setText("关闭")
                self._set_status(
                    "检测到正在后台安装，已接续显示进度...",
                    "color: #1565c0; font-size: 12px;",
                )
                self._start_polling()
        except Exception as e:
            logger.debug("检查已有安装失败: %s", e)

    def _on_start_install(self):
        if self._installing:
            return
        install_cmd = self.tool_info.get("install_cmd", "")
        if not install_cmd:
            return

        self._installing = True
        self.install_btn.setEnabled(False)
        self.cancel_btn.setText("关闭")
        self._set_status(
            "正在启动后台安装……（安装在服务器端运行，关闭窗口不影响）",
            "color: #1565c0; font-size: 12px;",
        )
        self.output_edit.clear()

        try:
            result = EnvInstaller.submit(
                self._ssh_run_fn,
                self.tool_info.get("id", ""),
                install_cmd,
                self._conda_executable,
            )
            self._task_dir = result["task_dir"]
            self._job_id = result["job_id"]
            self._set_status(
                "安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
                "color: #1565c0; font-size: 12px;",
            )
            self._start_polling()
        except Exception as e:
            logger.exception("启动后台安装失败")
            self._installing = False
            self.install_btn.setEnabled(True)
            self.install_btn.setText("重试")
            self._set_status(f"启动安装失败: {e}", STATUS_ERROR)

    def _start_polling(self):
        """启动 QTimer + QThread 轮询安装状态。"""
        self._stop_polling()

        self._poll_thread = QThread()
        self._poll_worker = EnvInstallPollWorker(self._ssh_run_fn, self._task_dir)
        self._poll_worker.moveToThread(self._poll_thread)

        self._poll_worker.status_updated.connect(self._on_status_updated)
        self._poll_worker.log_updated.connect(self._on_log_updated)
        self._poll_worker.poll_error.connect(self._on_poll_error)

        self._poll_thread.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_worker.poll)
        self._poll_timer.start(self.POLL_INTERVAL_MS)

        # 立即做一次轮询
        QTimer.singleShot(100, self._poll_worker.poll)

    def _stop_polling(self):
        """停止轮询。"""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        _cleanup_thread_pair(self, "_poll_thread", "_poll_worker", wait_ms=3000)

    def _on_status_updated(self, status: dict):
        st = status.get("status", "")
        if st == "DONE":
            self._stop_polling()
            self._installing = False
            self.output_edit.append("\n--- 安装成功 ---\n")
            self._set_status(
                "安装成功！",
                "color: #2e7d32; font-size: 13px; font-weight: bold;",
            )
            self.install_btn.setText("关闭")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self.accept)
            self.cancel_btn.setText("关闭")
            self.install_succeeded.emit(self.tool_info.get("id", ""))
            # 清理远端安装目录
            try:
                EnvInstaller.cleanup(self._ssh_run_fn, self._task_dir)
            except Exception:
                pass
        elif st == "FAILED":
            self._stop_polling()
            self._installing = False
            exit_code = status.get("exit_code", "?")
            self.output_edit.append(f"\n--- 安装失败 (exit_code={exit_code}) ---\n")
            self._set_status(
                "安装失败，请检查上方输出或网络后重试。",
                "color: #c62828; font-size: 12px;",
            )
            self.install_btn.setText("重试")
            self.install_btn.setEnabled(True)
            self._rebind_install_btn(self._on_start_install)
            self.cancel_btn.setText("关闭")

    def _on_log_updated(self, log_text: str):
        # 替换整个输出区内容（因为 tail 已返回最新的尾部日志）
        self.output_edit.setPlainText(log_text)
        sb = self.output_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_poll_error(self, msg: str):
        logger.debug("轮询出错（可能 SSH 暂时断开）: %s", msg)

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
        """关闭窗口 — 安装在服务器端继续，窗口随时可关。"""
        self._stop_polling()
        if self._installing:
            self.reject()
        else:
            self.reject()

    def closeEvent(self, event):
        self._stop_polling()
        super().closeEvent(event)


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片（含工具环境检测+安装）。

    功能：
      - 批量检测 16 个插件工具的 conda 环境是否就绪（一键检测）。
      - 对 ❌ 工具提供"安装"按钮，点击后弹出 EnvInstallDialog 执行 conda create。
      - 安装成功后自动重新检测；需要数据库的工具给出提示。
      - 支持 plugin_registry 外部注入（PluginRegistry 动态读取工具列表）。
      - 使用 Web UI (QWebEngineView) 展示工具环境表格，解决对齐问题。

    get_values() 返回字段（保持向后兼容）:
      max_concurrent, poll_interval,
      conda_env_path(空), conda_env_name(空), is_locked
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None, plugin_registry=None):
        super().__init__(parent)
        self.setObjectName("LinuxSettingsCard")

        self.active_client = None
        self._is_locked = False
        self._checking = False
        self._in_edit_mode = False
        self._external_lock = False

        self._plugin_registry = plugin_registry
        self._conda_executable: str = ""
        self._auto_installed: bool = False

        # 工具列表: [{"id", "name", "conda_env", "install_cmd", "databases"}]
        self._tools: list[dict] = []

        # Web UI 相关
        self._web_view = None
        self._bridge: Optional[ToolEnvBridge] = None
        self._channel = None

        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold)

        self._build_ui()
        self._lock_inputs()

    # ── 公开 API ─────────────────────────────────────────

    def set_plugin_registry(self, plugin_registry) -> None:
        """外部注入 PluginRegistry，用于刷新工具列表。"""
        self._plugin_registry = plugin_registry
        self._refresh_tool_list()

    def set_active_client(self, client) -> None:
        """接收外部传入的 SSH 客户端实例。SSH 连接成功后自动触发 conda 检测。"""
        self.active_client = client
        if client is not None:
            self._set_status("SSH 已就绪")
            # SSH 连接成功后延迟 1s 自动触发 conda 检测
            QTimer.singleShot(1000, self._ensure_conda_ready)
        else:
            self._set_status("等待 SSH 连接")

    def get_values(self) -> dict:
        """供 SettingsPage 获取数据。"""
        return {
            "conda_executable": self._conda_executable,
            "auto_installed": self._auto_installed,
            "conda_env_path": "",       # DEPRECATED, 保留 key 兼容旧逻辑
            "conda_env_name": "",       # DEPRECATED, 保留 key 兼容旧逻辑
            "is_locked": self._is_locked,
            "max_concurrent": self.spin_concurrent.value(),
            "poll_interval": self.spin_poll.value(),
        }

    def set_values(
        self,
        conda_env: str = "",
        conda_env_name: str = "",
        conda_executable: str = "",
        auto_installed: bool = False,
        max_concurrent: int = 3,
        poll_interval: int = 5,
    ) -> None:
        """供 SettingsPage 回填数据。"""
        self.spin_concurrent.setValue(max_concurrent)
        self.spin_poll.setValue(poll_interval)
        self._conda_executable = conda_executable
        self._auto_installed = auto_installed

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在 SSH 连接被占用时禁用编辑。"""
        if self._external_lock == locked:
            return
        self._external_lock = locked
        self._refresh_interaction_state()

    def _set_status(self, text: str, style: str = STATUS_NEUTRAL) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(style)

    def _set_form_enabled(self, enabled: bool) -> None:
        self.spin_concurrent.setEnabled(enabled)
        self.spin_poll.setEnabled(enabled)

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("LinuxSettingsCard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 头部（可点击折叠/展开）──
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.title_label = QLabel("Linux 端运行环境配置")
        self.title_label.setStyleSheet(CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setMinimumWidth(60)
        self.modify_btn.setStyleSheet(BUTTON_LINK)
        self.modify_btn.clicked.connect(self._enable_editing)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_btn)
        header_layout.addWidget(self.arrow_label)
        main_layout.addWidget(self.header_area)

        # ── 可折叠容器 ──
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(20, 0, 20, 20)
        c_layout.setSpacing(15)

        # ── 基础配置表单 ──
        form = QFormLayout()
        form.setVerticalSpacing(12)

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 8)
        self.spin_concurrent.setValue(3)
        self.spin_concurrent.setSuffix(" 个任务")

        self.spin_poll = QSpinBox()
        self.spin_poll.setRange(1, 60)
        self.spin_poll.setValue(5)
        self.spin_poll.setSuffix(" 秒")

        form.addRow("最大并发任务数", self.spin_concurrent)
        form.addRow("任务轮询间隔", self.spin_poll)
        c_layout.addLayout(form)

        # ── 工具环境检测区（Web UI）──
        self._build_tool_env_web_view(c_layout)

        # ── 状态行 + 保存按钮 ──
        row = QHBoxLayout()
        self.lock_btn = QPushButton("确认并保存")
        self.lock_btn.setMinimumWidth(110)
        self.lock_btn.setStyleSheet(BUTTON_PRIMARY)
        self.lock_btn.clicked.connect(self._on_save_and_lock)

        self.status_label = QLabel("等待 SSH 连接")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        row.addWidget(self.lock_btn)
        row.addWidget(self.status_label)
        row.addStretch()
        c_layout.addLayout(row)

        main_layout.addWidget(self.container)

    def _build_tool_env_web_view(self, parent_layout) -> None:
        """创建工具环境检测的 Web UI（QWebEngineView）。"""
        # 延迟导入 WebEngine（必须在 QApplication 创建后）
        from ui.qt_bootstrap import ensure_qt_webengine_ready
        ensure_qt_webengine_ready()

        try:
            from PyQt6.QtWebChannel import QWebChannel
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except ImportError as exc:
            logger.warning("QtWebEngine 不可用: %s", exc)
            fallback = QLabel("工具环境检测需要 QtWebEngine 支持")
            fallback.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            parent_layout.addWidget(fallback)
            return

        # 创建 Bridge
        self._bridge = ToolEnvBridge(parent=self)

        # 创建 WebView
        self._web_view = QWebEngineView()
        self._web_view.setMinimumHeight(45)  # 最小高度（折叠时只显示标题行）
        self._web_view.setMaximumHeight(400)  # 最大高度
        self._web_view.setFixedHeight(45)  # 初始高度设为折叠状态
        self._web_view.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._web_view.setStyleSheet("background: transparent; border: none;")

        # 设置 WebChannel
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # 加载 HTML
        assets_dir = Path(__file__).parent.parent / "pages" / "settings_page_assets"
        html_path = assets_dir / "tool_env_table.html"

        if html_path.exists():
            self._web_view.setUrl(QUrl.fromLocalFile(str(html_path)))
        else:
            logger.error("HTML 文件未找到: %s", html_path)

        parent_layout.addWidget(self._web_view)

    # ── 工具列表管理 ─────────────────────────────────────

    def _refresh_tool_list(self) -> None:
        """从 PluginRegistry 动态读取工具列表，更新到 Web UI。"""
        self._tools = []

        if not self._plugin_registry:
            logger.warning("插件注册表未就绪")
            if self._bridge:
                self._bridge.set_tools([])
            return

        try:
            for tool_id in self._plugin_registry.list_all_ids():
                desc = self._plugin_registry.get_descriptor(tool_id)
                self._tools.append(self._build_tool_info(tool_id, desc))
        except Exception:
            logger.exception("读取插件列表失败")

        # 更新 Web UI
        if self._bridge:
            self._bridge.set_tools(self._tools)

    @staticmethod
    def _build_tool_info(tool_id: str, desc: dict) -> dict:
        return {
            "id": tool_id,
            "name": desc.get("name", tool_id),
            "conda_env": desc.get("conda_env", ""),
            "install_cmd": desc.get("install_cmd", ""),
            "databases": desc.get("databases", []),
        }

    # ── conda 检测 ────────────────────────────────────────

    def _make_ssh_run_fn(self):
        """封装 paramiko client 为 env_detector 所需的 ssh_run_fn 回调。"""
        client = self.active_client

        def run(cmd, timeout=15):
            _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            return rc, out, err

        return run

    def _ensure_conda_ready(self) -> None:
        """SSH 连接后的第一层检测 — 检测 conda 是否可用。

        成功后缓存路径、保存配置、更新 ServiceLocator，然后继续 batch check。
        未找到时弹窗提示安装 Miniforge。
        """
        if not self.active_client or self._checking or self._external_lock:
            return

        self._checking = True
        self._set_status("正在检测 conda 环境...")

        self._cleanup_conda_detect_resources()

        self._conda_detect_thread = QThread()
        self._conda_detect_worker = CondaDetectWorker(
            ssh_run_fn=self._make_ssh_run_fn(),
            configured_path=self._conda_executable,
        )
        self._conda_detect_worker.moveToThread(self._conda_detect_thread)

        self._conda_detect_thread.started.connect(self._conda_detect_worker.run)
        self._conda_detect_worker.finished.connect(self._on_conda_detected)
        self._conda_detect_worker.error.connect(self._on_conda_detect_error)
        self._conda_detect_worker.finished.connect(self._cleanup_conda_detect_resources)

        self._conda_detect_thread.start()

    def _on_conda_detected(self, result) -> None:
        """conda 检测完成回调。"""
        self._checking = False

        if result.status == CondaStatus.OK:
            self._conda_executable = result.executable
            self._set_status(f"conda {result.version} 就绪，正在检测工具环境...", STATUS_SUCCESS)

            # 更新 ServiceLocator
            window = self.window()
            locator = getattr(window, "service_locator", None)
            if locator is not None and hasattr(locator, "conda_executable"):
                locator.conda_executable = self._conda_executable

            # 保存配置
            self.request_save.emit()

            # 继续批量检测工具环境
            QTimer.singleShot(200, self._on_batch_check)

            # 检查是否有后台安装正在运行
            QTimer.singleShot(500, self._recover_running_installs)

        elif result.status == CondaStatus.NOT_FOUND:
            self._set_status("未检测到 conda", STATUS_ERROR)
            self._prompt_miniforge_install()

        elif result.status == CondaStatus.VERSION_PARSE_FAILED:
            self._set_status("检测到 conda 但版本不可识别，请手动指定路径", STATUS_ERROR)

    def _on_conda_detect_error(self, msg: str) -> None:
        """conda 检测出错。"""
        self._checking = False
        self._set_status(f"conda 检测失败: {msg[:40]}", STATUS_ERROR)

    def _cleanup_conda_detect_resources(self) -> None:
        """清理 conda 检测线程资源。"""
        _cleanup_thread_pair(self, "_conda_detect_thread", "_conda_detect_worker", wait_ms=5000)

    def _prompt_miniforge_install(self) -> None:
        """弹窗提示：未检测到 conda，提供手动指定路径 / 自动安装 Miniforge 两个选项。"""
        from PyQt6.QtWidgets import QMessageBox, QInputDialog

        box = QMessageBox(self)
        box.setWindowTitle("未检测到 conda")
        box.setText(
            "远端服务器未自动检测到 conda 环境管理器。\n\n"
            "如果你已安装 conda / anaconda / miniconda，\n"
            "请点击「手动指定」输入 conda 可执行文件的绝对路径。\n\n"
            "如果没有 conda，可点击「安装 Miniforge」自动安装。"
        )
        btn_manual = box.addButton("手动指定路径", QMessageBox.ButtonRole.ActionRole)
        btn_install = box.addButton("安装 Miniforge", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_manual)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_manual:
            path, ok = QInputDialog.getText(
                self,
                "指定 conda 路径",
                "请输入远端 conda 可执行文件的绝对路径：\n"
                "（例如 /home/zyserver/anaconda3/bin/conda）",
            )
            if ok and path.strip():
                self._conda_executable = path.strip()
                self.request_save.emit()
                # 用指定路径重新检测
                QTimer.singleShot(200, self._ensure_conda_ready)
        elif clicked == btn_install:
            self._start_miniforge_install()

    def _start_miniforge_install(self) -> None:
        """启动 Miniforge 安装。

        Miniforge 是一次性短操作（< 5 分钟），保持 MiniforgeInstallWorker 阻塞方式。
        使用简化的 QDialog 而不是 EnvInstallDialog。
        """
        if not self.active_client:
            return

        from PyQt6.QtWidgets import QMessageBox

        dlg = QDialog(self)
        dlg.setWindowTitle("安装 Miniforge3")
        dlg.setMinimumWidth(580)
        dlg.setMinimumHeight(440)
        dlg.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info_lbl = QLabel("将安装 Miniforge3 到 ~/.h2ometa/conda，这可能需要几分钟。")
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(info_lbl)

        output_edit = QTextEdit()
        output_edit.setReadOnly(True)
        output_edit.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4;"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; border-radius: 4px; border: none;"
        )
        output_edit.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)
        output_edit.setMinimumHeight(180)
        layout.addWidget(output_edit)

        status_lbl = QLabel("点击「开始安装」启动安装。")
        status_lbl.setWordWrap(True)
        status_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(status_lbl)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(dlg.reject)
        install_btn = QPushButton("开始安装")
        install_btn.setFixedWidth(100)
        install_btn.setStyleSheet(BUTTON_PRIMARY)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(install_btn)
        layout.addLayout(btn_row)

        def _append_output(line):
            output_edit.insertPlainText(line)
            sb = output_edit.verticalScrollBar()
            sb.setValue(sb.maximum())

        def _do_miniforge():
            install_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            status_lbl.setText("正在安装 Miniforge3...")
            status_lbl.setStyleSheet("color: #1565c0; font-size: 12px;")
            output_edit.clear()

            thread = QThread()
            worker = MiniforgeInstallWorker(self._make_ssh_run_fn())
            worker.moveToThread(thread)

            thread.started.connect(worker.run)
            worker.output_line.connect(_append_output)

            def on_finished(result):
                thread.quit()
                thread.wait(3000)
                cancel_btn.setEnabled(True)
                if result.status == CondaStatus.OK:
                    self._conda_executable = result.executable
                    self._auto_installed = True
                    status_lbl.setText("Miniforge3 安装成功！")
                    status_lbl.setStyleSheet("color: #2e7d32; font-size: 13px; font-weight: bold;")
                    install_btn.setText("关闭")
                    install_btn.setEnabled(True)
                    try:
                        install_btn.clicked.disconnect()
                    except RuntimeError:
                        pass
                    install_btn.clicked.connect(dlg.accept)
                    QTimer.singleShot(500, self._ensure_conda_ready)
                else:
                    output_edit.insertPlainText(f"\n{result.message}\n")
                    status_lbl.setText("安装失败，请检查网络或手动安装。")
                    status_lbl.setStyleSheet("color: #c62828; font-size: 12px;")
                    install_btn.setText("重试")
                    install_btn.setEnabled(True)

            def on_error(msg):
                thread.quit()
                thread.wait(3000)
                cancel_btn.setEnabled(True)
                install_btn.setEnabled(True)
                install_btn.setText("重试")
                status_lbl.setText(f"安装出错: {msg[:80]}")
                status_lbl.setStyleSheet(STATUS_ERROR)

            worker.finished.connect(on_finished)
            worker.error.connect(on_error)

            dlg._mf_thread = thread
            dlg._mf_worker = worker
            thread.start()

        install_btn.clicked.connect(_do_miniforge)
        dlg.exec()

    # ── 批量检测 ─────────────────────────────────────────

    def _on_batch_check(self) -> None:
        """一键检测所有工具环境（外部调用入口）。"""
        self._do_batch_check()

    def _on_batch_check_from_web(self) -> None:
        """从 Web UI 调用的检测入口 — 如果 conda 已知则直接检测，否则先检测 conda。"""
        if self._conda_executable:
            self._do_batch_check()
        else:
            self._ensure_conda_ready()

    def _do_batch_check(self) -> None:
        """实际执行批量检测。"""
        if not self.active_client or self._checking or self._external_lock:
            return

        if not self._tools:
            self._set_status("未发现工具，请检查插件目录", STATUS_ERROR)
            return

        self._checking = True
        self._set_status("正在检测工具环境...")

        # 通知 Web UI 检测开始
        if self._bridge:
            self._bridge.emit_check_started()

        self._cleanup_check_resources()

        self._check_thread = QThread()
        self._check_worker = EnvBatchCheckWorker(
            self.active_client, self._tools, self._conda_executable,
        )
        self._check_worker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.tool_checked.connect(self._on_tool_checked)
        self._check_worker.finished.connect(self._on_batch_finished)
        self._check_worker.error.connect(self._on_batch_error)
        self._check_worker.finished.connect(self._cleanup_check_resources)

        self._check_thread.start()

    def _on_tool_checked(self, tool_id: str, env_name: str, ok: bool) -> None:
        """单个工具检测完成，通知 Web UI 更新状态。"""
        if self._bridge:
            self._bridge.emit_tool_checked(tool_id, ok)

    def _on_batch_finished(self, conda_envs: list) -> None:
        """全部检测完成。"""
        self._checking = False

        env_names = {path.rstrip("/").split("/")[-1] for path in conda_envs}
        ok_count = sum(
            1
            for tool in self._tools
            if not tool.get("conda_env", "") or tool.get("conda_env", "") in env_names
        )
        total = len(self._tools)

        # 通知 Web UI 检测完成
        if self._bridge:
            self._bridge.emit_check_finished(ok_count, total)

        fail_count = total - ok_count

        if fail_count > 0:
            self._set_status(f"检测完成：{ok_count}/{total} 个环境就绪，{fail_count} 个需要安装")
        else:
            self._set_status(f"检测完成：{ok_count}/{total} 个环境全部就绪 ✅")

        if ok_count == total:
            self.status_label.setStyleSheet(STATUS_SUCCESS)
        elif ok_count == 0:
            self.status_label.setStyleSheet(STATUS_ERROR)

    def _on_batch_error(self, msg: str) -> None:
        """检测出错。"""
        self._checking = False
        self._set_status(f"检测失败: {msg[:30]}", STATUS_ERROR)

    def _cleanup_check_resources(self) -> None:
        """清理检测线程资源。"""
        _cleanup_thread_pair(self, "_check_thread", "_check_worker", wait_ms=5000)

    # ── 安装 ─────────────────────────────────────────────

    def _on_install_click(self, tool: dict) -> None:
        """点击"安装"按钮，弹出安装对话框。"""
        self._do_install_tool(tool)

    def _on_install_from_web(self, tool_id: str) -> None:
        """从 Web UI 调用安装工具。"""
        tool = next((t for t in self._tools if t["id"] == tool_id), None)
        if tool:
            self._do_install_tool(tool)

    def _do_install_tool(self, tool: dict) -> None:
        """实际执行安装工具。"""
        if not self.active_client:
            self._set_status("SSH 未连接，无法安装", STATUS_ERROR)
            return

        dlg = EnvInstallDialog(self._make_ssh_run_fn(), tool, parent=self)
        dlg.install_succeeded.connect(self._on_install_succeeded)
        dlg.exec()

    def _on_install_succeeded(self, tool_id: str) -> None:
        """某工具安装成功后：提示数据库（如需要），然后重新检测。"""
        tool = next((t for t in self._tools if t["id"] == tool_id), None)

        if tool and tool.get("databases"):
            from PyQt6.QtWidgets import QMessageBox
            db_ids = "\n".join(f"  • {d.get('id', '')}" for d in tool["databases"])
            QMessageBox.information(
                self,
                "请配置数据库路径",
                f"工具【{tool.get('name', tool_id)}】环境安装成功！\n\n"
                f"该工具运行需要以下数据库：\n{db_ids}\n\n"
                f"请在下方「数据库路径配置」卡片中填写对应路径。",
            )

        # 重新检测所有工具
        QTimer.singleShot(300, self._on_batch_check)

    def _recover_running_installs(self) -> None:
        """启动时扫描 ~/.h2ometa/env_installs/*/status.txt，恢复安装状态。

        - RUNNING → 状态栏提示"XX 正在后台安装"
        - DONE（新完成的）→ 触发重新检测 + 清理
        """
        if not self.active_client:
            return
        try:
            installs = EnvInstaller.scan_running(self._make_ssh_run_fn())
        except Exception as e:
            logger.debug("扫描后台安装失败: %s", e)
            return

        running_tools = []
        newly_done = False
        for item in installs:
            tool_id = item["tool_id"]
            status = item["status"]
            task_dir = item["task_dir"]
            if status == "RUNNING":
                running_tools.append(tool_id)
            elif status == "DONE":
                newly_done = True
                # 清理已完成的安装目录
                try:
                    EnvInstaller.cleanup(self._make_ssh_run_fn(), task_dir)
                except Exception:
                    pass
            elif status == "FAILED":
                # 保留失败目录供诊断，但不提示
                pass

        if running_tools:
            names = ", ".join(running_tools)
            self._set_status(f"后台安装进行中: {names}")

        if newly_done:
            QTimer.singleShot(500, self._on_batch_check)

    # ── 保存/锁定 ─────────────────────────────────────────

    def _on_save_and_lock(self) -> None:
        """保存配置并切换锁定状态。"""
        if self._is_locked:
            # 解锁
            self._is_locked = False
            self._set_form_enabled(True)
            self.lock_btn.setText("确认并保存")
            self._set_status("配置已解锁，可修改")
            return

        self._is_locked = True
        self._lock_inputs()
        self.lock_btn.setText("修改配置")
        self._set_status("配置已保存", STATUS_SUCCESS)
        self.request_save.emit()

        self._auto_fold_timer.start(1500)

    # ── 折叠/展开 ─────────────────────────────────────────

    def _toggle_container(self):
        if self._checking or self._external_lock:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

    def _auto_fold(self):
        if not self._in_edit_mode and self.container.isVisible():
            self.container.hide()
            self.arrow_label.setText("▼")

    def _enable_editing(self):
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")

        self._set_form_enabled(True)
        self.lock_btn.show()
        self.lock_btn.setEnabled(True)

        self._set_status("请修改配置并保存")
        self._in_edit_mode = True

    def _lock_inputs(self):
        self._set_form_enabled(False)
        self.lock_btn.setText("修改配置")
        self._in_edit_mode = False

    def _refresh_interaction_state(self) -> None:
        if self._external_lock:
            for w in [
                self.modify_btn, self.lock_btn,
                self.spin_concurrent, self.spin_poll,
            ]:
                w.setEnabled(False)
            return

        if self._checking:
            return

        if self._in_edit_mode:
            self._set_form_enabled(True)
            self.lock_btn.setEnabled(True)
            self.modify_btn.setEnabled(True)
        else:
            self._set_form_enabled(False)
            self.modify_btn.setEnabled(True)
