"""H2OMeta UI 层入口。

保持初始化轻量，避免仅导入 ``ui`` 时就拉起所有页面依赖。
"""

from importlib import import_module
from typing import Any

__all__ = ["HomePage", "DetectionPageWeb", "SettingsPage"]


def __getattr__(name: str) -> Any:
    if name in set(__all__):
        return getattr(import_module("ui.pages"), name)
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
