from __future__ import annotations

from typing import Any


class RemoteRunnerResultPackageProxyMixin:
    def list_result_package_exports(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.list_result_package_exports(
            str(kwargs["result_id"]),
            lifecycle_state=kwargs.get("lifecycle_state"),
            limit=int(kwargs.get("limit") or 100),
        )

    def retire_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.retire_result_package(
            str(kwargs["result_id"]),
            str(kwargs["package_export_id"]),
            dict(kwargs.get("payload") or {}),
        )

    def delete_result_package_bytes(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.delete_result_package_bytes(
            str(kwargs["result_id"]),
            str(kwargs["package_export_id"]),
            dict(kwargs.get("payload") or {}),
        )

    def preview_result_package_byte_gc(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.preview_result_package_byte_gc(dict(kwargs.get("payload") or {}))
