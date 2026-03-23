"""Project-switch orchestration for MainWindow."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtWidgets import QMessageBox


class MainWindowProjectController:
    """Keep project-switch flow out of MainWindow view code."""

    def __init__(
        self,
        *,
        pm,
        status_bar,
        log_page,
        log_controller,
        update_project_selector_fn: Callable[[], None],
        schedule_reconcile_fn: Callable[[], None],
        notify_context_fn: Callable[[], None],
    ) -> None:
        self._pm = pm
        self._status_bar = status_bar
        self._log_page = log_page
        self._log_controller = log_controller
        self._update_project_selector = update_project_selector_fn
        self._schedule_reconcile = schedule_reconcile_fn
        self._notify_context = notify_context_fn

    def on_project_switched(self, project_id: str, *, logger: Any, parent_widget) -> None:
        self._update_project_selector()

        current = self._pm.current_project
        self._status_bar.update_project(current.name if current else None)
        self._schedule_reconcile()
        self._notify_context()

        self._log_page.set_project_context(project_id)
        self._log_controller.load_log_history_for_project(project_id, logger)

        if getattr(self._pm, "db_read_only", False):
            QMessageBox.warning(
                parent_widget,
                "项目只读模式",
                "当前项目数据库被其他进程占用，已以只读模式打开。\n"
                "请关闭占用该数据库的程序后重试，以恢复可写模式。",
            )

        logger.info("项目已切换: %s", project_id)

