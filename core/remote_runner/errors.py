from __future__ import annotations

from typing import Any


class RemoteRunnerManagerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        bootstrap_metadata: dict[str, Any] | None = None,
        status_code: int | None = None,
        detail: Any = None,
    ):
        super().__init__(message)
        self.bootstrap_metadata = bootstrap_metadata
        self.status_code = status_code
        self.detail = detail
