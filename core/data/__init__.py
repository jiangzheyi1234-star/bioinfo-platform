"""数据管理模块 — SQLite 数据模型、血缘追踪、项目管理、归档清理。"""

from importlib import import_module
from typing import Any

__all__ = ["SampleService", "DatabaseService"]


def __getattr__(name: str) -> Any:
    if name == "DatabaseService":
        return getattr(import_module("core.data.database_service"), name)
    if name == "SampleService":
        return getattr(import_module("core.data.sample_service"), name)
    raise AttributeError(f"module 'core.data' has no attribute {name!r}")
