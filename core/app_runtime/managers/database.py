from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.database_remote_endpoints import (
    DATABASE_CHECK,
    DATABASE_CREATE,
    DATABASE_DELETE,
    DATABASE_LIST,
    DATABASE_PACK_LIST,
    DATABASE_PACK_READY_SCAN,
    DATABASE_TEMPLATE_LIST,
    DATABASE_UPDATE,
)


DATABASE_VALIDATION_TIMEOUT_SECONDS = 2100


class DatabaseManager(BaseRuntimeManager):
    def list_databases(self) -> dict[str, Any]:
        items = self.call_remote_endpoint(
            DATABASE_LIST,
            path_values={},
            require_existing_runner=True,
        )
        return {"data": {"items": items}}

    def list_database_templates(self) -> dict[str, Any]:
        items = self.call_remote_endpoint(
            DATABASE_TEMPLATE_LIST,
            path_values={},
            require_existing_runner=True,
        )
        return {"data": {"items": items}}

    def list_database_packs(self) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                DATABASE_PACK_LIST,
                path_values={},
                require_existing_runner=True,
            )
        }

    def scan_database_pack_ready(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                DATABASE_PACK_READY_SCAN,
                path_values={},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
                timeout=DATABASE_VALIDATION_TIMEOUT_SECONDS,
            )
        }

    def add_database(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                DATABASE_CREATE,
                path_values={},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
                timeout=DATABASE_VALIDATION_TIMEOUT_SECONDS,
            )
        }

    def delete_database(self, database_id: str) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                DATABASE_DELETE,
                path_values={"database_id": database_id},
                require_existing_runner=True,
            )
        }

    def update_database(self, database_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                DATABASE_UPDATE,
                path_values={"database_id": database_id},
                payload=dict(payload or {}),
                require_existing_runner=True,
            )
        }

    def check_database(self, database_id: str) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                DATABASE_CHECK,
                path_values={"database_id": database_id},
                require_existing_runner=True,
                timeout=DATABASE_VALIDATION_TIMEOUT_SECONDS,
            )
        }
