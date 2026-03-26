from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer, QUrl, QElapsedTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    BUTTON_PRIMARY,
    CARD_TITLE,
    COLOR_TEXT_HINT,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
    BUTTON_LINK,
)
from ui.widgets.linux_settings_components import ClickableHeader, EnvInstallDialog, ToolEnvBridge, cleanup_thread_pair
from ui.widgets.report_view import create_report_web_view
from ui.widgets.toast import Toast

from core.environment import env_detector
from core.environment import miniforge_bootstrap
from core.environment.env_detector import CondaStatus
from core.environment.env_installer import EnvInstaller, INSTALL_BASE as _INSTALL_BASE
from core.environment.env_batch_checker import ToolCheckResult, check_all_envs, get_existing_env_paths
from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable

logger = logging.getLogger(__name__)
MINIFORGE_HEARTBEAT_STALE_SECONDS = 180
TOOL_INSTALL_POLL_INTERVAL_MS = 3000
_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMG]?B/s)", re.IGNORECASE)
_PROGRESS_RE = re.compile(r"\b([0-9]{1,3})%\b")


def _format_rate(bps: float) -> str:
    if bps >= 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024 * 1024):.1f}GB/s"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f}MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    return f"{max(bps, 0):.0f}B/s"


def _extract_progress_and_speed(log_text: str) -> tuple[str, str]:
    text = str(log_text or "")
    progress = ""
    speed = ""
    progress_matches = list(_PROGRESS_RE.finditer(text))
    for match in reversed(progress_matches):
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if 0 <= value <= 100:
            progress = f"{value}%"
            break
    speed_matches = list(_SPEED_RE.finditer(text))
    if speed_matches:
        last = speed_matches[-1]
        num = last.group(1)
        unit = last.group(2).upper()
        speed = f"{num}{unit}"
    return progress, speed


def _is_test_mode() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


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
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    def _emit(self, signal_name: str, *args) -> bool:
        if self._cancelled:
            return False
        try:
            signal = getattr(self, signal_name)
        except RuntimeError:
            logger.debug("Skipped worker signal access on deleted Qt object", exc_info=True)
            return False
        return _safe_emit(signal, *args)

    @pyqtSlot()
    def run(self):
        try:
            result = env_detector.detect(self._ssh_run_fn)
            self._emit("finished", result)
        except Exception as e:
            if self._cancelled:
                return
            logger.exception("CondaDetectWorker 出错")
            self._emit("error", str(e))


