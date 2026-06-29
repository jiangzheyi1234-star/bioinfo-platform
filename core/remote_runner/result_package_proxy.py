from __future__ import annotations

from typing import Any


class RemoteRunnerResultPackageProxyMixin:
    def _result_package_client(self, kwargs: dict[str, Any]):
        options: dict[str, Any] = {
            "server_id": str(kwargs["server_id"]),
            "ssh_service": kwargs["ssh_service"],
            "record": kwargs["server_record"],
        }
        if kwargs.get("timeout") is not None:
            options["timeout"] = int(kwargs["timeout"])
        return self._get_client(**options)

    def export_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client(kwargs)
        return client.post_json(
            f"/api/v1/results/{kwargs['result_id']}/export",
            dict(kwargs.get("payload") or {}),
        )["data"]

    def download_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client({**kwargs, "timeout": 60})
        return client.download_result_package(kwargs["result_id"], kwargs["package_export_id"])

    def retire_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client(kwargs)
        return client.retire_result_package(
            str(kwargs["result_id"]),
            str(kwargs["package_export_id"]),
            dict(kwargs.get("payload") or {}),
        )

    def preview_result_package_byte_gc(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client(kwargs)
        return client.preview_result_package_byte_gc(dict(kwargs.get("payload") or {}))

    def run_result_package_byte_gc(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client(kwargs)
        return client.run_result_package_byte_gc(dict(kwargs.get("payload") or {}))
