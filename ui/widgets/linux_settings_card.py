from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer, QUrl
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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
from ui.widgets.linux_settings_components import ClickableHeader, EnvInstallDialog, ToolEnvBridge, cleanup_thread_pair

from core.environment import env_detector
from core.environment.env_detector import CondaStatus
from core.environment.env_installer import EnvInstaller, INSTALL_BASE as _INSTALL_BASE
from core.environment.env_batch_checker import ToolCheckResult, check_all_envs, get_existing_env_paths
from core.utils import sanitize_terminal_line

logger = logging.getLogger(__name__)


def _safe_emit(signal, *args) -> bool:
    try:
        signal.emit(*args)
        return True
    except RuntimeError:
        logger.debug("Skipped signal emit on deleted Qt object", exc_info=True)
        return False

# ── Conda 检测 Worker ─────────────────────────────────────────────


class CondaDetectWorker(QObject):
    """在 QThread 中运行 env_detector.detect()，避免阻塞主线程。"""

    finished = pyqtSignal(object)  # CondaDetectResult
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn

    @pyqtSlot()
    def run(self):
        try:
            result = env_detector.detect(self._ssh_run_fn)
            _safe_emit(self.finished, result)
        except Exception as e:
            logger.exception("CondaDetectWorker 出错")
            _safe_emit(self.error, str(e))


# ── Miniforge 安装 Worker ─────────────────────────────────────────


class MiniforgeInstallWorker(QObject):
    """在 QThread 中运行 env_detector.install_miniforge()。"""

    output_line = pyqtSignal(str)
    finished = pyqtSignal(object)  # CondaDetectResult
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn

    @pyqtSlot()
    def run(self):
        try:
            # 包装 ssh_run_fn 以输出日志
            original_fn = self._ssh_run_fn

            def logging_fn(cmd, timeout=15):
                _safe_emit(self.output_line, f"$ {cmd}\n")
                rc, stdout, stderr = original_fn(cmd, timeout)
                if stdout.strip():
                    clean = sanitize_terminal_line(stdout)
                    if clean:
                        _safe_emit(self.output_line, clean)
                if stderr.strip():
                    clean = sanitize_terminal_line(stderr)
                    if clean:
                        _safe_emit(self.output_line, f"[stderr] {clean}")
                return rc, stdout, stderr

            result = env_detector.install_miniforge(logging_fn)
            _safe_emit(self.finished, result)
        except Exception as e:
            logger.exception("MiniforgeInstallWorker 出错")
            _safe_emit(self.error, str(e))


# ── 批量环境检测 Worker ─────────────────────────────────────────────


class EnvBatchCheckWorker(QObject):
    """SSH 批量检测工具 conda 环境是否就绪。

    薄壳层：仅负责信号转发，后端逻辑委托给 env_batch_checker.check_all_envs()。

    Signals:
        tool_checked(tool_id, env_name, ok): 单个工具检测完成
        finished(conda_envs_list): 全部完成，返回已有环境路径列表
        error(message): 检测出错
    """

    tool_checked = pyqtSignal(str, str, bool)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client, tools: list[dict], conda_executable: str = ""):
        super().__init__()
        self.client = client
        self.tools = tools
        self._conda_executable = conda_executable or "conda"

    @pyqtSlot()
    def run(self):
        try:
            def ssh_run_fn(cmd, timeout=30):
                _, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
                exit_code = stdout.channel.recv_exit_status()
                output = stdout.read().decode("utf-8", errors="ignore")
                err_out = stderr.read().decode("utf-8", errors="ignore")
                return exit_code, output, err_out

            results, conda_envs = check_all_envs(
                ssh_run_fn=ssh_run_fn,
                tools=self.tools,
                conda_executable=self._conda_executable,
            )

            for r in results:
                if not _safe_emit(self.tool_checked, r.tool_id, r.env_name, r.ok):
                    return

            _safe_emit(self.finished, conda_envs)

        except Exception as e:
            logger.exception("EnvBatchCheckWorker 出错")
            _safe_emit(self.error, str(e))


