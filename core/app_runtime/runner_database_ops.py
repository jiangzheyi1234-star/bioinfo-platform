from __future__ import annotations

from typing import Any, Optional


class RunnerDatabaseOperationsMixin:
    def list_databases(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_databases,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def list_database_templates(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_database_templates,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def add_database(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.add_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def delete_database(self, database_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.delete_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
            )
        }

    def update_database(self, database_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.update_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
                payload=dict(payload or {}),
            )
        }

    def check_database(self, database_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.check_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
            )
        }
