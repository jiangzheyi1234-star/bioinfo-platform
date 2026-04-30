from __future__ import annotations

from typing import Any

from core.remote_runner.client import RemoteRunnerClientError


class RemoteRunnerCatalogMixin:
    def list_database_templates(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/database-templates")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def list_databases(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/databases")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def add_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json("/api/v1/databases", kwargs["payload"])["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def delete_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.delete_json(f"/api/v1/databases/{kwargs['database_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def check_database(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json(f"/api/v1/databases/{kwargs['database_id']}/check", {})["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
