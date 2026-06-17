from __future__ import annotations

from typing import Any

from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerConflictError


DATABASE_VALIDATION_TIMEOUT_SECONDS = 2100


class RemoteRunnerCatalogMixin:
    def list_database_templates(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/database-templates")["data"]["items"]

    def list_database_packs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/database-packs")["data"]

    def list_databases(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/databases")["data"]["items"]

    def add_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=DATABASE_VALIDATION_TIMEOUT_SECONDS,
        )
        try:
            return client.post_json("/api/v1/databases", kwargs["payload"])["data"]
        except RemoteRunnerConflictError:
            raise
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc), status_code=exc.status_code, detail=exc.detail) from exc

    def update_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.patch_json(f"/api/v1/databases/{kwargs['database_id']}", kwargs["payload"])["data"]

    def delete_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.delete_json(f"/api/v1/databases/{kwargs['database_id']}")["data"]

    def check_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=DATABASE_VALIDATION_TIMEOUT_SECONDS,
        )
        return client.post_json(f"/api/v1/databases/{kwargs['database_id']}/check", {})["data"]

    @staticmethod
    def _manager_error(message: str, *, status_code: int | None = None, detail: Any = None) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message, status_code=status_code, detail=detail)
