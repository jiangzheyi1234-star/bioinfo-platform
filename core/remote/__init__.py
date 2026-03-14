"""远程连接模块 — SSH 连接、重连、远端存储。"""

from core.remote.ssh_connector import (
    classify_ssh_error,
    diagnose_to_text,
    run_diagnostics,
    ssh_connect,
    ConnectResult,
    DiagnosticStep,
)

__all__ = [
    "classify_ssh_error",
    "diagnose_to_text",
    "run_diagnostics",
    "ssh_connect",
    "ConnectResult",
    "DiagnosticStep",
]