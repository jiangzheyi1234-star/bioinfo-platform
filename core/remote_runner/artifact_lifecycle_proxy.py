from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


class RemoteRunnerArtifactLifecycleProxyMixin:
    def list_artifact_lifecycle_controller_ticks(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        query = urlencode({"limit": int(kwargs.get("limit") or 20)})
        return client.get_json(f"/api/v1/artifacts/lifecycle/controller/ticks?{query}")["data"]
