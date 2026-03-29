from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
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
from ui.controllers.install_workflow import InstallWorkflowPresenter, InstallWorkflowStore
from ui.widgets.linux_settings_components import ClickableHeader, EnvInstallDialog, ToolEnvBridge
from ui.widgets.web_ui_host import create_local_web_ui_host
from ui.widgets.toast import Toast
from ui.workers.base_worker import BaseCancellableWorker, launch_worker, request_worker_stop

from core.environment import env_detector
from core.environment import miniforge_bootstrap
from core.environment.env_installer import EnvInstaller, INSTALL_BASE as _INSTALL_BASE
from core.environment.env_batch_checker import ToolCheckResult, check_all_envs, get_existing_env_paths
from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.remote.server_capabilities import ServerCapabilities
from core.utils import get_app_root

logger = logging.getLogger(__name__)
MINIFORGE_HEARTBEAT_STALE_SECONDS = 180
TOOL_INSTALL_POLL_INTERVAL_MS = 3000
MINIFORGE_PROBE_COMMAND = "test -f ~/.h2ometa/conda/bin/conda && echo OK || echo MISSING"


def _format_rate(bps: float) -> str:
    if bps >= 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024 * 1024):.1f}GB/s"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f}MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    return f"{max(bps, 0):.0f}B/s"


def _is_test_mode() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


def _safe_emit(signal, *args) -> bool:
    try:
        signal.emit(*args)
        return True
    except RuntimeError:
        logger.debug("Skipped signal emit on deleted Qt object", exc_info=True)
        return False


def _normalize_env_paths(paths) -> set[str]:
    return {str(path).rstrip("/") for path in (paths or []) if str(path).strip()}


def _tool_env_exists_in_paths(tool: dict | None, existing_env_paths: set[str], conda_executable: str = "") -> bool:
    tool = tool or {}
    conda_env = str(tool.get("conda_env", "") or "").strip()
    if not conda_env:
        return True

    normalized_paths = _normalize_env_paths(existing_env_paths)
    env_names = {path.split("/")[-1] for path in normalized_paths}
    if conda_env in env_names:
        return True

    expected_path = env_detector.expected_env_path(conda_executable, conda_env)
    if expected_path and "~" not in expected_path:
        return expected_path.rstrip("/") in normalized_paths
    return False

# ── Conda 检测 Worker ─────────────────────────────────────────────


