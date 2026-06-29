from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.tool_remote_endpoints import TOOL_INDEX_READ, TOOL_LIST


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
            "data": self.call_existing_runner(
                "add_tool",
                preferred_server_id=preferred_server_id,
                payload=body,
            )
        }

    def create_tool_prepare_job(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "create_tool_prepare_job",
                preferred_server_id=preferred_server_id,
                payload=body,
            )
        }

    def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, Any]:
        return {
            "data": {
                "byToolId": self.call_existing_runner(
                    "list_latest_tool_prepare_jobs",
                    tool_ids=tool_ids,
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
            "data": self.call_existing_runner(
                "list_tool_prepare_job_queue",
                status=status,
                limit=limit,
                offset=offset,
            )
        }

    def get_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "get_tool_prepare_job",
                job_id=job_id,
            )
        }

    def cancel_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "cancel_tool_prepare_job",
                job_id=job_id,
            )
        }

    def update_tool_rule_template(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "update_tool_rule_template",
                preferred_server_id=preferred_server_id,
                tool_id=tool_id,
                payload=body,
            )
        }

    def delete_tool(self, tool_id: str) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "delete_tool",
                tool_id=tool_id,
            )
        }

    def mark_tool_production_enabled(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "mark_tool_production_enabled",
                preferred_server_id=preferred_server_id,
                tool_id=tool_id,
                payload=body,
            )
        }
