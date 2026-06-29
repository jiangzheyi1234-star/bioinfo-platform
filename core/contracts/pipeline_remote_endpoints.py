from __future__ import annotations

from typing import Any


PIPELINE_LIST = "pipeline.list"
PIPELINE_READ = "pipeline.read"


PIPELINE_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    PIPELINE_LIST: {
        "method": "GET",
        "path_template": "/api/v1/pipelines",
        "operation_id": "listPipelines",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "pipeline-list.v1",
        "cache_scope": "pipeline-read-model",
        "response_item_key": "items",
    },
    PIPELINE_READ: {
        "method": "GET",
        "path_template": "/api/v1/pipelines/{pipeline_id}",
        "operation_id": "getPipeline",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "pipeline.v1",
        "cache_scope": "pipeline-read-model",
    },
}
