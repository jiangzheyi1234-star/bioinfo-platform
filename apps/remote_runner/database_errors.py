from __future__ import annotations

from typing import Any


class DatabaseRegistryError(ValueError):
    status_code = 400


class DatabaseNotFoundError(DatabaseRegistryError):
    status_code = 404


class DatabaseCandidateConflictError(DatabaseRegistryError):
    status_code = 409

    def __init__(self, payload: dict[str, Any]):
        super().__init__("Multiple database candidates were found")
        self.payload = payload
