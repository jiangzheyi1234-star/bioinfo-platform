from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer, QUrl, QSize
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
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

logger = logging.getLogger(__name__)
CONDA_EXE_CANDIDATES = [
    "/home/zyserver/anaconda3/bin/conda",
    "/home/zyserver/miniconda3/bin/conda",
    "~/anaconda3/bin/conda",
    "~/miniconda3/bin/conda",
    "/opt/anaconda3/bin/conda",
    "/opt/miniconda3/bin/conda",
    "conda",
]


def _resolve_conda_executable(client, timeout: int = 15) -> str:
    for exe in CONDA_EXE_CANDIDATES:
        try:
            _, stdout, _ = client.exec_command(f"{exe} --version", timeout=timeout)
            if stdout.channel.recv_exit_status() == 0:
                return exe
        except Exception:
            continue
    return "conda"


def _rewrite_conda_install_cmd(install_cmd: str, client) -> str:
    stripped = install_cmd.lstrip()
    if not (stripped == "conda" or stripped.startswith("conda ")):
        return install_cmd
    prefix = install_cmd[: len(install_cmd) - len(stripped)]
    remainder = stripped[5:]
    return f"{prefix}{_resolve_conda_executable(client)}{remainder}"

# 工具环境检测状态图标
_STATUS_PENDING = "..."
_STATUS_OK = "OK"
_STATUS_FAIL = "×"


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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

    def __init__(self, client, tools: list[dict]):
        """
        Args:
            client: paramiko SSHClient
            tools: [{"id": ..., "conda_env": ...}, ...]
        """
        super().__init__()
        self.client = client
        self.tools = tools

    @pyqtSlot()
    def run(self):
        try:
            import json as _json

            # ── 获取远程 conda 环境列表 ──────────────────────────────
            conda_envs: list[str] = []
            candidates = [f"{exe} env list --json" for exe in CONDA_EXE_CANDIDATES]

            for cmd in candidates:
                try:
                    _, stdout, stderr = self.client.exec_command(cmd, timeout=30)
                    # ★ 等待命令真正执行完毕
                    exit_code = stdout.channel.recv_exit_status()
                    output = stdout.read().decode("utf-8", errors="ignore").strip()
                    err_out = stderr.read().decode("utf-8", errors="ignore").strip()

                    logger.debug("conda cmd=%r exit=%d out_len=%d err=%s",
                                 cmd, exit_code, len(output), err_out[:80])

                    if exit_code != 0 or not output:
                        continue

                    json_start = output.find("{")
                    if json_start < 0:
                        continue

                    data = _json.loads(output[json_start:])
                    conda_envs = data.get("envs", [])
                    logger.info("conda env list 成功，共 %d 个环境（命令: %s）",
                                len(conda_envs), cmd)
                    break

                except _json.JSONDecodeError as e:
                    logger.warning("JSON 解析失败 cmd=%r: %s", cmd, e)
                    continue
                except Exception as e:
                    logger.debug("cmd=%r 失败: %s", cmd, e)
                    continue

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


# ── 环境安装 Worker ────────────────────────────────────────────────


class EnvInstallWorker(QObject):
    """SSH 执行 conda create 安装工具环境，实时流式输出。

    Signals:
        output_line(str): 每读到一行输出
        finished(bool): 安装完成，True=成功
        error(str): 异常
    """

    output_line = pyqtSignal(str)   # 每行输出
    finished = pyqtSignal(bool)     # True=成功
    error = pyqtSignal(str)

    def __init__(self, client, install_cmd: str):
        super().__init__()
        self.client = client
        self.install_cmd = install_cmd

    @pyqtSlot()
    def run(self):
        try:
            resolved_cmd = _rewrite_conda_install_cmd(self.install_cmd, self.client)
            logger.info("开始安装环境: %s", resolved_cmd)
            self.output_line.emit(f"$ {resolved_cmd}\n")
            _, stdout, stderr = self.client.exec_command(
                resolved_cmd, timeout=900  # 最长 15 分钟
            )

            # 流式读取 stdout（conda 主要输出在 stdout）
            for line in iter(stdout.readline, ""):
                if not line:
                    break
                self.output_line.emit(line)

            # 等待命令完全结束，取退出码
            exit_code = stdout.channel.recv_exit_status()

            # 读取 stderr（conda 有时把进度写到 stderr）
            err_text = stderr.read().decode("utf-8", errors="ignore").strip()
            if err_text:
                for line in err_text.splitlines():
                    self.output_line.emit(f"[stderr] {line}\n")

            success = exit_code == 0
            logger.info("安装完成 exit_code=%d success=%s", exit_code, success)
            self.finished.emit(success)

        except Exception as e:
            logger.exception("EnvInstallWorker 出错")
            self.error.emit(str(e))


