from __future__ import annotations

import logging
import os
import sys
import time

from PyQt6.QtCore import QTimer

from ui.controllers.install_workflow import build_bootstrap_task_event
from ui.widgets.linux_settings_workers import (
    MiniforgeBootstrapSubmitWorker,
    MiniforgePollWorker,
    MiniforgeProbeWorker,
)
from ui.widgets.toast import Toast
from ui.workers.base_worker import launch_worker, request_worker_stop

from core.environment import miniforge_bootstrap
from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.remote.server_capabilities import ServerCapabilities

logger = logging.getLogger(__name__)
MINIFORGE_HEARTBEAT_STALE_SECONDS = 180


def _is_test_mode() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


class LinuxSettingsMiniforgeMixin:
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

    def get_values(self) -> dict:
        return {
            "conda_executable": self._conda_executable,
        }

    def set_values(self, conda_executable: str = "") -> None:
        if conda_executable and not is_managed_conda_executable(conda_executable):
            logger.warning("忽略非自管 conda 配置路径: %s", conda_executable)
            self._conda_executable = ""
        else:
            self._conda_executable = conda_executable
            self._miniforge_deployed = bool(conda_executable)
        self._emit_deploy_state()

    def start_deploy(self) -> None:
        if not self._is_ssh_service_ready():
            self._set_status("SSH 未连接，无法部署运行环境", self.STATUS_ERROR)
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_deploy_state()
            return
        if self._miniforge_deployed:
            self._set_status("运行环境已就绪", self.STATUS_SUCCESS)
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
        self.deploy_state_changed.emit(
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
            self._set_status("运行环境已就绪", self.STATUS_SUCCESS)
        else:
            self._set_status("运行环境未部署，请先点击“一键部署运行环境”", self.STATUS_NEUTRAL)
        self._emit_deploy_state()

    def _on_miniforge_probe_error(self, msg: str) -> None:
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = False
        self._miniforge_deployed = False
        self._conda_executable = ""
        self._sync_locator_conda_executable()
        self.request_save.emit()
        self._set_status(f"运行环境检查失败: {msg[:60]}", self.STATUS_ERROR)
        self._emit_deploy_state()

    def _cleanup_miniforge_resources(self) -> None:
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
        if not self._is_ssh_service_ready():
            return
        caps, preflight_error = self._get_server_capabilities()
        if caps is None:
            message = preflight_error or "服务器预检尚未完成，请稍后重试。"
            self._set_status(message[:60], self.STATUS_ERROR)
            self._emit_install_task(build_bootstrap_task_event("failed", message))
            self._prompt_miniforge_install_failed(message)
            return
        if self._miniforge_installing:
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._emit_install_task(
                build_bootstrap_task_event("running", "运行环境初始化进行中")
            )
            self._emit_deploy_state()
            return

        self._miniforge_installing = True
        self._miniforge_probe_inflight = False
        self._miniforge_probe_completed = True
        self._miniforge_deployed = False
        self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
        self._emit_install_task(
            build_bootstrap_task_event("running", "后台提交初始化任务")
        )
        self._emit_deploy_state()
        self._cleanup_miniforge_resources()

        def _on_finished(result: dict) -> None:
            self._miniforge_task_dir = result.get("task_dir", miniforge_bootstrap.TASK_DIR)
            already_running = bool(result.get("already_running", False))
            message = "已接管后台运行中的初始化任务" if already_running else "初始化任务已提交到后台"
            self._emit_install_task(build_bootstrap_task_event("running", message))
            self._set_status("正在初始化运行环境（首次启动约 1-2 分钟）...")
            self._start_miniforge_polling()
            self._cleanup_miniforge_resources()

        def _on_error(msg: str) -> None:
            self._miniforge_installing = False
            self._emit_deploy_state()
            self._set_status("运行环境初始化失败，请重试安装", self.STATUS_ERROR)
            self._emit_install_task(build_bootstrap_task_event("failed", f"提交失败: {msg}"))
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
            self._set_status("运行环境已就绪，正在检测工具环境...", self.STATUS_SUCCESS)
            self._emit_install_task(
                build_bootstrap_task_event("success", "运行环境初始化完成")
            )
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
        self._emit_install_task(
            build_bootstrap_task_event("running", "后台初始化任务执行中")
        )
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

    def _is_stale_heartbeat(
        self,
        heartbeat_value: str,
        stale_seconds: int = MINIFORGE_HEARTBEAT_STALE_SECONDS,
    ) -> bool:
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
        self._set_status("运行环境初始化失败，请重试安装", self.STATUS_ERROR)
        self._emit_install_task(build_bootstrap_task_event("failed", reason))
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
