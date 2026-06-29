from __future__ import annotations

from typing import Any


class RemoteRunnerArtifactLifecycleProxyMixin:
    def run_artifact_lifecycle_controller_once(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.post_json(
            "/api/v1/artifacts/lifecycle/controller/run-once",
            kwargs["payload"],
        )["data"]
