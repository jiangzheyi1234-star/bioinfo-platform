from __future__ import annotations

from typing import Any


class ToolRegistryError(ValueError):
    status_code = 400


class ToolNotFoundError(ToolRegistryError):
    status_code = 404


class ToolProductionConflictError(ToolRegistryError):
    status_code = 409


class ToolPrepareWaitingResourceError(ToolRegistryError):
    def __init__(self, *, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.details = details or {}
