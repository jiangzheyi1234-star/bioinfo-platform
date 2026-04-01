from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from ui.controllers.install_workflow import build_tool_install_task_event
from ui.install_log_parser import extract_progress_and_speed
from ui.widgets.linux_settings_components import EnvInstallDialog
from ui.widgets.linux_settings_workers import (
    RecoverInstallsWorker,
    ToolInstallBatchPollWorker,
    ToolInstallSubmitWorker,
    _format_rate,
    _normalize_env_paths,
    _tool_env_exists_in_paths,
)
from ui.widgets.toast import Toast
from ui.workers.base_worker import launch_worker

from core.environment.env_installer import INSTALL_BASE as _INSTALL_BASE
from core.environment.env_batch_checker import get_existing_env_paths
from core.environment.h2o_env_paths import is_managed_conda_executable

logger = logging.getLogger(__name__)


class LinuxSettingsToolInstallMixin:
    def _on_install_click(self, tool: dict) -> None:
        self._queue_install_tool(tool)

    def _on_install_from_web(self, tool_id: str) -> None:
        tool = next((t for t in self._tools if t["id"] == tool_id), None)
        if tool:
            self._queue_install_tool(tool)

    def _ensure_tool_install_ready(self, *, interactive: bool = True) -> bool:
        if not self._is_ssh_service_ready():
            self._set_status("SSH 未连接，无法安装", self.STATUS_ERROR)
            return False
        if self._miniforge_installing:
            self._set_status("运行环境正在初始化，请稍后再安装工具", self.STATUS_NEUTRAL)
            return False
        if not self._conda_executable or not is_managed_conda_executable(self._conda_executable):
            self._set_status("运行环境未就绪，请先完成初始化", self.STATUS_ERROR)
            return False
        return True

    def _queue_install_tool(self, tool: dict) -> None:
        tool_snapshot = dict(tool)
        QTimer.singleShot(0, lambda: self._do_install_tool(tool_snapshot))

    def _do_install_tool(self, tool: dict) -> None:
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
            self._set_status(f"打开安装窗口失败: {tool_name}", self.STATUS_ERROR)
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
                self._set_status(f"安装窗口异常关闭，后台任务仍在继续: {tool_name}", self.STATUS_NEUTRAL)
                message = (
                    f"工具【{tool_name}】的安装窗口运行异常，但后台安装任务仍会继续。\n\n"
                    f"错误信息：{exc}"
                )
            else:
                self._set_status(f"打开安装窗口失败: {tool_name}", self.STATUS_ERROR)
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

        QTimer.singleShot(300, self._do_batch_check)

    def _on_install_failed(self, tool_id: str) -> None:
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
        return _tool_env_exists_in_paths(tool, existing_env_paths, self._conda_executable)
