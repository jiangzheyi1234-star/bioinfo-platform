from __future__ import annotations

from typing import Any, Optional


class RunnerWorkflowDesignOperationsMixin:
    def list_workflow_design_drafts(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.workflows.list_workflow_design_drafts(server_id)

    def create_workflow_design_draft(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.workflows.create_workflow_design_draft(payload)

    def get_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.workflows.get_workflow_design_draft(draft_id, server_id)

    def update_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.workflows.update_workflow_design_draft(draft_id, payload)

    def fork_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.workflows.fork_workflow_design_draft(draft_id, payload)

    def delete_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.workflows.delete_workflow_design_draft(draft_id, server_id)

    def plan_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.workflows.plan_workflow_design_draft(draft_id, payload)

    def compile_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.workflows.compile_workflow_design_draft(draft_id, payload)
