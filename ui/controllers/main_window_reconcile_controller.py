"""Background reconcile orchestration for MainWindow."""

from __future__ import annotations

import time
from typing import Any, Callable

from PyQt6.QtCore import QTimer

from core.data.execution_query_service import ExecutionQueryService
from core.execution.execution_reconcile_service import ExecutionReconcileService
from core.execution.task_runner import TaskRunner


class MainWindowReconcileController:
    """Run execution status reconcile out of MainWindow view code."""

    def __init__(
        self,
        *,
        pm,
        locator,
        parent,
        is_services_initialized: Callable[[], bool],
        logger: Any,
    ) -> None:
        self._pm = pm
        self._locator = locator
        self._is_services_initialized = is_services_initialized
        self._logger = logger

        self._reconcile_scheduled = False
        self._reconcile_task_id = ""
        self._resume_scheduled = False
        self._resume_task_id = ""
        self._runner = TaskRunner(max_threads=1, parent=parent)
        self._timer = QTimer(parent)
        self._timer.setInterval(20_000)
        self._timer.timeout.connect(self.schedule)
        self._runner.task_succeeded.connect(self._on_task_succeeded)
        self._runner.task_failed.connect(self._on_task_failed)

    def schedule(self, delay_ms: int = 150) -> None:
        if self._reconcile_scheduled:
            return
        self._reconcile_scheduled = True

        def _run() -> None:
            self._reconcile_scheduled = False
            self._reconcile_running_tasks()

        QTimer.singleShot(delay_ms, _run)

    def on_ssh_status_changed(self, connected: bool) -> None:
        if connected:
            self.schedule_resume()
            self.schedule()

    def on_ssh_changed(self, connected: bool) -> None:
        if connected:
            if not self._timer.isActive():
                self._timer.start()
            self.schedule_resume(delay_ms=120)
            self.schedule(delay_ms=200)
            return
        self._timer.stop()
        self._resume_scheduled = False
        self._resume_task_id = ""

    def schedule_resume(self, delay_ms: int = 120) -> None:
        if self._resume_scheduled:
            return
        self._resume_scheduled = True

        def _run() -> None:
            self._resume_scheduled = False
            self._resume_running_tasks_after_connect()

        QTimer.singleShot(delay_ms, _run)

    def shutdown(self) -> None:
        try:
            self._timer.stop()
        except Exception:
            self._logger.debug("停止任务校准定时器失败", exc_info=True)
        self._reconcile_scheduled = False
        self._reconcile_task_id = ""
        self._resume_scheduled = False
        self._resume_task_id = ""

        for signal, handler in (
            (self._runner.task_succeeded, self._on_task_succeeded),
            (self._runner.task_failed, self._on_task_failed),
        ):
            try:
                signal.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        if not self._runner.wait_for_done(timeout_ms=5000):
            self._logger.warning("Reconcile TaskRunner shutdown wait timed out")

    def _reconcile_running_tasks(self) -> None:
        try:
            if not self._is_services_initialized():
                return
            if self._pm.current_project is None:
                return
            ssh = self._locator.ssh_service
            if ssh is None or not getattr(ssh, "is_connected", False):
                return
            if self._reconcile_task_id:
                return

            query_service = ExecutionQueryService(self._pm.db)
            running_rows = query_service.list_running_executions(limit=20)
            failed_rows = query_service.list_failed_executions(limit=20)
            if not running_rows and not failed_rows:
                return

            running = [(r["execution_id"], r["sample_id"], r["tool_id"]) for r in running_rows]
            failed = [(r["execution_id"], r["sample_id"], r["tool_id"]) for r in failed_rows]
            task_id = f"ui_reconcile_{int(time.time() * 1000)}"
            self._reconcile_task_id = task_id
            self._runner.submit(
                ExecutionReconcileService.collect_actions,
                ssh,
                self._pm.current_project.remote_base,
                running,
                failed,
                task_id=task_id,
            )
        except Exception:
            self._reconcile_task_id = ""
            self._logger.exception("任务状态自动校准失败")

    def _resume_running_tasks_after_connect(self) -> None:
        try:
            if not self._is_services_initialized():
                return
            if self._pm.current_project is None:
                return
            ssh = self._locator.ssh_service
            if ssh is None or not getattr(ssh, "is_connected", False):
                return
            if self._resume_task_id:
                return

            query_service = ExecutionQueryService(self._pm.db)
            running_rows = query_service.list_running_executions(limit=50)
            if not running_rows:
                return

            running = [(r["execution_id"], r["sample_id"], r["tool_id"]) for r in running_rows]
            task_id = f"ui_resume_{int(time.time() * 1000)}"
            self._resume_task_id = task_id
            self._runner.submit(
                ExecutionReconcileService.collect_resume_actions,
                ssh,
                self._pm.current_project.remote_base,
                running,
                task_id=task_id,
            )
        except Exception:
            self._resume_task_id = ""
            self._logger.exception("启动后恢复运行任务监控失败")

    def _on_task_succeeded(self, task_id: str, payload: object) -> None:
        if task_id == self._resume_task_id:
            self._resume_task_id = ""
            self._apply_resume_actions(payload)
            return

        if task_id != self._reconcile_task_id:
            return
        self._reconcile_task_id = ""
        try:
            if not isinstance(payload, dict):
                return
            actions = payload
            relink_ids = [item["execution_id"] for item in actions.get("relink_running", [])]
            if relink_ids:
                query_service = ExecutionQueryService(self._pm.db)
                query_service.relink_failed_to_running(relink_ids)

            tool_engine = self._locator.tool_engine
            if tool_engine is None:
                return

            for item in actions.get("mark_completed", []):
                if self._locator.is_execution_waiting(item["execution_id"]):
                    continue
                descriptor = self._locator.plugin_registry.get_descriptor(item["tool_id"])
                tool_engine.on_job_completed(
                    execution_id=item["execution_id"],
                    descriptor=descriptor,
                    sample_id=item["sample_id"],
                    output_dir=item["output_dir"],
                )
            for item in actions.get("mark_failed", []):
                if self._locator.is_execution_waiting(item["execution_id"]):
                    continue
                tool_engine.on_job_failed(item["execution_id"], item["error"])
        except Exception:
            self._logger.exception("应用任务状态校准结果失败")

    def _apply_resume_actions(self, payload: object) -> None:
        try:
            if not isinstance(payload, dict):
                return
            actions = payload
            tool_engine = self._locator.tool_engine
            if tool_engine is None:
                return

            for item in actions.get("mark_completed", []):
                descriptor = self._locator.plugin_registry.get_descriptor(item["tool_id"])
                tool_engine.on_job_completed(
                    execution_id=item["execution_id"],
                    descriptor=descriptor,
                    sample_id=item["sample_id"],
                    output_dir=item["output_dir"],
                )
            for item in actions.get("mark_failed", []):
                tool_engine.on_job_failed(item["execution_id"], item["error"])
            for item in actions.get("resume_waiting", []):
                if self._locator.is_execution_waiting(item["execution_id"]):
                    continue
                self._locator.resume_execution_waiting(
                    execution_id=item["execution_id"],
                    sample_id=item["sample_id"],
                    tool_id=item["tool_id"],
                    task_dir=item["task_dir"],
                    job_id=item.get("job_id") or None,
                )
        except Exception:
            self._logger.exception("应用恢复监控动作失败")

    def _on_task_failed(self, task_id: str, error: str) -> None:
        if task_id == self._resume_task_id:
            self._resume_task_id = ""
            self._logger.warning("启动恢复后台任务失败: %s", error)
            return
        if task_id != self._reconcile_task_id:
            return
        self._reconcile_task_id = ""
        self._logger.warning("任务状态后台校准失败: %s", error)
