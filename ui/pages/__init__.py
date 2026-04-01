"""页面导出入口。

避免导入 ``ui.pages`` 时立即实例化所有页面依赖。
"""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "SettingsPage": "ui.pages.settings_page",
    "DatabasePage": "ui.pages.database_page",
    "DetectionPageWeb": "ui.pages.detection_page_web",
    "HomePage": "ui.pages.home_page",
    "ProjectPage": "ui.pages.project_page",
    "LogPage": "ui.pages.log_page",
}

__all__ = [
    "SettingsPage",
    "DatabasePage",
    "DetectionPageWeb",
    "DetectionPage",
    "HomePage",
    "ProjectPage",
    "LogPage",
]


def __getattr__(name: str) -> Any:
    if name == "DetectionPage":
        name = "DetectionPageWeb"
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'ui.pages' has no attribute {name!r}")
    return getattr(import_module(module_name), name)
