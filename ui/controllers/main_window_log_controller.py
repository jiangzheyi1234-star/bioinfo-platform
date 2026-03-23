"""MainWindow log/history coordination helpers."""

from __future__ import annotations

from typing import Any, Optional

from core.data.execution_query_service import ExecutionQueryService


class MainWindowLogController:
    """Coordinate log-page data and execution event messages."""

    def __init__(self, *, pm, locator, log_page) -> None:
        self._pm = pm
        self._locator = locator
        self._log_page = log_page

    def current_project_id(self) -> str:
        cp = self._pm.current_project
        return cp.project_id if cp else ""

    def load_log_history_for_project(self, project_id: str, logger: Any) -> None:
        try:
            query_service = ExecutionQueryService(self._pm.db)
            rows = query_service.list_recent_executions(limit=50, archived=False)
            self._log_page.load_history_rows(rows, project_id)
        except Exception:
            logger.exception("加载日志历史失败")

    def on_exec_started(self, execution_id: str, ssh_wrapper: Optional[Any]) -> None:
        task_dir = self._locator.get_task_dir(execution_id)
        if task_dir:
            self._log_page.set_execution_context(execution_id, task_dir)
            if ssh_wrapper is not None:
                self._log_page.set_ssh_run_fn(ssh_wrapper.run)

    def on_exec_completed(self, execution_id: str) -> None:
        pid = self.current_project_id()
        self._log_page.append_log("SUCCESS", f"任务完成: {execution_id[:16]}", execution_id, pid)
        self._log_page.stop_tailing()

    def on_exec_failed(self, execution_id: str, error: str) -> None:
        msg = f"任务失败: {execution_id[:16]}"
        if error:
            msg += f" — {error[:100]}"
        pid = self.current_project_id()
        self._log_page.append_log("ERROR", msg, execution_id, pid)
        self._log_page.stop_tailing()

