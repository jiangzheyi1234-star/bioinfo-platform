from __future__ import annotations

from typing import Any


class ToolRegistryError(ValueError):
    pass


class ToolPrepareWaitingResourceError(ToolRegistryError):
    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.details = details or {}