# ── 安装状态检查 Worker（对话框初始化时使用）────────────────────────


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片（含工具环境检测+安装）。

    功能：
      - 批量检测 16 个插件工具的 conda 环境是否就绪（一键检测）。
      - 对 ❌ 工具提供"安装"按钮，点击后弹出 EnvInstallDialog 执行 conda create。
      - 安装成功后自动重新检测；需要数据库的工具给出提示。
      - 支持 plugin_registry 外部注入（PluginRegistry 动态读取工具列表）。
      - 使用 Web UI (QWebEngineView) 展示工具环境表格，解决对齐问题。

    get_values() 返回字段:
      conda_executable, auto_installed, conda_env_path(空), conda_env_name(空), is_locked
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
        # 正在安装的工具 ID 集合（用于检测时跳过）
        self._installing_tool_ids: set[str] = set()

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
            "is_locked": self._is_locked,
        }

    def set_values(
        self,
        conda_executable: str = "",
        auto_installed: bool = False,
    ) -> None:
        """供 SettingsPage 回填数据。"""
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
        pass  # 不再需要启用/禁用表单控件

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
            version_str = f" {result.version}" if result.version else ""
            self._set_status(f"conda{version_str} 就绪，正在检测工具环境...", STATUS_SUCCESS)

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

    def _on_conda_detect_error(self, msg: str) -> None:
        """conda 检测出错。"""
        self._checking = False
        self._set_status(f"conda 检测失败: {msg[:40]}", STATUS_ERROR)

    def _cleanup_conda_detect_resources(self) -> None:
        """清理 conda 检测线程资源。"""
        cleanup_thread_pair(self, "_conda_detect_thread", "_conda_detect_worker", wait_ms=5000)

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
        box.setDefaultButton(btn_install)
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

        info_lbl = QLabel("将安装 Miniforge3 到 ~/miniforge3，这可能需要几分钟。")
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

        # 立即通知 Web UI 检测开始（避免用户感觉点击后无响应）
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
        # 跳过正在安装的工具（保持"安装中"状态）
        if tool_id in self._installing_tool_ids:
            return
        if self._bridge:
            self._bridge.emit_tool_checked(tool_id, ok)

    def _on_batch_finished(self, conda_envs: list) -> None:
        """全部检测完成。"""
        self._checking = False

        env_paths_set = {path.rstrip("/") for path in conda_envs if path}
        env_names = {path.rstrip("/").split("/")[-1] for path in conda_envs}
        ok_count = 0
        for tool in self._tools:
            conda_env = tool.get("conda_env", "")
            if not conda_env:
                ok_count += 1
                continue
            # 优先使用环境名匹配（不受 ~ 展开影响）
            if conda_env in env_names:
                ok_count += 1
                continue
            # 路径匹配作为备选
            expected_path = env_detector.expected_env_path(self._conda_executable, conda_env)
            if expected_path and expected_path in env_paths_set:
                ok_count += 1
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
        cleanup_thread_pair(self, "_check_thread", "_check_worker", wait_ms=5000)

    # ── 安装 ─────────────────────────────────────────────

    def _on_install_click(self, tool: dict) -> None:
        """点击"安装"按钮，弹出安装对话框。"""
        self._queue_install_tool(tool)

    def _on_install_from_web(self, tool_id: str) -> None:
        """从 Web UI 调用安装工具。"""
        tool = next((t for t in self._tools if t["id"] == tool_id), None)
        if tool:
            # 通知 JS 安装开始，显示"安装中"状态
            if self._bridge:
                self._bridge.emit_install_started(tool_id)
            self._queue_install_tool(tool)

    def _queue_install_tool(self, tool: dict) -> None:
        """在当前事件结束后再打开安装对话框，避免 WebChannel 回调重入。"""
        tool_snapshot = dict(tool)
        QTimer.singleShot(0, lambda: self._do_install_tool(tool_snapshot))

    def _do_install_tool(self, tool: dict) -> None:
        """实际执行安装工具。"""
        if not self.active_client:
            self._set_status("SSH 未连接，无法安装", STATUS_ERROR)
            # 从安装中集合移除（如果之前被添加）
            self._installing_tool_ids.discard(tool.get("id", ""))
            if self._bridge:
                self._bridge.emit_install_finished(tool.get("id", ""), False)
            return

        try:
            dlg = EnvInstallDialog(self._make_ssh_run_fn(), tool, parent=self)
            dlg.install_succeeded.connect(self._on_install_succeeded)
            dlg.install_failed.connect(self._on_install_failed)
            dlg.exec()
        except Exception as exc:
            tool_name = tool.get("name") or tool.get("id") or "未知工具"
            tool_id = tool.get("id", "")
            logger.exception("打开安装对话框失败: tool=%s", tool_name)
            # 从安装中集合移除
            self._installing_tool_ids.discard(tool_id)
            self._set_status(f"打开安装窗口失败: {tool_name}", STATUS_ERROR)
            # 通知 JS 安装失败
            if self._bridge:
                self._bridge.emit_install_finished(tool_id, False)
            QMessageBox.critical(
                self,
                "安装窗口打开失败",
                f"工具【{tool_name}】的安装窗口打开失败。\n\n错误信息：{exc}",
            )

    def _on_install_succeeded(self, tool_id: str) -> None:
        """某工具安装成功后：提示数据库（如需要），然后重新检测。"""
        # 从安装中集合移除
        self._installing_tool_ids.discard(tool_id)
        # 通知 JS 安装完成
        if self._bridge:
            self._bridge.emit_install_finished(tool_id, True)

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

    def _on_install_failed(self, tool_id: str) -> None:
        """安装失败后通知 JS 更新状态。"""
        # 从安装中集合移除
        self._installing_tool_ids.discard(tool_id)
        if self._bridge:
            self._bridge.emit_install_finished(tool_id, False)

    def _recover_running_installs(self) -> None:
        """启动时扫描 ~/.h2ometa/env_installs/*/status.txt，恢复安装状态。

        - RUNNING → 检查环境是否实际已存在（防残留），存在则视为完成
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

        # 获取当前所有已存在的 conda 环境路径
        existing_env_paths = self._get_existing_env_paths()

        for item in installs:
            tool_id = item["tool_id"]
            status = item["status"]
            task_dir = item["task_dir"]

            if status == "RUNNING":
                # 检查该工具的环境是否实际已存在（防止状态文件残留）
                tool = next((t for t in self._tools if t["id"] == tool_id), None)
                if tool and self._is_tool_env_exists(tool, existing_env_paths):
                    logger.info("工具 %s 状态为 RUNNING 但环境已存在，视为安装完成", tool_id)
                    newly_done = True
                    # 清理残留的安装目录
                    try:
                        EnvInstaller.cleanup(self._make_ssh_run_fn(), task_dir)
                    except Exception:
                        pass
                else:
                    running_tools.append(tool_id)
                    self._installing_tool_ids.add(tool_id)
                    # 通知 Web UI 显示"安装中"状态
                    if self._bridge:
                        self._bridge.emit_install_started(tool_id)
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

    def _get_existing_env_paths(self) -> set[str]:
        """获取远端所有已存在的 conda 环境路径集合。"""
        if not self.active_client or not self._conda_executable:
            return set()

        try:
            import json as _json
            cmd = f"{self._conda_executable} env list --json"
            _, stdout, stderr = self.active_client.exec_command(cmd, timeout=30)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode("utf-8", errors="ignore").strip()

            if exit_code == 0 and output:
                json_start = output.find("{")
                if json_start >= 0:
                    data = _json.loads(output[json_start:])
                    return {p.rstrip("/") for p in data.get("envs", [])}
        except Exception as e:
            logger.debug("获取环境列表失败: %s", e)

        return set()

    def _is_tool_env_exists(self, tool: dict, existing_env_paths: set[str]) -> bool:
        """检查指定工具的环境是否已存在。"""
        conda_env = tool.get("conda_env", "")
        if not conda_env:
            return True  # 无环境要求，视为已存在

        # 使用环境名匹配（更可靠，不受 ~ 展开影响）
        env_names = {p.rstrip("/").split("/")[-1] for p in existing_env_paths}
        if conda_env in env_names:
            return True

        # 也可以尝试路径匹配（展开 ~）
        expected_path = env_detector.expected_env_path(
            self._conda_executable, conda_env
        )
        if expected_path and "~" in expected_path:
            try:
                _, stdout, _ = self._make_ssh_run_fn()(
                    f"eval echo {expected_path}", 10
                )
                expanded = stdout.strip()
                if expanded in existing_env_paths:
                    return True
            except Exception:
                pass

        return False

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

    def closeEvent(self, event) -> None:
        cleanup_thread_pair(self, "_conda_detect_thread", "_conda_detect_worker", wait_ms=1000)
        cleanup_thread_pair(self, "_check_thread", "_check_worker", wait_ms=1000)
        super().closeEvent(event)
