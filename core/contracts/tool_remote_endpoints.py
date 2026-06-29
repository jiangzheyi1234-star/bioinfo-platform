from __future__ import annotations

from typing import Any


TOOL_LIST = "tool.list"
TOOL_INDEX_READ = "tool.index.read"


TOOL_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    TOOL_LIST: {
        "method": "GET",
        "path_template": "/api/v1/tools",
        "operation_id": "listTools",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-list.v1",
        "cache_scope": "tool-read-model",
        "response_item_key": "items",
    },
    TOOL_INDEX_READ: {
        "method": "GET",
        "path_template": "/api/v1/tools/index",
        "operation_id": "listToolIndex",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-index.v1",
        "cache_scope": "tool-read-model",
        "query_params": ("query", "limit", "offset", "source", "state"),
    },
}