class MiniforgeBootstrapSubmitWorker(QObject):
    """在 QThread 中提交 detached Miniforge 初始化任务。"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        if self._cancelled:
            return
        try:
            result = miniforge_bootstrap.submit(self._ssh_run_fn)
            if self._cancelled:
                return
            self.finished.emit(result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("提交 Miniforge 后台任务失败")
            self.error.emit(str(exc))


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

    def __init__(self, ssh_run_fn, tools: list[dict], conda_executable: str = ""):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self.tools = tools
        self._conda_executable = conda_executable or "conda"
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    def _emit(self, signal_name: str, *args) -> bool:
        if self._cancelled:
            return False
        try:
            signal = getattr(self, signal_name)
        except RuntimeError:
            logger.debug("Skipped worker signal access on deleted Qt object", exc_info=True)
            return False
        return _safe_emit(signal, *args)

    @pyqtSlot()
    def run(self):
        try:
            results, conda_envs = check_all_envs(
                ssh_run_fn=self._ssh_run_fn,
                tools=self.tools,
                conda_executable=self._conda_executable,
            )

            for r in results:
                if not self._emit("tool_checked", r.tool_id, r.env_name, r.ok):
                    return

            self._emit("finished", conda_envs)

        except Exception as e:
            if self._cancelled:
                return
            logger.exception("EnvBatchCheckWorker 出错")
            self._emit("error", str(e))


class ToolInstallBatchPollWorker(QObject):
    """批量轮询工具环境安装状态（后台线程）。"""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, tool_ids: list[str]):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_ids = list(tool_ids)
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            rows = EnvInstaller.batch_probe(
                self._ssh_run_fn,
                self._tool_ids,
                tail_lines=120,
                timeout=20,
            )
            if not self._cancelled:
                self.finished.emit(rows)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallBatchPollWorker 出错")
            self.error.emit(str(exc))


class ToolInstallSubmitWorker(QObject):
    """后台提交工具环境安装任务。"""

    finished = pyqtSignal(str, dict)
    error = pyqtSignal(str, str)

    def __init__(self, ssh_run_fn, tool_id: str, install_cmd: str, conda_executable: str):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_id = str(tool_id or "").strip()
        self._install_cmd = str(install_cmd or "")
        self._conda_executable = str(conda_executable or "")
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        if self._cancelled:
            return
        try:
            result = EnvInstaller.submit(
                self._ssh_run_fn,
                self._tool_id,
                self._install_cmd,
                self._conda_executable,
            )
            if not self._cancelled:
                self.finished.emit(self._tool_id, result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallSubmitWorker 出错: tool_id=%s", self._tool_id)
            self.error.emit(self._tool_id, str(exc))


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
    install_task_event = pyqtSignal(dict)
    tool_install_snapshot_updated = pyqtSignal(str, dict)

    def __init__(self, parent=None, plugin_registry=None):
        super().__init__(parent)
        self.setObjectName("LinuxSettingsCard")

        self.active_client = None
        self._ssh_service = None
        self._is_locked = False
        self._checking = False
        self._in_edit_mode = False
        self._external_lock = False

        self._plugin_registry = plugin_registry
        self._conda_executable: str = ""
        self._auto_installed: bool = False
        self._detect_interactive_request: bool = False
        self._miniforge_installing: bool = False
        self._miniforge_task_dir: str = miniforge_bootstrap.TASK_DIR
        self._miniforge_polling: bool = False
        self._miniforge_poll_timer = QTimer(self)
        self._miniforge_poll_timer.setInterval(3000)
        self._miniforge_poll_timer.timeout.connect(self._poll_miniforge_status)
        self._tool_install_polling: bool = False
        self._tool_install_poll_timer = QTimer(self)
        self._tool_install_poll_timer.setInterval(TOOL_INSTALL_POLL_INTERVAL_MS)
        self._tool_install_poll_timer.timeout.connect(self._poll_running_tool_installs)
        self._tool_log_samples: dict[str, tuple[int, float]] = {}
        self._latest_detected_env_paths: set[str] = set()
        self._pending_recover_after_batch: bool = False
        self._tool_install_snapshots: dict[str, dict] = {}
        self._tool_install_submitting_ids: set[str] = set()
        self._tool_install_submit_threads: dict[str, QThread] = {}
        self._tool_install_submit_workers: dict[str, ToolInstallSubmitWorker] = {}

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

    def _emit_install_task_event(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        state: str,
        detail: str = "",
    ) -> None:
        payload = {
            "task_id": str(task_id or "").strip(),
            "title": str(title or "").strip(),
            "source": str(source or "").strip(),
            "state": str(state or "").strip().lower() or "running",
            "detail": str(detail or "").strip(),
        }
        if not payload["task_id"] or not payload["title"]:
            return
        try:
            self.install_task_event.emit(payload)
        except RuntimeError:
            logger.debug("install_task_event emit skipped on deleted card", exc_info=True)

    def _emit_bootstrap_install_event(self, state: str, detail: str = "") -> None:
        self._emit_install_task_event(
            task_id="bootstrap:miniforge",
            title="运行环境初始化",
            source="bootstrap",
            state=state,
            detail=detail,
        )

    def _emit_tool_install_event(self, tool_id: str, state: str, detail: str = "") -> None:
        tool = next((t for t in self._tools if t.get("id") == tool_id), None)
        tool_name = str((tool or {}).get("name", "") or tool_id).strip() or tool_id
        self._emit_install_task_event(
            task_id=f"tool_env:{tool_id}",
            title=f"工具环境安装 · {tool_name}",
            source="tool_env",
            state=state,
            detail=detail,
        )

    def _get_tool_install_snapshot(self, tool_id: str) -> dict:
        return dict(self._tool_install_snapshots.get(str(tool_id or "").strip(), {}))

    def _update_tool_install_snapshot(self, tool_id: str, **updates) -> dict:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            return {}
        current = dict(self._tool_install_snapshots.get(clean_tool_id, {}))
        current.update({k: v for k, v in updates.items() if v is not None})
        current["tool_id"] = clean_tool_id
        current["updated_at"] = time.time()
        self._tool_install_snapshots[clean_tool_id] = current
        _safe_emit(self.tool_install_snapshot_updated, clean_tool_id, dict(current))
        return dict(current)

    def set_active_client(self, client) -> None:
        """接收外部传入的 SSH 客户端实例。SSH 连接成功后自动触发 conda 检测。"""
        self.active_client = client
        if client is not None:
            self._set_status("SSH 已就绪")
            # SSH 连接成功后延迟 1s 自动触发 conda 检测
            if not _is_test_mode():
                QTimer.singleShot(1000, lambda: self._ensure_conda_ready(interactive=False))
        else:
            self._set_status("等待 SSH 连接")

    def set_ssh_service(self, ssh_service) -> None:
        """注入统一 SSHService，优先使用其串行 run 通道。"""
        self._ssh_service = ssh_service

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
        if conda_executable and not is_managed_conda_executable(conda_executable):
            logger.warning("忽略非自管 conda 配置路径: %s", conda_executable)
            self._conda_executable = ""
            self._auto_installed = False
        else:
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
        if _is_test_mode():
            fallback = QLabel("测试模式：已禁用 QtWebEngine 工具环境视图")
            fallback.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            parent_layout.addWidget(fallback)
            self._web_view = None
            self._bridge = None
            self._channel = None
            return

        # 延迟导入 WebEngine（必须在 QApplication 创建后）
        from ui.qt_bootstrap import ensure_qt_webengine_ready
        ensure_qt_webengine_ready()

        try:
            from PyQt6.QtWebChannel import QWebChannel
        except ImportError as exc:
            logger.warning("QtWebEngine 不可用: %s", exc)
            fallback = QLabel("工具环境检测需要 QtWebEngine 支持")
            fallback.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            parent_layout.addWidget(fallback)
            return

        # 创建 Bridge
        self._bridge = ToolEnvBridge(parent=self)

        # 创建 WebView
        self._web_view = create_report_web_view(
            parent=self,
            background="#FFFFFF",
            disable_context_menu=True,
        )
        self._web_view.setMinimumHeight(45)  # 最小高度（折叠时只显示标题行）
        self._web_view.setMaximumHeight(400)  # 最大高度
        self._web_view.setFixedHeight(45)  # 初始高度设为折叠状态
        self._web_view.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self._web_view.setStyleSheet("background: #FFFFFF; border: none;")

        # 设置 WebChannel
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # 加载 HTML
        from core.utils import get_app_root
        assets_dir = get_app_root() / "ui" / "pages" / "settings_page_assets"
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
        def run(cmd, timeout=15):
            start = QElapsedTimer()
            start.start()
            if self._ssh_service is not None and getattr(self._ssh_service, "is_connected", False):
                rc, out, err = self._ssh_service.run(cmd, timeout=timeout)
                logger.debug(
                    "linux_card ssh_run source=service cmd=%r timeout=%s rc=%s duration_ms=%s",
                    cmd[:80], timeout, rc, start.elapsed(),
                )
                return rc, out, err

            client = self.active_client
            if client is None:
                raise RuntimeError("SSH client is not connected")
            _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            # Fallback path: keep safe read ordering to avoid channel hang.
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            rc = stdout.channel.recv_exit_status()
            logger.debug(
                "linux_card ssh_run source=client-fallback cmd=%r timeout=%s rc=%s duration_ms=%s",
                cmd[:80], timeout, rc, start.elapsed(),
            )
            return rc, out, err

        return run

    def _ensure_conda_ready(self, interactive: bool = False) -> None:
        """SSH 连接后的第一层检测 — 检测 conda 是否可用。

        成功后缓存路径、保存配置、更新 ServiceLocator，然后继续 batch check。
        未找到时：
          - 启动自动探测（非交互）: 静默安装并在状态栏提示
          - 用户主动触发（交互）: 弹窗确认后安装
        """
        if _is_test_mode():
            return
        if not self.active_client or self._checking or self._external_lock:
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            return

        self._checking = True
        self._detect_interactive_request = interactive
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
            if not is_managed_conda_executable(result.executable or ""):
                logger.warning("检测到非自管 conda 路径，已忽略: %s", result.executable)
                self._conda_executable = ""
                if self._detect_interactive_request:
                    self._set_status("检测到非自管 conda，已拒绝", STATUS_ERROR)
                    self._prompt_miniforge_install()
                else:
                    self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
                    self._start_miniforge_install_silent()
                return
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
            if self._tools:
                self._pending_recover_after_batch = True
                QTimer.singleShot(200, self._on_batch_check)
            else:
                self._pending_recover_after_batch = False
                QTimer.singleShot(200, lambda: self._recover_running_installs(existing_env_paths=set()))

        elif result.status == CondaStatus.NOT_FOUND:
            if self._detect_interactive_request:
                self._set_status("未检测到 conda", STATUS_ERROR)
                self._prompt_miniforge_install()
            else:
                self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
                self._start_miniforge_install_silent()

    def _on_conda_detect_error(self, msg: str) -> None:
        """conda 检测出错。"""
        self._checking = False
        self._set_status(f"conda 检测失败: {msg[:40]}", STATUS_ERROR)

    def _cleanup_conda_detect_resources(self) -> None:
        """清理 conda 检测线程资源。"""
        cleanup_thread_pair(self, "_conda_detect_thread", "_conda_detect_worker", wait_ms=5000)

    def _cleanup_miniforge_resources(self) -> None:
        """清理 Miniforge 后台任务提交线程资源。"""
        cleanup_thread_pair(self, "_miniforge_thread", "_miniforge_worker", wait_ms=5000)

    def _prompt_miniforge_install(self) -> None:
        """弹窗提示：未检测到自管 conda，引导后台自动安装。"""
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("首次启动初始化")
        box.setText(
            "H2OMeta 需要初始化运行环境（一次性操作）。\n\n"
            "安装目录：\n"
            "~/.h2ometa/conda\n\n"
            "不会影响服务器上已有的软件环境。"
        )
        btn_install = box.addButton("后台自动安装", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_install)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_install:
            self._start_miniforge_install_silent()

    def _prompt_miniforge_install_failed(self, message: str) -> None:
        """静默安装失败后弹窗提示，提供重试入口。"""
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("运行环境初始化失败")
        box.setText(
            "后台初始化未完成，请重试安装。\n\n"
            f"错误信息：{message[:300]}"
        )
        btn_retry = box.addButton("重试安装", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后处理", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_retry)
        box.exec()
        if box.clickedButton() == btn_retry:
            self._start_miniforge_install_silent()

    def _start_miniforge_install_silent(self) -> None:
        """后台静默初始化 Miniforge（detached remote task，可跨重启恢复）。"""
        if not self.active_client:
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_bootstrap_install_event("running", "运行环境初始化进行中")
            return

        self._miniforge_installing = True
        self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
        self._emit_bootstrap_install_event("running", "后台提交初始化任务")
        self._cleanup_miniforge_resources()

        self._miniforge_thread = QThread()
        self._miniforge_worker = MiniforgeBootstrapSubmitWorker(self._make_ssh_run_fn())
        self._miniforge_worker.moveToThread(self._miniforge_thread)
        self._miniforge_thread.started.connect(self._miniforge_worker.run)

        def _on_finished(result: dict) -> None:
            self._miniforge_task_dir = result.get("task_dir", miniforge_bootstrap.TASK_DIR)
            already_running = bool(result.get("already_running", False))
            detail = "已接管后台运行中的初始化任务" if already_running else "初始化任务已提交到后台"
            self._emit_bootstrap_install_event("running", detail)
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._start_miniforge_polling()
            self._cleanup_miniforge_resources()

        def _on_error(msg: str) -> None:
            self._miniforge_installing = False
            self._set_status("运行环境初始化失败，请重试安装", STATUS_ERROR)
            self._emit_bootstrap_install_event("failed", f"提交失败: {msg}")
            self._prompt_miniforge_install_failed(msg)
            self._cleanup_miniforge_resources()

        self._miniforge_worker.finished.connect(_on_finished)
        self._miniforge_worker.error.connect(_on_error)

        self._miniforge_thread.start()

    def _start_miniforge_polling(self) -> None:
        if not self._miniforge_poll_timer.isActive():
            self._miniforge_poll_timer.start()
        QTimer.singleShot(100, self._poll_miniforge_status)

    def _poll_miniforge_status(self) -> None:
        if not self._miniforge_installing or self._miniforge_polling:
            return
        self._miniforge_polling = True
        try:
            status = miniforge_bootstrap.check_status(
                self._make_ssh_run_fn(),
                task_dir=self._miniforge_task_dir,
                timeout=10,
            )
            state = (status.get("status") or "").strip().upper()
            rc = (status.get("exit_code") or "").strip()
            heartbeat = (status.get("heartbeat") or "").strip()
            alive = miniforge_bootstrap.is_session_alive(
                self._make_ssh_run_fn(),
                job_id=miniforge_bootstrap.JOB_ID,
                timeout=10,
            )

            if state == "DONE" or rc == "0":
                self._miniforge_installing = False
                self._miniforge_poll_timer.stop()
                self._set_status("运行环境已就绪，正在检测工具环境...", STATUS_SUCCESS)
                self._emit_bootstrap_install_event("success", "运行环境初始化完成")
                Toast.show_toast(self, "运行环境初始化完成", level="success", duration_ms=3000)
                QTimer.singleShot(200, lambda: self._ensure_conda_ready(interactive=False))
                return

            if state == "FAILED":
                self._handle_miniforge_failure("远端初始化任务失败")
                return

            if state == "RUNNING" and not alive:
                if self._is_stale_heartbeat(heartbeat):
                    self._handle_miniforge_failure("远端会话已退出（状态仍为 RUNNING 且心跳超时）")
                    return

            if not alive and (state == "" or self._is_stale_heartbeat(heartbeat)):
                self._handle_miniforge_failure("远端会话已退出且心跳超时")
                return

            # RUNNING / status 空但 session 存活
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_bootstrap_install_event("running", "后台初始化任务执行中")
        except Exception as exc:
            logger.debug("轮询 Miniforge 初始化状态失败: %s", exc)
            # 网络瞬时抖动不立即失败，保持下次轮询继续
        finally:
            self._miniforge_polling = False

    def _is_stale_heartbeat(self, heartbeat_value: str, stale_seconds: int = MINIFORGE_HEARTBEAT_STALE_SECONDS) -> bool:
        try:
            ts = int((heartbeat_value or "").strip())
        except Exception:
            return True
        return (time.time() - ts) > stale_seconds

    def _handle_miniforge_failure(self, reason: str) -> None:
        self._miniforge_installing = False
        self._miniforge_poll_timer.stop()
        log_text = miniforge_bootstrap.read_log(
            self._make_ssh_run_fn(),
            task_dir=self._miniforge_task_dir,
            tail_lines=40,
            timeout=10,
        )
        tail = log_text.strip()
        message = f"{reason}\n\n{tail}" if tail else reason
        self._set_status("运行环境初始化失败，请重试安装", STATUS_ERROR)
        self._emit_bootstrap_install_event("failed", reason)
        self._prompt_miniforge_install_failed(message)

    # ── 批量检测 ─────────────────────────────────────────

    def _on_batch_check(self) -> None:
        """一键检测所有工具环境（外部调用入口）。"""
        self._do_batch_check()

    def _on_batch_check_from_web(self) -> None:
        """从 Web UI 调用的检测入口 — 如果 conda 已知则直接检测，否则先检测 conda。"""
        if self._conda_executable and is_managed_conda_executable(self._conda_executable):
            self._do_batch_check()
        else:
            self._ensure_conda_ready(interactive=True)

    def _do_batch_check(self) -> None:
        """实际执行批量检测。"""
        if not self.active_client or self._checking or self._external_lock:
            return

        if not is_managed_conda_executable(self._conda_executable):
            self._set_status("未检测到自管 conda，无法检测工具环境", STATUS_ERROR)
            QTimer.singleShot(200, lambda: self._ensure_conda_ready(interactive=True))
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
            self._make_ssh_run_fn(), self._tools, self._conda_executable,
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
        self._latest_detected_env_paths = set(env_paths_set)
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

        if self._pending_recover_after_batch:
            self._pending_recover_after_batch = False
            logger.debug("恢复安装状态复用本轮环境快照: env_count=%d", len(env_paths_set))
            self._recover_running_installs(existing_env_paths=env_paths_set)

    def _on_batch_error(self, msg: str) -> None:
        """检测出错。"""
        self._checking = False
        self._set_status(f"检测失败: {msg[:30]}", STATUS_ERROR)
        if self._pending_recover_after_batch:
            self._pending_recover_after_batch = False
            logger.debug("批量检测失败，回退到独立恢复流程")
            self._recover_running_installs(existing_env_paths=None)

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
            self._queue_install_tool(tool)

    def _ensure_tool_install_ready(self, *, interactive: bool = True) -> bool:
        """工具安装前置守卫：SSH + 自管 conda 就绪。"""
        if not self.active_client:
            self._set_status("SSH 未连接，无法安装", STATUS_ERROR)
            return False
        if self._miniforge_installing:
            self._set_status("运行环境正在初始化，请稍后再安装工具", STATUS_NEUTRAL)
            return False
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self._set_status("运行环境未就绪，请先完成初始化", STATUS_ERROR)
            if interactive:
                QTimer.singleShot(100, lambda: self._ensure_conda_ready(interactive=True))
            return False
        return True

    def _queue_install_tool(self, tool: dict) -> None:
        """在当前事件结束后再打开安装对话框，避免 WebChannel 回调重入。"""
        tool_snapshot = dict(tool)
        QTimer.singleShot(0, lambda: self._do_install_tool(tool_snapshot))

    def _do_install_tool(self, tool: dict) -> None:
        """实际执行安装工具。"""
        try:
            dlg = EnvInstallDialog(tool, parent=self)
            dlg.install_requested.connect(self._on_dialog_install_requested)
            self.tool_install_snapshot_updated.connect(dlg.on_snapshot_updated)

            tool_id = str(tool.get("id", "") or "").strip()
            snapshot = self._get_tool_install_snapshot(tool_id)
            if not snapshot and tool_id in self._installing_tool_ids:
                snapshot = self._update_tool_install_snapshot(
                    tool_id,
                    status="RUNNING",
                    message="安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
                )
            if not snapshot and tool_id in self._tool_install_submitting_ids:
                snapshot = self._update_tool_install_snapshot(
                    tool_id,
                    status="SUBMITTING",
                    message="正在提交后台安装任务……",
                )
            if snapshot:
                dlg.apply_install_snapshot(snapshot)
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
            if tool_id:
                self._emit_tool_install_event(tool_id, "failed", f"打开安装窗口失败: {exc}")
            QMessageBox.critical(
                self,
                "安装窗口打开失败",
                f"工具【{tool_name}】的安装窗口打开失败。\n\n错误信息：{exc}",
            )

    def _on_dialog_install_requested(self, tool_id: str) -> None:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            return

        if clean_tool_id in self._tool_install_submitting_ids:
            self._update_tool_install_snapshot(
                clean_tool_id,
                status="SUBMITTING",
                message="安装任务提交中，请稍候……",
            )
            return

        if clean_tool_id in self._installing_tool_ids:
            self._update_tool_install_snapshot(
                clean_tool_id,
                status="RUNNING",
                message="安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
            )
            self._ensure_tool_install_polling()
            return

        if not self._ensure_tool_install_ready(interactive=True):
            self._update_tool_install_snapshot(
                clean_tool_id,
                status="FAILED",
                message="运行环境未就绪，请先完成初始化。",
            )
            self._emit_tool_install_event(clean_tool_id, "failed", "运行环境未就绪，无法安装")
            return

        tool = next((t for t in self._tools if t.get("id") == clean_tool_id), None)
        install_cmd = str((tool or {}).get("install_cmd", "") or "").strip()
        if not install_cmd:
            self._update_tool_install_snapshot(
                clean_tool_id,
                status="FAILED",
                message="该工具未配置 install_cmd，无法自动安装。",
            )
            self._emit_tool_install_event(clean_tool_id, "failed", "该工具未配置 install_cmd")
            return

        self._start_tool_install_submit(clean_tool_id, install_cmd)

    def _start_tool_install_submit(self, tool_id: str, install_cmd: str) -> None:
        self._cleanup_tool_install_submit_job(tool_id)
        self._tool_install_submitting_ids.add(tool_id)
        self._update_tool_install_snapshot(
            tool_id,
            status="SUBMITTING",
            message="正在提交后台安装任务……",
        )
        self._emit_tool_install_event(tool_id, "running", "正在提交安装任务")

        thread = QThread(self)
        worker = ToolInstallSubmitWorker(
            self._make_ssh_run_fn(),
            tool_id,
            install_cmd,
            self._conda_executable,
        )
        worker.moveToThread(thread)
        self._tool_install_submit_threads[tool_id] = thread
        self._tool_install_submit_workers[tool_id] = worker

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_tool_install_submit_finished)
        worker.error.connect(self._on_tool_install_submit_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()

    def _cleanup_tool_install_submit_job(self, tool_id: str) -> None:
        clean_tool_id = str(tool_id or "").strip()
        worker = self._tool_install_submit_workers.pop(clean_tool_id, None)
        thread = self._tool_install_submit_threads.pop(clean_tool_id, None)
        if worker is not None:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except RuntimeError:
                    logger.debug("submit worker already deleted: %s", clean_tool_id, exc_info=True)
            worker.deleteLater()
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
            thread.deleteLater()

    def _cleanup_tool_install_submit_resources(self) -> None:
        for tool_id in list(self._tool_install_submit_threads.keys()):
            self._cleanup_tool_install_submit_job(tool_id)
        self._tool_install_submitting_ids.clear()

    def _on_tool_install_submit_finished(self, tool_id: str, result: dict) -> None:
        clean_tool_id = str(tool_id or "").strip()
        self._tool_install_submitting_ids.discard(clean_tool_id)
        self._cleanup_tool_install_submit_job(clean_tool_id)

        task_dir = str((result or {}).get("task_dir", "") or "").strip()
        job_id = str((result or {}).get("job_id", "") or "").strip()
        self._on_install_submitted(clean_tool_id)
        self._update_tool_install_snapshot(
            clean_tool_id,
            status="RUNNING",
            task_dir=task_dir,
            job_id=job_id,
            message="安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
        )

    def _on_tool_install_submit_error(self, tool_id: str, message: str) -> None:
        clean_tool_id = str(tool_id or "").strip()
        self._tool_install_submitting_ids.discard(clean_tool_id)
        self._cleanup_tool_install_submit_job(clean_tool_id)
        self._installing_tool_ids.discard(clean_tool_id)
        self._tool_log_samples.pop(clean_tool_id, None)
        self._update_tool_install_snapshot(
            clean_tool_id,
            status="FAILED",
            message=f"启动安装失败: {message}",
        )
        if clean_tool_id:
            self._emit_tool_install_event(clean_tool_id, "failed", f"提交安装失败: {message}")
        self._ensure_tool_install_polling()

    def _on_install_submitted(self, tool_id: str) -> None:
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._installing_tool_ids.add(tool_id)
        if self._bridge:
            self._bridge.emit_install_started(tool_id)
        self._emit_tool_install_event(tool_id, "running", "安装任务已提交，正在拉取进度")
        self._update_tool_install_snapshot(
            tool_id,
            status="RUNNING",
            message="安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
        )
        self._ensure_tool_install_polling()

    def _on_install_succeeded(self, tool_id: str) -> None:
        """某工具安装成功后：提示数据库（如需要），然后重新检测。"""
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._tool_install_submitting_ids.discard(tool_id)
        # 从安装中集合移除
        self._installing_tool_ids.discard(tool_id)
        self._tool_log_samples.pop(tool_id, None)
        # 通知 JS 安装完成
        if self._bridge:
            self._bridge.emit_install_finished(tool_id, True)
        self._emit_tool_install_event(tool_id, "success", "工具环境安装完成")
        self._update_tool_install_snapshot(
            tool_id,
            status="DONE",
            message="安装成功！",
        )
        self._ensure_tool_install_polling()

        tool = next((t for t in self._tools if t["id"] == tool_id), None)
        tool_name = tool.get("name", tool_id) if tool else tool_id

        if tool and tool.get("databases"):
            db_names = [d.get("id", "") for d in tool["databases"] if d.get("id", "")]
            db_hint = f"，请配置数据库：{', '.join(db_names[:3])}" if db_names else "，请在数据库页配置所需数据库"
            Toast.show_toast(
                self,
                f"工具 {tool_name} 安装完成{db_hint}",
                level="info",
                duration_ms=4200,
            )
        else:
            Toast.show_toast(self, f"工具 {tool_name} 安装完成", level="success", duration_ms=3000)

        # 重新检测所有工具
        QTimer.singleShot(300, self._on_batch_check)

    def _on_install_failed(self, tool_id: str) -> None:
        """安装失败后通知 JS 更新状态。"""
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._tool_install_submitting_ids.discard(tool_id)
        # 从安装中集合移除
        self._installing_tool_ids.discard(tool_id)
        self._tool_log_samples.pop(tool_id, None)
        if self._bridge:
            self._bridge.emit_install_finished(tool_id, False)
        self._emit_tool_install_event(tool_id, "failed", "工具环境安装失败")
        self._update_tool_install_snapshot(
            tool_id,
            status="FAILED",
            message="安装失败，请检查上方输出或网络后重试。",
        )
        self._ensure_tool_install_polling()

    def _recover_running_installs(self, existing_env_paths: Optional[set[str]] = None) -> None:
        """启动时扫描 ~/.h2ometa/env_installs/*/status.txt，恢复安装状态。

        - RUNNING → 恢复为“安装中”并继续轮询
        - DONE    → 静默清理并触发一次重检（不写入安装任务面板）
        - FAILED  → 保留诊断目录，不在启动时写入安装任务面板
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

        if existing_env_paths is None:
            # 回退路径：仍可独立查询
            existing_env_paths = self._get_existing_env_paths()
            logger.debug("恢复安装状态使用独立环境查询: env_count=%d", len(existing_env_paths))
        else:
            existing_env_paths = {p.rstrip("/") for p in existing_env_paths if p}
            logger.debug("恢复安装状态使用缓存环境查询: env_count=%d", len(existing_env_paths))

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
                    self._update_tool_install_snapshot(
                        tool_id,
                        status="DONE",
                        task_dir=task_dir,
                        message="检测到环境已就绪，安装视为完成。",
                    )
                    # 清理残留的安装目录
                    try:
                        EnvInstaller.cleanup(self._make_ssh_run_fn(), task_dir)
                    except Exception:
                        pass
                else:
                    alive = EnvInstaller.is_session_alive(
                        self._make_ssh_run_fn(), f"h2o_install_{tool_id}", timeout=10
                    )
                    if alive:
                        running_tools.append(tool_id)
                        self._installing_tool_ids.add(tool_id)
                        self._update_tool_install_snapshot(
                            tool_id,
                            status="RUNNING",
                            task_dir=task_dir,
                            message="检测到后台安装任务仍在运行",
                        )
                        # 通知 Web UI 显示"安装中"状态
                        if self._bridge:
                            self._bridge.emit_install_started(tool_id)
                        self._emit_tool_install_event(tool_id, "running", "检测到后台安装任务仍在运行")
                        self._ensure_tool_install_polling()
                    else:
                        logger.info("工具 %s RUNNING 但会话已不存在且环境未落地，静默回缺失", tool_id)
                        self._installing_tool_ids.discard(tool_id)
                        self._tool_log_samples.pop(tool_id, None)
                        self._update_tool_install_snapshot(
                            tool_id,
                            status="FAILED",
                            task_dir=task_dir,
                            message="安装会话已退出且环境未落地，请重试安装。",
                        )
                        if self._bridge:
                            self._bridge.emit_install_finished(tool_id, False)
                        newly_done = True
                        try:
                            EnvInstaller.cleanup(self._make_ssh_run_fn(), task_dir)
                        except Exception:
                            pass
            elif status == "DONE":
                newly_done = True
                self._update_tool_install_snapshot(
                    tool_id,
                    status="DONE",
                    task_dir=task_dir,
                    message="安装任务已完成。",
                )
                logger.info("发现已完成的后台安装任务，静默清理: %s", tool_id)
                # 清理已完成的安装目录
                try:
                    EnvInstaller.cleanup(self._make_ssh_run_fn(), task_dir)
                except Exception:
                    pass
            elif status == "FAILED":
                # 保留失败目录供诊断，启动恢复阶段不提示，避免误判为新失败
                self._update_tool_install_snapshot(
                    tool_id,
                    status="FAILED",
                    task_dir=task_dir,
                    message="检测到历史失败任务，请查看日志后重试。",
                )
                logger.info("发现失败的后台安装任务，跳过启动提示: %s", tool_id)

        if running_tools:
            names = ", ".join(running_tools)
            self._set_status(f"后台安装进行中: {names}")

        if newly_done:
            QTimer.singleShot(500, self._on_batch_check)

    def _ensure_tool_install_polling(self) -> None:
        if self._installing_tool_ids:
            was_active = self._tool_install_poll_timer.isActive()
            if not was_active:
                self._tool_install_poll_timer.start()
                QTimer.singleShot(100, self._poll_running_tool_installs)
        else:
            if self._tool_install_poll_timer.isActive():
                self._tool_install_poll_timer.stop()
            self._tool_install_polling = False

    def _cleanup_tool_install_poll_resources(self) -> None:
        cleanup_thread_pair(self, "_tool_install_poll_thread", "_tool_install_poll_worker", wait_ms=3000)

    def _poll_running_tool_installs(self) -> None:
        if not self._installing_tool_ids:
            self._ensure_tool_install_polling()
            return
        if self._tool_install_polling:
            return
        if not self.active_client:
            return

        self._tool_install_polling = True
        self._cleanup_tool_install_poll_resources()

        self._tool_install_poll_thread = QThread()
        self._tool_install_poll_worker = ToolInstallBatchPollWorker(
            self._make_ssh_run_fn(),
            sorted(self._installing_tool_ids),
        )
        self._tool_install_poll_worker.moveToThread(self._tool_install_poll_thread)
        self._tool_install_poll_thread.started.connect(self._tool_install_poll_worker.run)
        self._tool_install_poll_worker.finished.connect(self._on_tool_install_poll_finished)
        self._tool_install_poll_worker.error.connect(self._on_tool_install_poll_error)
        self._tool_install_poll_worker.finished.connect(self._cleanup_tool_install_poll_resources)
        self._tool_install_poll_worker.error.connect(self._cleanup_tool_install_poll_resources)
        self._tool_install_poll_thread.start()

    def _build_tool_install_running_detail(self, tool_id: str, log_text: str, log_size: int) -> str:
        progress, speed = _extract_progress_and_speed(log_text)
        now = time.time()
        last = self._tool_log_samples.get(tool_id)
        self._tool_log_samples[tool_id] = (max(int(log_size or 0), 0), now)

        if not speed and last is not None:
            last_size, last_ts = last
            delta_size = max(int(log_size or 0) - int(last_size or 0), 0)
            delta_ts = max(now - float(last_ts or 0.0), 1e-6)
            if delta_size > 0:
                speed = _format_rate(delta_size / delta_ts)

        parts: list[str] = []
        if progress:
            parts.append(progress)
        if speed:
            parts.append(f"速度 {speed}")
        if parts:
            return " · ".join(parts)
        return "后台安装任务执行中"

    def _on_tool_install_poll_finished(self, rows: list[dict]) -> None:
        self._tool_install_polling = False
        need_recheck = False
        existing_env_paths: Optional[set[str]] = None

        for row in rows or []:
            tool_id = str(row.get("tool_id", "") or "").strip()
            if not tool_id or tool_id not in self._installing_tool_ids:
                continue

            status_text = str(row.get("status", "") or "").strip().upper()
            log_text = str(row.get("log_text", "") or "")
            log_size = int(row.get("log_size", 0) or 0)
            exit_code = str(row.get("exit_code", "") or "").strip()
            session_alive = bool(row.get("session_alive", False))

            self._update_tool_install_snapshot(
                tool_id,
                status=status_text or "RUNNING",
                log_text=log_text,
                log_size=max(log_size, 0),
                exit_code=exit_code,
                session_alive=session_alive,
            )

            if status_text == "DONE":
                self._on_install_succeeded(tool_id)
                need_recheck = True
                try:
                    EnvInstaller.cleanup(self._make_ssh_run_fn(), f"{_INSTALL_BASE}/{tool_id}")
                except Exception:
                    pass
                continue

            if status_text == "FAILED":
                self._on_install_failed(tool_id)
                if exit_code:
                    self._update_tool_install_snapshot(
                        tool_id,
                        status="FAILED",
                        exit_code=exit_code,
                        message=f"安装失败 (exit_code={exit_code})，请检查上方输出后重试。",
                    )
                continue

            if status_text in ("", "RUNNING") and not session_alive:
                if existing_env_paths is None:
                    existing_env_paths = self._get_existing_env_paths()
                tool = next((t for t in self._tools if t["id"] == tool_id), None)
                if tool and self._is_tool_env_exists(tool, existing_env_paths):
                    self._on_install_succeeded(tool_id)
                    need_recheck = True
                    try:
                        EnvInstaller.cleanup(self._make_ssh_run_fn(), f"{_INSTALL_BASE}/{tool_id}")
                    except Exception:
                        pass
                else:
                    logger.info("工具 %s 安装会话已退出且状态不可靠，静默回缺失", tool_id)
                    self._installing_tool_ids.discard(tool_id)
                    self._tool_log_samples.pop(tool_id, None)
                    if self._bridge:
                        self._bridge.emit_install_finished(tool_id, False)
                    self._update_tool_install_snapshot(
                        tool_id,
                        status="FAILED",
                        message="安装会话已退出且状态不可靠，请重试安装。",
                    )
                    need_recheck = True
                    try:
                        EnvInstaller.cleanup(self._make_ssh_run_fn(), f"{_INSTALL_BASE}/{tool_id}")
                    except Exception:
                        pass
                continue

            detail = self._build_tool_install_running_detail(
                tool_id,
                log_text,
                log_size,
            )
            self._update_tool_install_snapshot(
                tool_id,
                status="RUNNING",
                log_text=log_text,
                log_size=max(log_size, 0),
                message=detail,
            )
            self._emit_tool_install_event(tool_id, "running", detail)

        if need_recheck:
            QTimer.singleShot(300, self._on_batch_check)
        self._ensure_tool_install_polling()

    def _on_tool_install_poll_error(self, msg: str) -> None:
        self._tool_install_polling = False
        logger.debug("轮询工具安装状态失败: %s", msg)
        self._ensure_tool_install_polling()

    def _get_existing_env_paths(self) -> set[str]:
        """获取远端所有已存在的 conda 环境路径集合。"""
        if not self._conda_executable:
            return set()

        try:
            paths = get_existing_env_paths(
                ssh_run_fn=self._make_ssh_run_fn(),
                conda_executable=self._conda_executable,
            )
            logger.debug("linux_card existing env paths count=%s", len(paths))
            return paths
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

        if self._conda_executable and not is_managed_conda_executable(self._conda_executable):
            self._set_status(f"仅允许使用自管 conda: {H2O_CONDA_EXE}", STATUS_ERROR)
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
        if self._miniforge_poll_timer.isActive():
            self._miniforge_poll_timer.stop()
        if self._tool_install_poll_timer.isActive():
            self._tool_install_poll_timer.stop()
        self._cleanup_tool_install_submit_resources()
        cleanup_thread_pair(self, "_conda_detect_thread", "_conda_detect_worker", wait_ms=1000)
        cleanup_thread_pair(self, "_check_thread", "_check_worker", wait_ms=1000)
        cleanup_thread_pair(self, "_miniforge_thread", "_miniforge_worker", wait_ms=1000)
        cleanup_thread_pair(self, "_tool_install_poll_thread", "_tool_install_poll_worker", wait_ms=1000)
        super().closeEvent(event)
