from __future__ import annotations

from typing import Any

from core.contracts.remote_endpoints import render_remote_endpoint_path
from core.contracts.result_package_remote_endpoints import RESULT_PACKAGE_DOWNLOAD


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
        path = render_remote_endpoint_path(
            RESULT_PACKAGE_DOWNLOAD,
            {
                "result_id": kwargs["result_id"],
                "package_export_id": kwargs["package_export_id"],
            },
        )
        return client.download_bytes(path)
