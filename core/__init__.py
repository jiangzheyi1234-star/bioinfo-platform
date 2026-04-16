"""Core 模块 — H2OMeta 核心功能。

保持包初始化轻量，避免仅导入 ``core`` 时触发 SSH / Paramiko 等重量级副作用。
"""

from importlib import import_module
from typing import Any

__all__ = ["ExecutionCleaner", "ExecutionDiskUsage"]


def __getattr__(name: str) -> Any:
    if name in {"ExecutionCleaner", "ExecutionDiskUsage"}:
        module = import_module("core.data.execution_cleaner")
        return getattr(module, name)
    raise AttributeError(f"module 'core' has no attribute {name!r}")
