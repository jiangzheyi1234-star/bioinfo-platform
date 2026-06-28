from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager


class DatabaseManager(BaseRuntimeManager):
    def list_databases(self) -> dict[str, Any]:
        return {"data": {"items": self.call_existing_runner("list_databases")}}

    def list_database_templates(self) -> dict[str, Any]:
        return {"data": {"items": self.call_existing_runner("list_database_templates")}}

    def list_database_packs(self) -> dict[str, Any]:
        return {"data": self.call_existing_runner("list_database_packs")}

    def scan_database_pack_ready(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "scan_database_pack_ready",
                preferred_server_id=preferred_server_id,
                payload=body,
            )
        }

    def add_database(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "add_database",
                preferred_server_id=preferred_server_id,
                payload=body,
            )
        }

    def delete_database(self, database_id: str) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "delete_database",
                database_id=database_id,
            )
        }

    def update_database(self, database_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "update_database",
                database_id=database_id,
                payload=dict(payload or {}),
            )
        }

    def check_database(self, database_id: str) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "check_database",
                database_id=database_id,
            )
        }
