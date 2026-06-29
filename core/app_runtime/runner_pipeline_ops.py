from __future__ import annotations

from typing import Any, Optional


class RunnerPipelineOperationsMixin:
    def list_pipelines(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.pipelines.list_pipelines(server_id)

    def get_pipeline(self, pipeline_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.pipelines.get_pipeline(pipeline_id, server_id)
