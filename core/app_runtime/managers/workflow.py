from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager


class WorkflowManager(BaseRuntimeManager):
    def list_workflow_design_drafts(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": {
                "items": self.call_existing_runner(
                    "list_workflow_design_drafts",
                    preferred_server_id=server_id,
                )
            }
        }

    def create_workflow_design_draft(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "create_workflow_design_draft",
                preferred_server_id=preferred_server_id,
                payload=body,
            )
        }

    def get_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "get_workflow_design_draft",
                preferred_server_id=server_id,
                draft_id=draft_id,
            )
        }

    def update_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "update_workflow_design_draft",
                preferred_server_id=preferred_server_id,
                draft_id=draft_id,
                payload=body,
            )
        }

    def fork_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return {
            "data": self.call_existing_runner(
                "fork_workflow_design_draft",
                preferred_server_id=preferred_server_id,
                draft_id=draft_id,
                payload=body,
            )
        }

    def delete_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "delete_workflow_design_draft",
                preferred_server_id=server_id,
                draft_id=draft_id,
            )
        }

    def plan_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        return {
            "data": self.call_existing_runner(
                "plan_workflow_design_draft",
                preferred_server_id=preferred_server_id,
                draft_id=draft_id,
                payload=body,
            )
        }

    def compile_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        return {
            "data": self.call_existing_runner(
                "compile_workflow_design_draft",
                preferred_server_id=preferred_server_id,
                draft_id=draft_id,
            )
        }
