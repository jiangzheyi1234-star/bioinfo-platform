from __future__ import annotations

from typing import Any
from urllib.parse import quote


class RemoteRunnerWorkflowRevisionProxyMixin:
    def get_workflow_revision(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        revision_id = quote(str(kwargs["workflow_revision_id"]), safe="")
        return client.get_json(f"/api/v1/workflow-revisions/{revision_id}")["data"]
