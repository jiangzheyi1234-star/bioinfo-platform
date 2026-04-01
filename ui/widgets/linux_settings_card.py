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
from ui.widgets.linux_settings_workers import (
    EnvBatchCheckWorker,
    RecoverInstallsWorker,
    ToolInstallBatchPollWorker,
    ToolInstallSubmitWorker,
    _format_rate,
    _normalize_env_paths,
    _safe_emit,
    _tool_env_exists_in_paths,
)
from ui.widgets.web_ui_host import create_local_web_ui_host
from ui.widgets.toast import Toast
from ui.workers.base_worker import launch_worker, request_worker_stop

from core.environment import env_detector
from core.environment import miniforge_bootstrap
from core.environment.env_installer import EnvInstaller, INSTALL_BASE as _INSTALL_BASE
from core.environment.env_batch_checker import get_existing_env_paths
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.utils import get_app_root

logger = logging.getLogger(__name__)
TOOL_INSTALL_POLL_INTERVAL_MS = 3000


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(LinuxSettingsMiniforgeMixin, QFrame):
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
        if not self._is_ssh_service_ready():
            self._set_status("SSH 未连接，无法安装", STATUS_ERROR)
            return False
        if self._miniforge_installing:
            self._set_status("运行环境正在初始化，请稍后再安装工具", STATUS_NEUTRAL)
            return False
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self._set_status("运行环境未就绪，请先完成初始化", STATUS_ERROR)
            return False
        return True

    def _queue_install_tool(self, tool: dict) -> None:
        """在当前事件结束后再打开安装对话框，避免 WebChannel 回调重入。"""
        tool_snapshot = dict(tool)
        QTimer.singleShot(0, lambda: self._do_install_tool(tool_snapshot))

    def _do_install_tool(self, tool: dict) -> None:
        """实际执行安装工具。"""
        tool_name = tool.get("name") or tool.get("id") or "未知工具"
        tool_id = str(tool.get("id", "") or "").strip()
        existing = self._get_tool_install_dialog(tool_id)
        if existing is not None:
            snapshot = self._get_or_create_tool_install_snapshot(tool_id)
            try:
                if snapshot:
                    existing.apply_install_snapshot(snapshot)
                self._activate_tool_install_dialog(existing)
                return
            except Exception:
                logger.exception("复用安装窗口失败，准备重建: tool=%s", tool_name)
                self._cleanup_tool_install_dialog(tool_id)

        dlg = None
        try:
            dlg = EnvInstallDialog(tool, conda_executable=self._conda_executable, parent=None)
        except Exception as exc:
            logger.exception("打开安装对话框失败: tool=%s", tool_name)
            self._set_status(f"打开安装窗口失败: {tool_name}", STATUS_ERROR)
            QMessageBox.critical(
                self,
                "安装窗口打开失败",
                f"工具【{tool_name}】的安装窗口打开失败。\n\n错误信息：{exc}",
            )
            return

        try:
            self._register_tool_install_dialog(tool_id, dlg)

            snapshot = self._get_or_create_tool_install_snapshot(tool_id)
            if snapshot:
                dlg.apply_install_snapshot(snapshot)
            self._activate_tool_install_dialog(dlg)
        except Exception as exc:
            logger.exception("安装对话框运行异常: tool=%s", tool_name)
            self._cleanup_tool_install_dialog(tool_id)
            active_install = tool_id in self._installing_tool_ids or tool_id in self._tool_install_submitting_ids
            if active_install:
                self._set_status(f"安装窗口异常关闭，后台任务仍在继续: {tool_name}", STATUS_NEUTRAL)
                message = (
                    f"工具【{tool_name}】的安装窗口运行异常，但后台安装任务仍会继续。\n\n"
                    f"错误信息：{exc}"
                )
            else:
                self._set_status(f"打开安装窗口失败: {tool_name}", STATUS_ERROR)
                message = f"工具【{tool_name}】的安装窗口打开失败。\n\n错误信息：{exc}"
            QMessageBox.critical(
                self,
                "安装窗口打开失败",
                message,
            )

    def _get_or_create_tool_install_snapshot(self, tool_id: str) -> dict:
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
        return snapshot

    def _get_tool_install_dialog(self, tool_id: str) -> Optional[EnvInstallDialog]:
        clean_tool_id = str(tool_id or "").strip()
        dialog = self._tool_install_dialogs.get(clean_tool_id)
        if dialog is None:
            return None
        try:
            dialog.isVisible()
        except RuntimeError:
            logger.exception("安装窗口实例已失效，正在重建: %s", clean_tool_id)
            self._cleanup_tool_install_dialog(clean_tool_id)
            return None
        return dialog

    def _register_tool_install_dialog(self, tool_id: str, dlg: EnvInstallDialog) -> None:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            raise RuntimeError("注册安装窗口失败：缺少 tool_id")
        self._tool_install_dialogs[clean_tool_id] = dlg
        dlg.install_requested.connect(self._on_dialog_install_requested)
        self.tool_install_snapshot_updated.connect(dlg.on_snapshot_updated)
        dlg.finished.connect(dlg.deleteLater)
        dlg.finished.connect(lambda _result, tool_id=clean_tool_id: self._on_tool_install_dialog_finished(tool_id))
        dlg.destroyed.connect(lambda _obj=None, tool_id=clean_tool_id: self._on_tool_install_dialog_destroyed(tool_id))

    def _activate_tool_install_dialog(self, dlg: EnvInstallDialog) -> None:
        try:
            if dlg.isMinimized():
                dlg.showNormal()
            else:
                dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except RuntimeError as exc:
            raise RuntimeError("激活安装窗口失败") from exc

    def _on_tool_install_dialog_finished(self, tool_id: str) -> None:
        self._cleanup_tool_install_dialog(tool_id)

    def _on_tool_install_dialog_destroyed(self, tool_id: str) -> None:
        self._tool_install_dialogs.pop(str(tool_id or "").strip(), None)

    def _cleanup_tool_install_dialog(self, tool_id: str) -> None:
        clean_tool_id = str(tool_id or "").strip()
        dialog = self._tool_install_dialogs.pop(clean_tool_id, None)
        if dialog is None:
            return
        try:
            dialog.install_requested.disconnect(self._on_dialog_install_requested)
        except (TypeError, RuntimeError):
            pass
        try:
            self.tool_install_snapshot_updated.disconnect(dialog.on_snapshot_updated)
        except (TypeError, RuntimeError):
            pass

    def _close_tool_install_dialogs(self) -> None:
        for tool_id, dialog in list(self._tool_install_dialogs.items()):
            self._cleanup_tool_install_dialog(tool_id)
            try:
                dialog.close()
            except RuntimeError:
                logger.debug("安装窗口已销毁，跳过关闭: %s", tool_id, exc_info=True)

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
            self._emit_install_task(
                build_tool_install_task_event(
                    clean_tool_id,
                    self._tool_display_name(clean_tool_id),
                    "failed",
                    "运行环境未就绪，无法安装",
                )
            )
            return

        tool = next((t for t in self._tools if t.get("id") == clean_tool_id), None)
        install_cmd = str((tool or {}).get("install_cmd", "") or "").strip()
        if not install_cmd:
            self._update_tool_install_snapshot(
                clean_tool_id,
                status="FAILED",
                message="该工具未配置 install_cmd，无法自动安装。",
            )
            self._emit_install_task(
                build_tool_install_task_event(
                    clean_tool_id,
                    self._tool_display_name(clean_tool_id),
                    "failed",
                    "该工具未配置 install_cmd",
                )
            )
            return

        self._start_tool_install_submit(clean_tool_id, install_cmd)

    def _start_tool_install_submit(self, tool_id: str, install_cmd: str) -> None:
        existing_thread = getattr(self, "_tool_install_submit_thread", None)
        if existing_thread is not None and existing_thread.isRunning():
            self._tool_install_submitting_ids.discard(tool_id)
            self._update_tool_install_snapshot(
                tool_id,
                status="FAILED",
                message="已有安装提交任务在执行，请稍候重试。",
            )
            self._emit_install_task(
                build_tool_install_task_event(
                    tool_id,
                    self._tool_display_name(tool_id),
                    "failed",
                    "已有安装提交任务在执行，请稍候重试。",
                )
            )
            return
        self._tool_install_submitting_ids.add(tool_id)
        self._update_tool_install_snapshot(
            tool_id,
            status="SUBMITTING",
            message="正在提交后台安装任务……",
        )
        self._emit_install_task(
            build_tool_install_task_event(
                tool_id,
                self._tool_display_name(tool_id),
                "running",
                "正在提交安装任务",
            )
        )

        launch_worker(
            self,
            "_tool_install_submit_thread",
            "_tool_install_submit_worker",
            ToolInstallSubmitWorker(
                self._make_ssh_run_fn(),
                tool_id,
                install_cmd,
                self._conda_executable,
            ),
            on_finished=self._on_tool_install_submit_finished,
            on_error=self._on_tool_install_submit_error,
        )

    def _on_tool_install_submit_finished(self, tool_id: str, result: dict) -> None:
        clean_tool_id = str(tool_id or "").strip()
        self._tool_install_submitting_ids.discard(clean_tool_id)

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
        self._installing_tool_ids.discard(clean_tool_id)
        self._tool_log_samples.pop(clean_tool_id, None)
        self._update_tool_install_snapshot(
            clean_tool_id,
            status="FAILED",
            message=f"启动安装失败: {message}",
        )
        if clean_tool_id:
            self._emit_install_task(
                build_tool_install_task_event(
                    clean_tool_id,
                    self._tool_display_name(clean_tool_id),
                    "failed",
                    f"提交安装失败: {message}",
                )
            )
        self._ensure_tool_install_polling()

    def _on_install_submitted(self, tool_id: str) -> None:
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._installing_tool_ids.add(tool_id)
        if self._bridge:
            self._bridge.emit_install_started(tool_id)
        self._emit_install_task(
            build_tool_install_task_event(
                tool_id,
                self._tool_display_name(tool_id),
                "running",
                "安装任务已提交，正在拉取进度",
            )
        )
        self._update_tool_install_snapshot(
            tool_id,
            status="RUNNING",
            message="安装中……（conda 安装可能需要 5-30 分钟，可关闭窗口后台继续）",
        )
        self._ensure_tool_install_polling()

    def _finalize_tool_install_state(self, tool_id: str, success: bool) -> None:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            return
        self._tool_install_submitting_ids.discard(clean_tool_id)
        self._installing_tool_ids.discard(clean_tool_id)
        self._tool_log_samples.pop(clean_tool_id, None)
        if self._bridge:
            self._bridge.emit_install_finished(clean_tool_id, success)
        self._ensure_tool_install_polling()

    def _on_install_succeeded(self, tool_id: str) -> None:
        """某工具安装成功后：提示数据库（如需要），然后重新检测。"""
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._finalize_tool_install_state(tool_id, success=True)
        self._emit_install_task(
            build_tool_install_task_event(
                tool_id,
                self._tool_display_name(tool_id),
                "success",
                "工具环境安装完成",
            )
        )
        self._update_tool_install_snapshot(
            tool_id,
            status="DONE",
            message="安装成功！",
        )

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
        QTimer.singleShot(300, self._do_batch_check)

    def _on_install_failed(self, tool_id: str) -> None:
        """安装失败后通知 JS 更新状态。"""
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return
        self._finalize_tool_install_state(tool_id, success=False)
        self._emit_install_task(
            build_tool_install_task_event(
                tool_id,
                self._tool_display_name(tool_id),
                "failed",
                "工具环境安装失败",
            )
        )
        self._update_tool_install_snapshot(
            tool_id,
            status="FAILED",
            message="安装失败，请检查上方输出或网络后重试。",
        )

    def _start_recover_installs_job(self, existing_env_paths: Optional[set[str]] = None) -> None:
        launch_worker(
            self,
            "_recover_installs_thread",
            "_recover_installs_worker",
            RecoverInstallsWorker(
                self._make_ssh_run_fn(),
                self._tools,
                self._conda_executable,
                existing_env_paths=existing_env_paths,
            ),
            on_finished=self._on_recover_installs_finished,
            on_error=self._on_recover_installs_error,
        )

    def _recover_running_installs(self, existing_env_paths: Optional[set[str]] = None) -> None:
        """启动时扫描 ~/.h2ometa/env_installs/*/status.txt，恢复安装状态。

        - RUNNING → 恢复为“安装中”并继续轮询
        - DONE    → 静默清理并触发一次重检（不写入安装任务面板）
        - FAILED  → 保留诊断目录，不在启动时写入安装任务面板
        """
        if not self._is_ssh_service_ready():
            return
        if self._recover_installs_running:
            return
        self._recover_installs_running = True
        self._start_recover_installs_job(existing_env_paths=existing_env_paths)

    def _on_recover_installs_finished(self, payload: object) -> None:
        self._recover_installs_running = False
        data = payload if isinstance(payload, dict) else {}
        rows = list(data.get("rows", []) or [])
        existing_env_paths = _normalize_env_paths(data.get("existing_env_paths", []))
        running_tools = []
        newly_done = False
        logger.debug("恢复安装状态完成: install_count=%d env_count=%d", len(rows), len(existing_env_paths))

        for item in rows:
            tool_id = str(item.get("tool_id", "") or "").strip()
            status = str(item.get("status", "") or "").strip().upper()
            task_dir = str(item.get("task_dir", "") or "").strip()
            env_exists = bool(item.get("env_exists", False))
            session_alive = bool(item.get("session_alive", False))
            if not tool_id:
                continue

            if status == "RUNNING":
                tool = next((t for t in self._tools if t["id"] == tool_id), None)
                if tool and (env_exists or self._is_tool_env_exists(tool, existing_env_paths)):
                    logger.info("工具 %s 状态为 RUNNING 但环境已存在，视为安装完成", tool_id)
                    newly_done = True
                    self._update_tool_install_snapshot(
                        tool_id,
                        status="DONE",
                        task_dir=task_dir,
                        message="检测到环境已就绪，安装视为完成。",
                    )
                elif session_alive:
                    running_tools.append(tool_id)
                    self._installing_tool_ids.add(tool_id)
                    self._update_tool_install_snapshot(
                        tool_id,
                        status="RUNNING",
                        task_dir=task_dir,
                        message="检测到后台安装任务仍在运行",
                    )
                    if self._bridge:
                        self._bridge.emit_install_started(tool_id)
                    self._emit_install_task(
                        build_tool_install_task_event(
                            tool_id,
                            self._tool_display_name(tool_id),
                            "running",
                            "检测到后台安装任务仍在运行",
                        )
                    )
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
            elif status == "DONE":
                newly_done = True
                self._update_tool_install_snapshot(
                    tool_id,
                    status="DONE",
                    task_dir=task_dir,
                    message="安装任务已完成。",
                )
                logger.info("发现已完成的后台安装任务，静默清理: %s", tool_id)
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
            self._ensure_tool_install_polling()

        if newly_done:
            QTimer.singleShot(500, self._do_batch_check)

    def _on_recover_installs_error(self, msg: str) -> None:
        self._recover_installs_running = False
        logger.debug("恢复后台安装状态失败: %s", msg)

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

    def _poll_running_tool_installs(self) -> None:
        if not self._installing_tool_ids:
            self._ensure_tool_install_polling()
            return
        if self._tool_install_polling:
            return
        if not self._is_ssh_service_ready():
            return

        self._tool_install_polling = True
        launch_worker(
            self,
            "_tool_install_poll_thread",
            "_tool_install_poll_worker",
            ToolInstallBatchPollWorker(
                self._make_ssh_run_fn(),
                sorted(self._installing_tool_ids),
            ),
            on_finished=self._on_tool_install_poll_finished,
            on_error=self._on_tool_install_poll_error,
        )

    def _build_tool_install_running_message(self, tool_id: str, log_text: str, log_size: int) -> str:
        progress, speed = extract_progress_and_speed(log_text)
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
                logger.info("工具 %s 安装会话已退出且状态不可靠，静默回缺失", tool_id)
                self._installing_tool_ids.discard(tool_id)
                self._tool_log_samples.pop(tool_id, None)
                if self._bridge:
                    self._bridge.emit_install_finished(tool_id, False)
                self._update_tool_install_snapshot(
                    tool_id,
                    status="FAILED",
                    task_dir=f"{_INSTALL_BASE}/{tool_id}",
                    message="安装会话已退出且状态不可靠，请重试安装。",
                )
                need_recheck = True
                continue

            message = self._build_tool_install_running_message(
                tool_id,
                log_text,
                log_size,
            )
            progress_text, speed_text = extract_progress_and_speed(message)
            self._update_tool_install_snapshot(
                tool_id,
                status="RUNNING",
                log_text=log_text,
                log_size=max(log_size, 0),
                message=message,
            )
            self._emit_install_task(
                build_tool_install_task_event(
                    tool_id,
                    self._tool_display_name(tool_id),
                    "running",
                    message,
                    progress_text=progress_text,
                    speed_text=speed_text,
                )
            )

        if need_recheck:
            QTimer.singleShot(300, self._do_batch_check)
        self._ensure_tool_install_polling()

    def _on_tool_install_poll_error(self, msg: str) -> None:
        self._tool_install_polling = False
        logger.debug("轮询工具安装状态失败: %s", msg)
        self._ensure_tool_install_polling()

    def _get_existing_env_paths(self) -> set[str]:
        """获取远端所有已存在的 conda 环境路径集合。"""
        assert not QThread.isMainThread(), (
            "_get_existing_env_paths() performs SSH and must not run on the main thread"
        )
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
        return _tool_env_exists_in_paths(tool, existing_env_paths, self._conda_executable)

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
