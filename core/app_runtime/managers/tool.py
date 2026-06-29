from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.tool_remote_endpoints import (
    TOOL_CREATE,
    TOOL_DELETE,
    TOOL_INDEX_READ,
    TOOL_LIST,
    TOOL_PREPARE_JOB_CANCEL,
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_LATEST_READ,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
    TOOL_PRODUCTION_ENABLE,
    TOOL_RULE_TEMPLATE_UPDATE,
)


class ToolManager(BaseRuntimeManager):
    def list_tools(self) -> dict[str, Any]:
        items = self.call_remote_endpoint(
            TOOL_LIST,
            path_values={},
            require_existing_runner=True,
        )
        return {"data": {"items": items}}

    def list_tool_index(
        self,
        *,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        source: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                TOOL_INDEX_READ,
                path_values={},
                query_values={
                    "query": query,
                    "limit": limit,
                    "offset": offset,
                    "source": source,
                    "state": state,
                },
                require_existing_runner=True,
            )
        }

    def add_tool(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                TOOL_CREATE,
                path_values={},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
            )
        }

    def create_tool_prepare_job(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                TOOL_PREPARE_JOB_CREATE,
                path_values={},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
            )
        }

    def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, Any]:
        encoded_tool_ids = ",".join(str(item or "").strip() for item in tool_ids if str(item or "").strip())
        return {
            "data": {
                "byToolId": self.call_remote_endpoint(
                    TOOL_PREPARE_JOB_LATEST_READ,
                    path_values={},
                    query_values={"toolIds": encoded_tool_ids},
                    require_existing_runner=True,
                )
            }
        }

    def list_tool_prepare_job_queue(
        self,
        *,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                TOOL_PREPARE_JOB_QUEUE_READ,
                path_values={},
                query_values={"status": status, "limit": limit, "offset": offset},
                require_existing_runner=True,
            )
        }

    def get_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                TOOL_PREPARE_JOB_READ,
                path_values={"job_id": job_id},
                require_existing_runner=True,
            )
        }

    def cancel_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                TOOL_PREPARE_JOB_CANCEL,
                path_values={"job_id": job_id},
                require_existing_runner=True,
            )
        }

    def update_tool_rule_template(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                TOOL_RULE_TEMPLATE_UPDATE,
                path_values={"tool_id": tool_id},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
            )
        }

    def delete_tool(self, tool_id: str) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                TOOL_DELETE,
                path_values={"tool_id": tool_id},
                require_existing_runner=True,
            )
        }

    def mark_tool_production_enabled(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_remote_endpoint(
                TOOL_PRODUCTION_ENABLE,
                path_values={"tool_id": tool_id},
                payload=body,
                preferred_server_id=preferred_server_id,
                require_existing_runner=True,
            )
        }
