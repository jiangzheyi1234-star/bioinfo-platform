"""远程连接模块 — SSH 连接、重连、远端存储。"""

from importlib import import_module
from typing import Any

__all__ = [
    "classify_ssh_error",
    "diagnose_to_text",
    "run_diagnostics",
    "ssh_connect",
    "ConnectResult",
    "DiagnosticStep",
]


def __getattr__(name: str) -> Any:
    if name in set(__all__):
        return getattr(import_module("core.remote.ssh_connector"), name)
    raise AttributeError(f"module 'core.remote' has no attribute {name!r}")
