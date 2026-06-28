from __future__ import annotations

from typing import Any, Optional


class RunnerDatabaseOperationsMixin:
    def list_databases(self) -> dict[str, Any]:
        return self.databases.list_databases()

    def list_database_templates(self) -> dict[str, Any]:
        return self.databases.list_database_templates()

    def list_database_packs(self) -> dict[str, Any]:
        return self.databases.list_database_packs()

    def scan_database_pack_ready(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.databases.scan_database_pack_ready(payload)

    def add_database(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.databases.add_database(payload)

    def delete_database(self, database_id: str) -> dict[str, Any]:
        return self.databases.delete_database(database_id)

    def update_database(self, database_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.databases.update_database(database_id, payload)

    def check_database(self, database_id: str) -> dict[str, Any]:
        return self.databases.check_database(database_id)
