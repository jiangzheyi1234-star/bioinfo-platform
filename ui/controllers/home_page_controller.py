"""HomePage controller."""

from __future__ import annotations

import logging
from typing import Any

from core.data.sample_service import SampleService

logger = logging.getLogger(__name__)


class HomePageController:
    """Coordinate HomePage user actions with services and other pages."""

    def __init__(self, main_window: Any = None):
        self._main_window = main_window

    def get_project_manager(self):
        locator = self.get_service_locator()
        if locator is not None:
            return locator.project_manager
        return None

    def get_service_locator(self):
        if self._main_window and hasattr(self._main_window, "service_locator"):
            return self._main_window.service_locator
        return None

    def ensure_service(self, service: SampleService | None = None) -> SampleService | None:
        pm = self.get_project_manager()
        if pm is None or pm.current_project is None:
            return None

        locator = self.get_service_locator()
        ssh = getattr(locator, "ssh_service", None) if locator is not None else None

        if service is None:
            return SampleService(pm.db, ssh)

        service.set_db(pm.db)
        service.set_ssh_service(ssh)
        return service

    def add_sample(
        self,
        service: SampleService,
        *,
        name: str,
        source: str,
        r1_path: str,
        r2_path: str,
    ) -> str:
        return service.add_sample(
            name=name,
            source=source,
            metadata={"r1": r1_path, "r2": r2_path},
        )

    def delete_sample(self, service: SampleService, sample_id: str) -> bool:
        return service.delete_sample(sample_id)

    def get_sample_name(self, service: SampleService, sample_id: str) -> str:
        return service.get_sample_name(sample_id)

    def open_analysis_for_sample(self, service: SampleService, sample_id: str) -> bool:
        info = service.get_sample_metadata(sample_id)
        if not info.get("name"):
            return False

        if self._main_window is None or not hasattr(self._main_window, "open_analysis_for_sample"):
            return False

        try:
            metadata = info.get("metadata", {})
            return bool(
                self._main_window.open_analysis_for_sample(
                    sample_id=sample_id,
                    sample_name=info["name"],
                    r1_path=metadata.get("r1", ""),
                    r2_path=metadata.get("r2", ""),
                )
            )
        except Exception:
            logger.debug("预填分析页参数失败（非严重错误）", exc_info=True)
            return False
