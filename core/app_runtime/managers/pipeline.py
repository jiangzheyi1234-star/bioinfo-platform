from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.pipeline_remote_endpoints import PIPELINE_LIST, PIPELINE_READ


class PipelineManager(BaseRuntimeManager):
    def list_pipelines(self, server_id: Optional[str] = None) -> dict[str, Any]:
        items = self.call_existing_remote_endpoint(
            PIPELINE_LIST,
            preferred_server_id=server_id,
        )
        return {"data": {"items": items}}

    def get_pipeline(self, pipeline_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            PIPELINE_READ,
            path_values={"pipeline_id": pipeline_id},
            preferred_server_id=server_id,
        )
