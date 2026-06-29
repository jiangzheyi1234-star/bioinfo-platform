from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.workflow_design_remote_endpoints import (
    WORKFLOW_DESIGN_DRAFT_COMPILE,
    WORKFLOW_DESIGN_DRAFT_CREATE,
    WORKFLOW_DESIGN_DRAFT_DELETE,
    WORKFLOW_DESIGN_DRAFT_FORK,
    WORKFLOW_DESIGN_DRAFT_LIST,
    WORKFLOW_DESIGN_DRAFT_PLAN,
    WORKFLOW_DESIGN_DRAFT_READ,
    WORKFLOW_DESIGN_DRAFT_UPDATE,
)


class WorkflowManager(BaseRuntimeManager):
    def list_workflow_design_drafts(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": {
                "items": self.call_existing_remote_endpoint(WORKFLOW_DESIGN_DRAFT_LIST, preferred_server_id=server_id)
            }
        }

    def create_workflow_design_draft(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return self.read_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_CREATE,
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def get_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_READ,
            path_values={"draft_id": draft_id},
            preferred_server_id=server_id,
        )

    def update_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return self.read_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_UPDATE,
            path_values={"draft_id": draft_id},
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def fork_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        return self.read_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_FORK,
            path_values={"draft_id": draft_id},
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def delete_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_DELETE,
            path_values={"draft_id": draft_id},
            preferred_server_id=server_id,
        )

    def plan_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        return self.read_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_PLAN,
            path_values={"draft_id": draft_id},
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def compile_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        return self.read_remote_endpoint(
            WORKFLOW_DESIGN_DRAFT_COMPILE,
            path_values={"draft_id": draft_id},
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )
