from __future__ import annotations

from typing import Any


class RemoteRunnerResultPackageProxyMixin:
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
