"""Blank project home page placeholder."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from core.data.sample_service import SampleService
from ui.page_base import BasePage
from ui.widgets import styles


class HomePage(BasePage):
    """Intentionally blank placeholder page.

    Keep only the minimal API expected by MainWindow/tests so the homepage can
    be redesigned later without carrying old logic.
    """

    def __init__(self, main_window: Any = None, parent: Optional[QWidget] = None):
        super().__init__("项目首页")
        self._main_window = main_window

        # Preserve attributes that other code may still touch.
        self._card_widgets: list = []
        self._proj_name_label = QLabel("")
        self._stat_samples = QLabel("")
        self._add_btn = QLabel("")
        self._service: SampleService | None = None

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        if hasattr(self, "label"):
            self.label.hide()

        placeholder = QLabel("")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("background: transparent;")
        self.layout.addWidget(placeholder, stretch=1)

    def refresh_context(self) -> None:
        pass

    def clear_context(self) -> None:
        pass

    def _load_all(self) -> None:
        pass

    def _on_continue_analysis(self, sample_id: str) -> None:
        if self._main_window is None or not hasattr(self._main_window, "open_analysis_for_sample"):
            return

        locator = getattr(self._main_window, "service_locator", None)
        pm = getattr(locator, "project_manager", None) if locator is not None else None
        if pm is None or pm.current_project is None:
            return

        if self._service is None:
            ssh = getattr(locator, "ssh_service", None) if locator is not None else None
            self._service = SampleService(pm.db, ssh)
        else:
            self._service.set_db(pm.db)
            self._service.set_ssh_service(getattr(locator, "ssh_service", None) if locator is not None else None)

        info = self._service.get_sample_metadata(sample_id)
        if not info.get("name"):
            return

        metadata = info.get("metadata", {})
        self._main_window.open_analysis_for_sample(
            sample_id=sample_id,
            sample_name=info["name"],
            r1_path=metadata.get("r1", ""),
            r2_path=metadata.get("r2", ""),
        )
