"""执行链模块 — 任务提交、分发、监控。"""

from importlib import import_module
from typing import Any

__all__ = ["ToolBridgeService"]


def __getattr__(name: str) -> Any:
    if name == "ToolBridgeService":
        return getattr(import_module("core.execution.tool_bridge_service"), name)
    raise AttributeError(f"module 'core.execution' has no attribute {name!r}")
