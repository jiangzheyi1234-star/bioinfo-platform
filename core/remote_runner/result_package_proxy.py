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

    def download_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._result_package_client({**kwargs, "timeout": 60})
        return client.download_result_package(kwargs["result_id"], kwargs["package_export_id"])
