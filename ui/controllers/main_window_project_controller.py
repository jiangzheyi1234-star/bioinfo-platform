"""Project and selector menu orchestration for MainWindow."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtWidgets import QInputDialog, QMessageBox

from ui.pages.project_page import CreateProjectDialog
from ui.widgets.project_selector import ProjectSelectorMenu


class MainWindowProjectController:
    """Keep project-switch flow out of MainWindow view code."""

    def __init__(
        self,
        *,
        pm,
        project_selector_btn,
        status_bar,
        log_page,
        log_controller,
        schedule_reconcile_fn: Callable[[], None],
        notify_context_fn: Callable[[], None],
        logger: Any,
        parent_widget,
    ) -> None:
        self._pm = pm
        self._project_selector_btn = project_selector_btn
        self._status_bar = status_bar
        self._log_page = log_page
        self._log_controller = log_controller
        self._schedule_reconcile = schedule_reconcile_fn
        self._notify_context = notify_context_fn
        self._logger = logger
        self._parent_widget = parent_widget
        self._project_menu: ProjectSelectorMenu | None = None

    def show_project_menu(self) -> None:
        if self._project_menu is None:
            self._project_menu = ProjectSelectorMenu(self._parent_widget)
            self._project_menu.project_selected.connect(self.on_menu_project_selected)
            self._project_menu.create_project_requested.connect(self.on_create_project_clicked)
            self._project_menu.delete_project_requested.connect(self.on_menu_delete_project)

        self._project_menu.refresh_projects(self._pm)
        self._project_menu.show_at(self._project_selector_btn)

    def update_project_selector(self) -> None:
        current = self._pm.current_project
        if current:
            self._project_selector_btn.set_project_name(current.name)
        else:
            self._project_selector_btn.set_empty_state()

    def on_menu_project_selected(self, project_id: str) -> None:
        current = self._pm.current_project
        if current and current.project_id == project_id:
            return
        try:
            self._pm.open_project(project_id)
            self.on_project_switched(project_id, logger=self._logger, parent_widget=self._parent_widget)
        except Exception as exc:
            self._logger.error("切换项目失败: %s", exc)
            QMessageBox.warning(
                self._parent_widget,
                "切换项目失败",
                f"无法打开该项目：{exc}",
            )

    def on_create_project_clicked(self) -> None:
        dialog = CreateProjectDialog(self._parent_widget)
        if dialog.exec():
            name, desc = dialog.get_values()
            if not name:
                return
            try:
                project_id = self._pm.create_project(name, desc)
                self._pm.open_project(project_id)
                self.on_project_switched(project_id, logger=self._logger, parent_widget=self._parent_widget)
            except Exception as exc:
                self._logger.error("创建项目失败: %s", exc)

    def on_menu_delete_project(self) -> None:
        current = self._pm.current_project
        current_id = current.project_id if current else ""

        candidates = [
            p
            for p in self._pm.list_projects()
            if p.status == "active" and p.project_id != current_id
        ]
        if not candidates:
            QMessageBox.information(self._parent_widget, "提示", "没有可删除的项目。请先切换到其他项目。")
            return

        labels = [p.name for p in candidates]
        selected_name, ok = QInputDialog.getItem(
            self._parent_widget,
            "删除项目",
            "选择要删除的项目：",
            labels,
            0,
            False,
        )
        if not ok or not selected_name:
            return

        target = next((p for p in candidates if p.name == selected_name), None)
        if target is None:
            return

        result = QMessageBox.question(
            self._parent_widget,
            "确认删除",
            f"确定删除项目“{target.name}”吗？\n项目文件将被永久删除，无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        try:
            self._pm.delete_project(target.project_id)
            self.update_project_selector()
            QMessageBox.information(self._parent_widget, "成功", f"项目“{target.name}”已删除。")
        except Exception as exc:
            self._logger.error("删除项目失败: %s", exc)
            QMessageBox.critical(self._parent_widget, "错误", f"删除项目失败: {exc}")

    def on_project_switched(self, project_id: str, *, logger: Any, parent_widget) -> None:
        self.update_project_selector()

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