class MiniforgeProbeWorker(BaseCancellableWorker):
    """在 QThread 中探测自管 Miniforge 是否已落盘。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn

    @pyqtSlot()
    def run(self):
        try:
            rc, out, err = self._ssh_run_fn(MINIFORGE_PROBE_COMMAND, timeout=10)
            status = str(out or "").strip()
            if rc != 0 or status not in {"OK", "MISSING"}:
                raise RuntimeError(
                    f"Miniforge probe failed: rc={rc}, out={status!r}, err={str(err or '').strip()!r}"
                )
            self._emit(
                "finished",
                {
                    "command": MINIFORGE_PROBE_COMMAND,
                    "status": status,
                    "deployed": status == "OK",
                },
            )
        except Exception as e:
            if self._cancelled:
                return
            logger.exception("MiniforgeProbeWorker 出错")
            self._emit("error", str(e))


class MiniforgeBootstrapSubmitWorker(BaseCancellableWorker):
    """在 QThread 中提交 detached Miniforge 初始化任务。"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, caps: ServerCapabilities):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._caps = caps

    @pyqtSlot()
    def run(self):
        if self._cancelled:
            return
        try:
            result = miniforge_bootstrap.submit(self._caps, self._ssh_run_fn)
            if self._cancelled:
                return
            self._emit("finished", result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("提交 Miniforge 后台任务失败")
            self._emit("error", str(exc))


class MiniforgePollWorker(BaseCancellableWorker):
    """后台探测 Miniforge 状态或读取失败日志，避免主线程同步 SSH。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, ssh_run_fn, task_dir: str, operation: str, reason: str = ""):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._task_dir = str(task_dir or miniforge_bootstrap.TASK_DIR)
        self._operation = str(operation or "").strip()
        self._reason = str(reason or "")

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._operation == "probe_status":
                status = miniforge_bootstrap.check_status(
                    self._ssh_run_fn,
                    task_dir=self._task_dir,
                    timeout=10,
                )
                alive = miniforge_bootstrap.is_session_alive(
                    self._ssh_run_fn,
                    job_id=miniforge_bootstrap.JOB_ID,
                    timeout=10,
                )
                payload = {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "status": str(status.get("status", "") or ""),
                    "exit_code": str(status.get("exit_code", "") or ""),
                    "heartbeat": str(status.get("heartbeat", "") or ""),
                    "session_alive": bool(alive),
                }
            elif self._operation == "read_failure_log":
                log_text = miniforge_bootstrap.read_log(
                    self._ssh_run_fn,
                    task_dir=self._task_dir,
                    tail_lines=40,
                    timeout=10,
                )
                payload = {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "reason": self._reason,
                    "log_text": str(log_text or ""),
                }
            else:
                raise RuntimeError(f"Unsupported Miniforge poll operation: {self._operation}")

            self._emit("finished", payload)
        except Exception as exc:
            logger.exception("MiniforgePollWorker 出错: operation=%s", self._operation)
            self._emit(
                "error",
                {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "reason": self._reason,
                    "error": str(exc),
                },
            )


# ── 批量环境检测 Worker ─────────────────────────────────────────────


class EnvBatchCheckWorker(BaseCancellableWorker):
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


class ToolInstallBatchPollWorker(BaseCancellableWorker):
    """批量轮询工具环境安装状态（后台线程）。"""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, tool_ids: list[str]):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_ids = list(tool_ids)

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
                self._emit("finished", rows)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallBatchPollWorker 出错")
            self._emit("error", str(exc))


class ToolInstallSubmitWorker(BaseCancellableWorker):
    """后台提交工具环境安装任务。"""

    finished = pyqtSignal(str, dict)
    error = pyqtSignal(str, str)

    def __init__(self, ssh_run_fn, tool_id: str, install_cmd: str, conda_executable: str):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_id = str(tool_id or "").strip()
        self._install_cmd = str(install_cmd or "")
        self._conda_executable = str(conda_executable or "")

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
                self._emit("finished", self._tool_id, result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallSubmitWorker 出错: tool_id=%s", self._tool_id)
            self._emit("error", self._tool_id, str(exc))


class RecoverInstallsWorker(BaseCancellableWorker):
    """后台恢复/解析工具安装状态，避免主线程同步 SSH。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        ssh_run_fn,
        tools: list[dict],
        conda_executable: str = "",
        existing_env_paths=None,
    ):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tools = list(tools or [])
        self._conda_executable = str(conda_executable or "")
        self._existing_env_paths = None if existing_env_paths is None else _normalize_env_paths(existing_env_paths)

    def _load_existing_env_paths(self) -> set[str]:
        if self._existing_env_paths is not None:
            return set(self._existing_env_paths)
        return _normalize_env_paths(
            get_existing_env_paths(
                ssh_run_fn=self._ssh_run_fn,
                conda_executable=self._conda_executable,
            )
        )

    def _run_recover_scan(self, existing_env_paths: set[str], tool_map: dict[str, dict]) -> list[dict]:
        installs = EnvInstaller.scan_running(self._ssh_run_fn)
        rows: list[dict] = []
        for item in installs:
            if self._cancelled:
                return []
            tool_id = str(item.get("tool_id", "") or "").strip()
            status = str(item.get("status", "") or "").strip().upper()
            task_dir = str(item.get("task_dir", "") or "").strip()
            tool = tool_map.get(tool_id)
            env_exists = False
            session_alive = False
            cleanup_attempted = False

            if status == "RUNNING":
                env_exists = _tool_env_exists_in_paths(tool, existing_env_paths, self._conda_executable)
                if not env_exists:
                    session_alive = EnvInstaller.is_session_alive(
                        self._ssh_run_fn,
                        f"h2o_install_{tool_id}",
                        timeout=10,
                    )
                    if not session_alive:
                        cleanup_attempted = True
                        try:
                            EnvInstaller.cleanup(self._ssh_run_fn, task_dir)
                        except Exception:
                            logger.debug("恢复阶段清理任务目录失败: %s", task_dir, exc_info=True)
            elif status == "DONE":
                cleanup_attempted = True
                try:
                    EnvInstaller.cleanup(self._ssh_run_fn, task_dir)
                except Exception:
                    logger.debug("恢复阶段清理已完成任务失败: %s", task_dir, exc_info=True)

            rows.append(
                {
                    "tool_id": tool_id,
                    "task_dir": task_dir,
                    "status": status,
                    "env_exists": env_exists,
                    "session_alive": session_alive,
                    "cleanup_attempted": cleanup_attempted,
                }
            )
        return rows

    @pyqtSlot()
    def run(self) -> None:
        try:
            existing_env_paths = self._load_existing_env_paths()
            if self._cancelled:
                return

            tool_map = {str(tool.get("id", "") or "").strip(): dict(tool) for tool in self._tools}
            rows = self._run_recover_scan(existing_env_paths, tool_map)
            if self._cancelled:
                return

            self._emit(
                "finished",
                {
                    "rows": rows,
                    "existing_env_paths": sorted(existing_env_paths),
                },
            )
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("RecoverInstallsWorker 出错")
            self._emit("error", str(exc))


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
      conda_executable
    """

    request_save = pyqtSignal()
    install_task_event = pyqtSignal(dict)
    tool_install_snapshot_updated = pyqtSignal(str, dict)
    deploy_state_changed = pyqtSignal(dict)

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
        self._workflow_presenter = InstallWorkflowPresenter()
        self._tool_install_snapshots = self._workflow_store._tool_snapshots
        self._tool_install_submitting_ids: set[str] = set()
        self._tool_install_submit_threads: dict[str, QThread] = {}
        self._tool_install_submit_workers: dict[str, ToolInstallSubmitWorker] = {}
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

    def _emit_install_task_event(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        state: str,
        detail: str = "",
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> None:
        payload = self._workflow_presenter.build_task_event(
            task_id=task_id,
            title=title,
            source=source,
            state=state,
            detail=detail,
            message=message,
            progress_text=progress_text,
            speed_text=speed_text,
            location_hint=location_hint,
        )
        if not payload["task_id"] or not payload["title"]:
            return
        try:
            self.install_task_event.emit(payload)
        except RuntimeError:
            logger.debug("install_task_event emit skipped on deleted card", exc_info=True)

    def _emit_bootstrap_install_event(self, state: str, detail: str = "") -> None:
        payload = self._workflow_presenter.build_bootstrap_task_event(state, detail)
        try:
            self.install_task_event.emit(payload)
        except RuntimeError:
            logger.debug("install_task_event emit skipped on deleted card", exc_info=True)

    def _emit_tool_install_event(
        self,
        tool_id: str,
        state: str,
        detail: str = "",
        *,
        progress_text: str = "",
        speed_text: str = "",
    ) -> None:
        tool = next((t for t in self._tools if t.get("id") == tool_id), None)
        tool_name = str((tool or {}).get("name", "") or tool_id).strip() or tool_id
        payload = self._workflow_presenter.build_tool_install_task_event(
            tool_id,
            tool_name,
            state,
            detail,
            progress_text=progress_text,
            speed_text=speed_text,
        )
        try:
            self.install_task_event.emit(payload)
        except RuntimeError:
            logger.debug("install_task_event emit skipped on deleted card", exc_info=True)

    def _get_tool_install_snapshot(self, tool_id: str) -> dict:
        return self._workflow_store.get_tool_snapshot(tool_id)

    def _update_tool_install_snapshot(self, tool_id: str, **updates) -> dict:
        current = self._workflow_store.update_tool_snapshot(tool_id, **updates)
        clean_tool_id = str(current.get("tool_id", "") or "").strip()
        if not clean_tool_id:
            return {}
        _safe_emit(self.tool_install_snapshot_updated, clean_tool_id, dict(current))
        return dict(current)

    def set_active_client(self, client) -> None:
        """接收连接状态变化信号，触发后续检测流程。"""
        if client is not None and self._is_ssh_service_ready():
            self._set_status("SSH 已就绪，正在检查运行环境...")
            self._schedule_miniforge_probe(200)
        elif client is not None:
            self._set_status("SSH 已连接，正在等待服务通道就绪")
        else:
            self._reset_miniforge_probe_state(clear_conda=True)
            self._set_status("等待 SSH 连接")

    def set_ssh_service(self, ssh_service) -> None:
        """注入统一 SSHService，优先使用其串行 run 通道。"""
        service_changed = ssh_service is not self._ssh_service
        self._ssh_service = ssh_service
        if service_changed and not self._miniforge_installing:
            self._reset_miniforge_probe_state(clear_conda=True)
        if self._is_ssh_service_ready():
            if self._miniforge_installing:
                self._emit_deploy_state()
                self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
                self._schedule_miniforge_poll(200)
                return
            self._set_status("SSH 已就绪，正在检查运行环境...")
            self._schedule_miniforge_probe(200)
        else:
            self._reset_miniforge_probe_state(clear_conda=True)

    def _is_ssh_service_ready(self) -> bool:
        return self._ssh_service is not None and bool(getattr(self._ssh_service, "is_connected", False))

    def get_values(self) -> dict:
        """供 SettingsPage 获取数据。"""
        return {
            "conda_executable": self._conda_executable,
        }

    def set_values(
        self,
        conda_executable: str = "",
    ) -> None:
        """供 SettingsPage 回填数据。"""
        if conda_executable and not is_managed_conda_executable(conda_executable):
            logger.warning("忽略非自管 conda 配置路径: %s", conda_executable)
            self._conda_executable = ""
        else:
            self._conda_executable = conda_executable
            self._miniforge_deployed = bool(conda_executable)
        self._emit_deploy_state()

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在 SSH 连接被占用时禁用交互。"""
        if self._external_lock == locked:
            return
        self._external_lock = locked

    def start_deploy(self) -> None:
        if not self._is_ssh_service_ready():
            self._set_status("SSH 未连接，无法部署运行环境", STATUS_ERROR)
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_deploy_state()
            return
        if self._miniforge_deployed:
            self._set_status("运行环境已就绪", STATUS_SUCCESS)
            self._emit_deploy_state()
            return
        self._start_miniforge_install_silent()

    def _sync_locator_conda_executable(self) -> None:
        window = self.window()
        locator = getattr(window, "service_locator", None)
        if locator is not None and hasattr(locator, "conda_executable"):
            locator.conda_executable = self._conda_executable

    def _emit_deploy_state(self) -> None:
        if not self._is_ssh_service_ready():
            state = "hidden"
        elif self._miniforge_installing:
            state = "deploying"
        elif self._miniforge_probe_inflight and not self._miniforge_probe_completed:
            state = "checking"
        elif self._miniforge_deployed:
            state = "ready"
        else:
            state = "missing"
        _safe_emit(
            self.deploy_state_changed,
            {
                "state": state,
                "deployed": self._miniforge_deployed,
                "deploying": self._miniforge_installing,
                "checking": self._miniforge_probe_inflight and not self._miniforge_probe_completed,
            },
        )

    def _reset_miniforge_probe_state(self, *, clear_conda: bool) -> None:
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = False
        self._miniforge_deployed = False
        if clear_conda:
            self._conda_executable = ""
            self._sync_locator_conda_executable()
        self._emit_deploy_state()

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

    def _schedule_miniforge_probe(self, delay_ms: int = 200) -> None:
        if _is_test_mode():
            return
        if not self._is_ssh_service_ready():
            return
        if self._miniforge_installing or self._miniforge_probe_inflight or self._miniforge_probe_completed:
            self._emit_deploy_state()
            return
        QTimer.singleShot(max(int(delay_ms), 0), self._check_miniforge_exists)

    def _check_miniforge_exists(self) -> None:
        if _is_test_mode():
            return
        if not self._is_ssh_service_ready() or self._external_lock:
            return
        if self._miniforge_installing or self._miniforge_probe_inflight or self._miniforge_probe_completed:
            self._emit_deploy_state()
            return

        self._miniforge_probe_inflight = True
        self._emit_deploy_state()
        launch_worker(
            self,
            "_miniforge_probe_thread",
            "_miniforge_probe_worker",
            MiniforgeProbeWorker(self._make_ssh_run_fn()),
            on_finished=self._on_miniforge_probe_finished,
            on_error=self._on_miniforge_probe_error,
        )

    def _on_miniforge_probe_finished(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        deployed = bool(data.get("deployed", False))
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = True
        self._miniforge_deployed = deployed
        self._conda_executable = H2O_CONDA_EXE if deployed else ""
        self._sync_locator_conda_executable()
        self.request_save.emit()
        if deployed:
            self._set_status("运行环境已就绪", STATUS_SUCCESS)
        else:
            self._set_status("运行环境未部署，请先点击“一键部署运行环境”", STATUS_NEUTRAL)
        self._emit_deploy_state()

    def _on_miniforge_probe_error(self, msg: str) -> None:
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = False
        self._miniforge_deployed = False
        self._conda_executable = ""
        self._sync_locator_conda_executable()
        self.request_save.emit()
        self._set_status(f"运行环境检查失败: {msg[:60]}", STATUS_ERROR)
        self._emit_deploy_state()

    def _cleanup_miniforge_resources(self) -> None:
        """清理 Miniforge 提交/轮询线程资源。"""
        request_worker_stop(self, "_miniforge_thread", "_miniforge_worker")
        request_worker_stop(self, "_miniforge_poll_thread", "_miniforge_poll_worker")
        request_worker_stop(self, "_miniforge_probe_thread", "_miniforge_probe_worker")

    def _get_server_capabilities(self) -> tuple[ServerCapabilities | None, str]:
        window = self.window()
        locator = getattr(window, "service_locator", None)
        if locator is None:
            return None, "未找到运行时服务上下文"
        caps = getattr(locator, "server_capabilities", None)
        error = str(getattr(locator, "server_capability_error", "") or "")
        if isinstance(caps, ServerCapabilities):
            return caps, error
        return None, error

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
        if not self._is_ssh_service_ready():
            return
        caps, preflight_error = self._get_server_capabilities()
        if caps is None:
            message = preflight_error or "服务器预检尚未完成，请稍后重试。"
            self._set_status(message[:60], STATUS_ERROR)
            self._emit_bootstrap_install_event("failed", message)
            self._prompt_miniforge_install_failed(message)
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_bootstrap_install_event("running", "运行环境初始化进行中")
            self._emit_deploy_state()
            return

        self._miniforge_installing = True
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = True
        self._miniforge_deployed = False
        self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
        self._emit_bootstrap_install_event("running", "后台提交初始化任务")
        self._emit_deploy_state()
        self._cleanup_miniforge_resources()

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
            self._emit_deploy_state()
            self._set_status("运行环境初始化失败，请重试安装", STATUS_ERROR)
            self._emit_bootstrap_install_event("failed", f"提交失败: {msg}")
            self._prompt_miniforge_install_failed(msg)
            self._cleanup_miniforge_resources()

        launch_worker(
            self,
            "_miniforge_thread",
            "_miniforge_worker",
            MiniforgeBootstrapSubmitWorker(self._make_ssh_run_fn(), caps),
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _start_miniforge_polling(self) -> None:
        self._schedule_miniforge_poll(100)

    def _schedule_miniforge_poll(self, delay_ms: int = 3000) -> None:
        if not self._miniforge_installing:
            return
        self._miniforge_poll_timer.stop()
        self._miniforge_poll_timer.start(max(int(delay_ms), 0))

    def _start_miniforge_poll_job(self, operation: str, reason: str = "") -> None:
        launch_worker(
            self,
            "_miniforge_poll_thread",
            "_miniforge_poll_worker",
            MiniforgePollWorker(
                self._make_ssh_run_fn(),
                self._miniforge_task_dir,
                operation=operation,
                reason=reason,
            ),
            on_finished=self._on_miniforge_poll_finished,
            on_error=self._on_miniforge_poll_error,
        )

    def _poll_miniforge_status(self) -> None:
        if not self._miniforge_installing or self._miniforge_polling:
            return
        if not self._is_ssh_service_ready():
            return
        self._miniforge_polling = True
        self._start_miniforge_poll_job("probe_status")

    def _on_miniforge_poll_finished(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        operation = str(data.get("operation", "") or "").strip()
        self._miniforge_polling = False
        if operation == "read_failure_log":
            self._on_miniforge_failure_log_finished(data)
            return

        state = str(data.get("status", "") or "").strip().upper()
        rc = str(data.get("exit_code", "") or "").strip()
        heartbeat = str(data.get("heartbeat", "") or "").strip()
        alive = bool(data.get("session_alive", False))

        if state == "DONE" or rc == "0":
            self._miniforge_installing = False
            self._miniforge_poll_timer.stop()
            self._miniforge_probe_inflight = False
            self._miniforge_probe_completed = True
            self._miniforge_deployed = True
            self._conda_executable = H2O_CONDA_EXE
            self._sync_locator_conda_executable()
            self.request_save.emit()
            self._emit_deploy_state()
            self._set_status("运行环境已就绪，正在检测工具环境...", STATUS_SUCCESS)
            self._emit_bootstrap_install_event("success", "运行环境初始化完成")
            Toast.show_toast(self, "运行环境初始化完成", level="success", duration_ms=3000)
            if self._tools:
                self._pending_recover_after_batch = True
                QTimer.singleShot(200, self._do_batch_check)
            else:
                self._pending_recover_after_batch = False
                QTimer.singleShot(200, lambda: self._recover_running_installs(existing_env_paths=set()))
            return

        if state == "FAILED":
            self._handle_miniforge_failure("远端初始化任务失败")
            return

        if state == "RUNNING" and not alive and self._is_stale_heartbeat(heartbeat):
            self._handle_miniforge_failure("远端会话已退出（状态仍为 RUNNING 且心跳超时）")
            return

        if not alive and (state == "" or self._is_stale_heartbeat(heartbeat)):
            self._handle_miniforge_failure("远端会话已退出且心跳超时")
            return

        self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
        self._emit_bootstrap_install_event("running", "后台初始化任务执行中")
        self._schedule_miniforge_poll(3000)

    def _on_miniforge_poll_error(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        operation = str(data.get("operation", "") or "").strip()
        self._miniforge_polling = False
        if operation == "read_failure_log":
            self._on_miniforge_failure_log_error(data)
            return
        logger.debug("轮询 Miniforge 初始化状态失败: %s", data.get("error", ""))
        if self._miniforge_installing:
            self._schedule_miniforge_poll(3000)

    def _is_stale_heartbeat(self, heartbeat_value: str, stale_seconds: int = MINIFORGE_HEARTBEAT_STALE_SECONDS) -> bool:
        try:
            ts = int((heartbeat_value or "").strip())
        except Exception:
            return True
        return (time.time() - ts) > stale_seconds

    def _handle_miniforge_failure(self, reason: str) -> None:
        self._miniforge_installing = False
        self._miniforge_poll_timer.stop()
        self._miniforge_polling = False
        self._miniforge_deployed = False
        self._conda_executable = ""
        self._sync_locator_conda_executable()
        self.request_save.emit()
        self._emit_deploy_state()
        self._set_status("运行环境初始化失败，请重试安装", STATUS_ERROR)
        self._emit_bootstrap_install_event("failed", reason)
        self._start_miniforge_poll_job("read_failure_log", reason=reason)

    def _on_miniforge_failure_log_finished(self, payload: dict) -> None:
        reason = str(payload.get("reason", "") or "").strip()
        log_text = str(payload.get("log_text", "") or "")
        tail = log_text.strip()
        message = f"{reason}\n\n{tail}" if tail else reason
        self._prompt_miniforge_install_failed(message)

    def _on_miniforge_failure_log_error(self, payload: dict) -> None:
        reason = str(payload.get("reason", "") or "").strip() or "运行环境初始化失败"
        logger.debug("读取 Miniforge 失败日志失败: %s", payload.get("error", ""))
        self._prompt_miniforge_install_failed(reason)

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
        self._emit_tool_install_event(tool_id, "success", "工具环境安装完成")
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
        self._emit_tool_install_event(tool_id, "failed", "工具环境安装失败")
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
                    self._emit_tool_install_event(tool_id, "running", "检测到后台安装任务仍在运行")
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

    def _build_tool_install_running_detail(self, tool_id: str, log_text: str, log_size: int) -> str:
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

            detail = self._build_tool_install_running_detail(
                tool_id,
                log_text,
                log_size,
            )
            progress_text, speed_text = extract_progress_and_speed(detail)
            self._update_tool_install_snapshot(
                tool_id,
                status="RUNNING",
                log_text=log_text,
                log_size=max(log_size, 0),
                message=detail,
            )
            self._emit_tool_install_event(
                tool_id,
                "running",
                detail,
                progress_text=progress_text,
                speed_text=speed_text,
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
        self._cleanup_tool_install_submit_resources()
        request_worker_stop(self, "_check_thread", "_check_worker")
        self._cleanup_miniforge_resources()
        request_worker_stop(self, "_recover_installs_thread", "_recover_installs_worker")
        request_worker_stop(self, "_tool_install_poll_thread", "_tool_install_poll_worker")
        super().closeEvent(event)