# ── 环境安装对话框 ─────────────────────────────────────────────────


class EnvInstallDialog(QDialog):
    """安装工具 conda 环境的确认 + 进度对话框。

    用法::
        dlg = EnvInstallDialog(client, tool_info, parent=self)
        dlg.install_succeeded.connect(callback)
        dlg.exec()
    """

    install_succeeded = pyqtSignal(str)  # tool_id

    def __init__(self, client, tool_info: dict, parent=None):
        """
        Args:
            client: paramiko SSHClient
            tool_info: {"id", "name", "conda_env", "install_cmd", "databases"}
        """
        super().__init__(parent)
        self.client = client
        self.tool_info = tool_info
        self._installing = False
        self._install_thread: Optional[QThread] = None
        self._install_worker: Optional[EnvInstallWorker] = None

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

    def _on_start_install(self):
        if self._installing:
            return
        install_cmd = self.tool_info.get("install_cmd", "")
        if not install_cmd:
            return

        self._installing = True
        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_lbl.setText("安装中，请勿关闭窗口……（conda 安装可能需要 5-30 分钟）")
        self.status_lbl.setStyleSheet("color: #1565c0; font-size: 12px;")
        self.output_edit.clear()

        self._install_thread = QThread()
        self._install_worker = EnvInstallWorker(self.client, install_cmd)
        self._install_worker.moveToThread(self._install_thread)

        self._install_thread.started.connect(self._install_worker.run)
        self._install_worker.output_line.connect(self._append_output)
        self._install_worker.finished.connect(self._on_install_finished)
        self._install_worker.error.connect(self._on_install_error)
        self._install_worker.finished.connect(self._cleanup_install)

        self._install_thread.start()

    def _append_output(self, line: str):
        self.output_edit.insertPlainText(line)
        sb = self.output_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_install_finished(self, success: bool):
        self._installing = False
        self.cancel_btn.setEnabled(True)

        if success:
            self.output_edit.insertPlainText("\n✅ 安装成功！\n")
            self.status_lbl.setText("✅ 环境安装成功！")
            self.status_lbl.setStyleSheet(
                "color: #2e7d32; font-size: 13px; font-weight: bold;"
            )
            self.install_btn.setText("关闭")
            self.install_btn.setEnabled(True)
            # 断开旧信号，改为关闭对话框
            try:
                self.install_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self.install_btn.clicked.connect(self.accept)
            self.install_succeeded.emit(self.tool_info.get("id", ""))
        else:
            self.output_edit.insertPlainText("\n❌ 安装失败，请查看上方输出。\n")
            self.status_lbl.setText("❌ 安装失败，请检查网络或手动安装。")
            self.status_lbl.setStyleSheet("color: #c62828; font-size: 12px;")
            self.install_btn.setText("重试")
            self.install_btn.setEnabled(True)
            try:
                self.install_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self.install_btn.clicked.connect(self._on_start_install)

    def _on_install_error(self, msg: str):
        self._installing = False
        self.cancel_btn.setEnabled(True)
        self.install_btn.setText("重试")
        self.install_btn.setEnabled(True)
        self.status_lbl.setText(f"安装出错: {msg[:80]}")
        self.status_lbl.setStyleSheet(STATUS_ERROR)
        try:
            self.install_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.install_btn.clicked.connect(self._on_start_install)

    def _cleanup_install(self):
        for attr in ("_install_thread", "_install_worker"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            if attr == "_install_thread" and obj.isRunning():
                obj.quit()
                obj.wait(3000)
            obj.deleteLater()
            try:
                delattr(self, attr)
            except AttributeError:
                pass

    def _on_cancel(self):
        if self._installing:
            return  # 安装中不允许关闭
        self.reject()

    def closeEvent(self, event):
        if self._installing:
            event.ignore()  # 安装中禁止关闭
        else:
            self._cleanup_install()
            super().closeEvent(event)


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片（含工具环境检测+安装）。

    功能：
      - 配置远程 Linux 项目的根路径。
      - 批量检测 16 个插件工具的 conda 环境是否就绪（一键检测）。
      - 对 ❌ 工具提供"安装"按钮，点击后弹出 EnvInstallDialog 执行 conda create。
      - 安装成功后自动重新检测；需要数据库的工具给出提示。
      - 支持 plugin_registry 外部注入（PluginRegistry 动态读取工具列表）。
      - 使用 Web UI (QWebEngineView) 展示工具环境表格，解决对齐问题。

    get_values() 返回字段（保持向后兼容）:
      linux_project_path, max_concurrent, poll_interval,
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
        """接收外部传入的 SSH 客户端实例。SSH 连接成功后自动触发一次环境检测。"""
        self.active_client = client
        connected = client is not None

        if connected:
            self.status_label.setText("SSH 已就绪")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            # SSH 连接成功后延迟 1s 自动触发检测（等 UI 渲染完毕）
            QTimer.singleShot(1000, self._on_batch_check)
        else:
            self.status_label.setText("等待 SSH 连接")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)

    def get_values(self) -> dict:
        """供 SettingsPage 获取数据（向后兼容）。"""
        return {
            "linux_project_path": self.linux_project_path.text().strip(),
            "conda_env_path": "",       # 已移除，保留 key 兼容旧逻辑
            "conda_env_name": "",       # 已移除，保留 key 兼容旧逻辑
            "is_locked": self._is_locked,
            "max_concurrent": self.spin_concurrent.value(),
            "poll_interval": self.spin_poll.value(),
        }

    def set_values(
        self,
        project_path: str = "",
        conda_env: str = "",
        conda_env_name: str = "",
        max_concurrent: int = 3,
        poll_interval: int = 5,
    ) -> None:
        """供 SettingsPage 回填数据（签名向后兼容，conda_env 参数忽略）。"""
        self.linux_project_path.setText(project_path)
        self.spin_concurrent.setValue(max_concurrent)
        self.spin_poll.setValue(poll_interval)

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在 SSH 连接被占用时禁用编辑。"""
        if self._external_lock == locked:
            return
        self._external_lock = locked
        self._refresh_interaction_state()

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

        self.linux_project_path = QLineEdit()
        self.linux_project_path.setStyleSheet(INPUT_LINEEDIT)
        self.linux_project_path.setPlaceholderText("例如: /h2ometa/projects")

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 8)
        self.spin_concurrent.setValue(3)
        self.spin_concurrent.setSuffix(" 个任务")

        self.spin_poll = QSpinBox()
        self.spin_poll.setRange(1, 60)
        self.spin_poll.setValue(5)
        self.spin_poll.setSuffix(" 秒")

        form.addRow("项目根路径", self.linux_project_path)
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
                self._tools.append({
                    "id": tool_id,
                    "name": desc.get("name", tool_id),
                    "conda_env": desc.get("conda_env", ""),
                    "install_cmd": desc.get("install_cmd", ""),
                    "databases": desc.get("databases", []),
                })
        except Exception:
            logger.exception("读取插件列表失败")

        # 更新 Web UI
        if self._bridge:
            self._bridge.set_tools(self._tools)

    # ── 批量检测 ─────────────────────────────────────────

    def _on_batch_check(self) -> None:
        """一键检测所有工具环境（外部调用入口）。"""
        self._do_batch_check()

    def _on_batch_check_from_web(self) -> None:
        """从 Web UI 调用的检测入口。"""
        self._do_batch_check()

    def _do_batch_check(self) -> None:
        """实际执行批量检测。"""
        if not self.active_client or self._checking or self._external_lock:
            return

        if not self._tools:
            self.status_label.setText("未发现工具，请检查插件目录")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        self._checking = True
        self.status_label.setText("正在检测工具环境...")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        # 通知 Web UI 检测开始
        if self._bridge:
            self._bridge.emit_check_started()

        self._cleanup_check_resources()

        self._check_thread = QThread()
        self._check_worker = EnvBatchCheckWorker(self.active_client, self._tools)
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

        # 计算结果
        ok_count = sum(
            1 for tool in self._tools
            if tool.get("conda_env", "") == "" or tool.get("conda_env", "") in [
                path.rstrip("/").split("/")[-1] for path in conda_envs
            ]
        )
        total = len(self._tools)

        # 通知 Web UI 检测完成
        if self._bridge:
            self._bridge.emit_check_finished(ok_count, total)

        fail_count = total - ok_count

        if fail_count > 0:
            self.status_label.setText(
                f"检测完成：{ok_count}/{total} 个环境就绪，{fail_count} 个需要安装"
            )
        else:
            self.status_label.setText(f"检测完成：{ok_count}/{total} 个环境全部就绪 ✅")

        if ok_count == total:
            self.status_label.setStyleSheet(STATUS_SUCCESS)
        elif ok_count == 0:
            self.status_label.setStyleSheet(STATUS_ERROR)
        else:
            self.status_label.setStyleSheet(STATUS_NEUTRAL)

    def _on_batch_error(self, msg: str) -> None:
        """检测出错。"""
        self._checking = False
        self.status_label.setText(f"检测失败: {msg[:30]}")
        self.status_label.setStyleSheet(STATUS_ERROR)

    def _cleanup_check_resources(self) -> None:
        """清理检测线程资源。"""
        for attr in ("_check_thread", "_check_worker"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            if attr == "_check_thread" and obj.isRunning():
                obj.quit()
                obj.wait(5000)
            obj.deleteLater()
            try:
                delattr(self, attr)
            except AttributeError:
                pass

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
            self.status_label.setText("SSH 未连接，无法安装")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        dlg = EnvInstallDialog(self.active_client, tool, parent=self)
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

    # ── 保存/锁定 ─────────────────────────────────────────

    def _on_save_and_lock(self) -> None:
        """保存配置并切换锁定状态。"""
        if self._is_locked:
            # 解锁
            self._is_locked = False
            self.linux_project_path.setEnabled(True)
            self.spin_concurrent.setEnabled(True)
            self.spin_poll.setEnabled(True)
            self.lock_btn.setText("确认并保存")
            self.status_label.setText("配置已解锁，可修改")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            return

        project_path = self.linux_project_path.text().strip()
        if not project_path:
            self.status_label.setText("请填写项目根路径")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        self._is_locked = True
        self._lock_inputs()
        self.lock_btn.setText("修改配置")
        self.status_label.setText("配置已保存")
        self.status_label.setStyleSheet(STATUS_SUCCESS)
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

        self.linux_project_path.setEnabled(True)
        self.spin_concurrent.setEnabled(True)
        self.spin_poll.setEnabled(True)
        self.lock_btn.show()
        self.lock_btn.setEnabled(True)

        self.status_label.setText("请修改配置并保存")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)
        self._in_edit_mode = True

    def _lock_inputs(self):
        self.linux_project_path.setEnabled(False)
        self.spin_concurrent.setEnabled(False)
        self.spin_poll.setEnabled(False)
        self.lock_btn.setText("修改配置")
        self._in_edit_mode = False

    def _refresh_interaction_state(self) -> None:
        if self._external_lock:
            for w in [
                self.linux_project_path, self.modify_btn, self.lock_btn,
                self.spin_concurrent, self.spin_poll,
            ]:
                w.setEnabled(False)
            return

        if self._checking:
            return

        if self._in_edit_mode:
            self.linux_project_path.setEnabled(True)
            self.spin_concurrent.setEnabled(True)
            self.spin_poll.setEnabled(True)
            self.lock_btn.setEnabled(True)
            self.modify_btn.setEnabled(True)
        else:
            self.linux_project_path.setEnabled(False)
            self.spin_concurrent.setEnabled(False)
            self.spin_poll.setEnabled(False)
            self.modify_btn.setEnabled(True)
