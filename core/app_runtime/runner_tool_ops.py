from __future__ import annotations

from typing import Any, Optional


class RunnerToolOperationsMixin:
    def list_tools(self) -> dict[str, Any]:
        return self.tools.list_tools()

    def list_tool_index(
        self,
        *,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        source: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        return self.tools.list_tool_index(
            query=query,
            limit=limit,
            offset=offset,
            source=source,
            state=state,
        )

    def add_tool(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.tools.add_tool(payload)

    def create_tool_prepare_job(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.tools.create_tool_prepare_job(payload)

    def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, Any]:
        return self.tools.list_latest_tool_prepare_jobs(tool_ids)

    def get_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return self.tools.get_tool_prepare_job(job_id)

    def cancel_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        return self.tools.cancel_tool_prepare_job(job_id)

    def update_tool_rule_template(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.tools.update_tool_rule_template(tool_id, payload)

    def delete_tool(self, tool_id: str) -> dict[str, Any]:
        return self.tools.delete_tool(tool_id)

    def mark_tool_production_enabled(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.tools.mark_tool_production_enabled(tool_id, payload)
