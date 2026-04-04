from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
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
    CARD_TITLE,
    COLOR_TEXT_HINT,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
)
from ui.install_log_parser import extract_progress_and_speed
from ui.controllers.install_workflow import (
    InstallWorkflowStore,
    build_bootstrap_task_event,
    build_tool_install_task_event,
)
from ui.widgets.linux_settings_components import ClickableHeader, EnvInstallDialog, ToolEnvBridge
from ui.widgets.linux_settings_miniforge import LinuxSettingsMiniforgeMixin, _is_test_mode
from ui.widgets.linux_settings_tool_install import LinuxSettingsToolInstallMixin
from ui.widgets.linux_settings_workers import (
    EnvBatchCheckWorker,
    _format_rate,
    _safe_emit,
)
from ui.widgets.web_ui_host import create_local_web_ui_host
from ui.widgets.toast import Toast
from ui.workers.base_worker import launch_worker, request_worker_stop

from core.environment import env_detector
from core.environment import miniforge_bootstrap
from core.environment.env_installer import EnvInstaller
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.utils import get_app_root

logger = logging.getLogger(__name__)
TOOL_INSTALL_POLL_INTERVAL_MS = 3000


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(LinuxSettingsMiniforgeMixin, LinuxSettingsToolInstallMixin, QFrame):
    """Linux 项目与运行环境配置卡片（含工具环境检测+安装）。

    功能：
      - 批量检测 16 个插件工具的 conda 环境是否就绪（一键检测）。
      - 对 ❌ 工具提供"安装"按钮，点击后弹出 EnvInstallDialog 执行 conda create。
      - 安装成功后自动重新检测；需要数据库的工具给出提示。
      - 支持 plugin_registry 外部注入（PluginRegistry 动态读取工具列表）。
      - 使用 Web UI (QWebEngineView) 展示工具环境表格，解决对齐问题。

    get_values() 返回字段:
      conda_executable
    """

    request_save = pyqtSignal()
    install_task_event = pyqtSignal(dict)
    tool_install_snapshot_updated = pyqtSignal(str, dict)
    deploy_state_changed = pyqtSignal(dict)
    STATUS_NEUTRAL = STATUS_NEUTRAL
    STATUS_SUCCESS = STATUS_SUCCESS
    STATUS_ERROR = STATUS_ERROR

    def __init__(self, parent=None, plugin_registry=None):
        super().__init__(parent)
        self.setObjectName("LinuxSettingsCard")

        self._ssh_service = None
        self._checking = False
        self._external_lock = False

        self._plugin_registry = plugin_registry
        self._conda_executable: str = ""
        self._miniforge_deployed: bool = False
        self._miniforge_probe_inflight: bool = False
        self._miniforge_probe_completed: bool = False
        self._miniforge_installing: bool = False
        self._miniforge_task_dir: str = miniforge_bootstrap.TASK_DIR
        self._miniforge_polling: bool = False
        self._miniforge_poll_timer = QTimer(self)
        self._miniforge_poll_timer.setSingleShot(True)
        self._miniforge_poll_timer.timeout.connect(self._poll_miniforge_status)
        self._tool_install_polling: bool = False
        self._tool_install_poll_timer = QTimer(self)
        self._tool_install_poll_timer.setInterval(TOOL_INSTALL_POLL_INTERVAL_MS)
        self._tool_install_poll_timer.timeout.connect(self._poll_running_tool_installs)
        self._tool_log_samples: dict[str, tuple[int, float]] = {}
        self._latest_detected_env_paths: set[str] = set()
        self._pending_recover_after_batch: bool = False
        self._recover_installs_running: bool = False
        self._workflow_store = InstallWorkflowStore()
        self._tool_install_submitting_ids: set[str] = set()
        self._tool_install_dialogs: dict[str, EnvInstallDialog] = {}

        # 工具列表: [{"id", "name", "conda_env", "install_cmd", "databases"}]
        self._tools: list[dict] = []
        # 正在安装的工具 ID 集合（用于检测时跳过）
        self._installing_tool_ids: set[str] = set()

        # Web UI 相关
        self._web_view = None
        self._bridge: Optional[ToolEnvBridge] = None
        self._channel = None

        self._build_ui()

    # ── 公开 API ─────────────────────────────────────────

    def set_plugin_registry(self, plugin_registry) -> None:
        """外部注入 PluginRegistry，用于刷新工具列表。"""
        self._plugin_registry = plugin_registry
        self._refresh_tool_list()

    def _emit_install_task(self, payload: dict) -> None:
        if not payload.get("task_id") or not payload.get("title"):
            return
        self.install_task_event.emit(payload)

    def locate_install_task(self, task: dict) -> None:
        source = str(task.get("source", "") or "").strip().lower()
        if source == "bootstrap":
            self._set_status("请在本页查看运行环境初始化状态。", self.STATUS_NEUTRAL)
            return
        if source != "tool_env":
            return

        tool_id = self._resolve_tool_id_from_task(task)
        if not tool_id:
            logger.warning("无法定位工具安装任务: %s", task)
            self._set_status("未找到对应工具，无法打开安装窗口。", self.STATUS_ERROR)
            return
        self._on_install_from_web(tool_id)

    def _resolve_tool_id_from_task(self, task: dict) -> str:
        task_id = str(task.get("task_id", "") or "").strip()
        if task_id.startswith("tool_env:"):
            return str(task_id.split(":", 1)[1]).strip()

        title = str(task.get("title", "") or "").strip()
        if "·" in title:
            display_name = title.split("·", 1)[1].strip()
            if display_name:
                for item in self._tools:
                    name = str(item.get("name", "") or "").strip()
                    if name == display_name:
                        return str(item.get("id", "") or "").strip()

        return ""

    def _tool_display_name(self, tool_id: str) -> str:
        clean_tool_id = str(tool_id or "").strip()
        tool = next((item for item in self._tools if item.get("id") == clean_tool_id), None)
        return str((tool or {}).get("name", "") or clean_tool_id).strip() or clean_tool_id

    def _get_tool_install_snapshot(self, tool_id: str) -> dict:
        return self._workflow_store.get_tool_snapshot(tool_id)

    def _update_tool_install_snapshot(self, tool_id: str, **updates) -> dict:
        current = self._workflow_store.update_tool_snapshot(tool_id, **updates)
        clean_tool_id = str(current.get("tool_id", "") or "").strip()
        if not clean_tool_id:
            return {}
        _safe_emit(self.tool_install_snapshot_updated, clean_tool_id, dict(current))
        return dict(current)

    def _is_ssh_service_ready(self) -> bool:
        return self._ssh_service is not None and bool(getattr(self._ssh_service, "is_connected", False))

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在 SSH 连接被占用时禁用交互。"""
        if self._external_lock == locked:
            return
        self._external_lock = locked

    def _set_status(self, text: str, style: str = STATUS_NEUTRAL) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(style)

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

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
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

        # ── 状态行 ──
        row = QHBoxLayout()
        self.status_label = QLabel("等待 SSH 连接")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

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

        try:
            # 延迟导入 WebEngine（必须在 QApplication 创建后）
            self._bridge = ToolEnvBridge(parent=self)
            assets_dir = get_app_root() / "ui" / "pages" / "settings_page_assets"
            html_path = assets_dir / "tool_env_table.html"
            self._web_view, self._channel = create_local_web_ui_host(
                parent=self,
                bridge_name="bridge",
                bridge_object=self._bridge,
                html_path=html_path,
                background="#FFFFFF",
                disable_context_menu=True,
                allow_remote_resources=True,
                raise_on_missing_html=False,
            )
        except ImportError as exc:
            logger.warning("QtWebEngine 不可用: %s", exc)
            fallback = QLabel("工具环境检测需要 QtWebEngine 支持")
            fallback.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            parent_layout.addWidget(fallback)
            return

        self._web_view.setMinimumHeight(45)  # 最小高度（折叠时只显示标题行）
        self._web_view.setMaximumHeight(400)  # 最大高度
        self._web_view.setFixedHeight(45)  # 初始高度设为折叠状态
        self._web_view.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

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

    # ── 运行环境探测 ────────────────────────────────────────

    def _make_ssh_run_fn(self):
        """仅经 SSHService 串行队列发送命令，服务不可用时快速失败。"""
        def run(cmd, timeout=15):
            if self._is_ssh_service_ready():
                rc, out, err = self._ssh_service.run(cmd, timeout=timeout)
                logger.debug("linux_card ssh_run cmd=%r timeout=%s rc=%s", cmd[:80], timeout, rc)
                return rc, out, err

            raise RuntimeError("SSH service is not connected")

        return run

    # ── 批量检测 ─────────────────────────────────────────

    def _on_batch_check_from_web(self) -> None:
        """从 Web UI 调用的检测入口。"""
        self._do_batch_check()

    def _do_batch_check(self) -> None:
        """实际执行批量检测。"""
        if not self._is_ssh_service_ready() or self._checking or self._external_lock:
            return

        if (not self._miniforge_deployed) or (not is_managed_conda_executable(self._conda_executable)):
            self._set_status("请先点击“一键部署运行环境”", STATUS_ERROR)
            return

        if not self._tools:
            self._set_status("未发现工具，请检查插件目录", STATUS_ERROR)
            return

        self._checking = True
        self._set_status("正在检测工具环境...")

        # 立即通知 Web UI 检测开始（避免用户感觉点击后无响应）
        if self._bridge:
            self._bridge.emit_check_started()

        worker = EnvBatchCheckWorker(
            self._make_ssh_run_fn(), self._tools, self._conda_executable,
        )
        worker.tool_checked.connect(self._on_tool_checked)
        launch_worker(
            self,
            "_check_thread",
            "_check_worker",
            worker,
            on_finished=self._on_batch_finished,
            on_error=self._on_batch_error,
        )

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

    # ── 折叠/展开 ─────────────────────────────────────────

    def _toggle_container(self):
        if self._checking or self._external_lock:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

    def closeEvent(self, event) -> None:
        if self._miniforge_poll_timer.isActive():
            self._miniforge_poll_timer.stop()
        if self._tool_install_poll_timer.isActive():
            self._tool_install_poll_timer.stop()
        self._close_tool_install_dialogs()
        self._tool_install_submitting_ids.clear()
        request_worker_stop(self, "_tool_install_submit_thread", "_tool_install_submit_worker")
        request_worker_stop(self, "_check_thread", "_check_worker")
        self._cleanup_miniforge_resources()
        request_worker_stop(self, "_recover_installs_thread", "_recover_installs_worker")
        request_worker_stop(self, "_tool_install_poll_thread", "_tool_install_poll_worker")
        super().closeEvent(event)
