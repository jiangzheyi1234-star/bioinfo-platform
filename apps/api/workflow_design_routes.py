"""WorkflowDesignDraft routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftPlanRequest,
    WorkflowDesignDraftUpdateRequest,
)
from apps.api.workflow_design_service import (
    compile_workflow_design_draft_from_request,
    create_workflow_design_draft_from_request,
    delete_workflow_design_draft_from_request,
    fork_workflow_design_draft_from_request,
    get_workflow_design_draft_from_request,
    list_workflow_design_drafts_from_request,
    plan_workflow_design_draft_from_request,
    update_workflow_design_draft_from_request,
)


router = APIRouter()


@router.get("/api/v1/workflow-design-drafts")
async def list_workflow_design_drafts_api(
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_workflow_design_drafts_from_request(
        refresh=refresh,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-design-drafts", status_code=201)
async def create_workflow_design_draft_api(
    payload: WorkflowDesignDraftCreateRequest,
) -> dict[str, Any]:
    return await create_workflow_design_draft_from_request(payload)


@router.get("/api/v1/workflow-design-drafts/{draft_id}")
async def get_workflow_design_draft_api(
    draft_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await get_workflow_design_draft_from_request(
        draft_id,
        server_id=serverId,
    )


@router.patch("/api/v1/workflow-design-drafts/{draft_id}")
async def update_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    return await update_workflow_design_draft_from_request(draft_id, payload)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/fork", status_code=201)
async def fork_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    return await fork_workflow_design_draft_from_request(draft_id, payload)


@router.delete("/api/v1/workflow-design-drafts/{draft_id}")
async def delete_workflow_design_draft_api(
    draft_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await delete_workflow_design_draft_from_request(draft_id, server_id=serverId)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/plan")
async def plan_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftPlanRequest | None = None,
) -> dict[str, Any]:
    return await plan_workflow_design_draft_from_request(draft_id, payload)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/compile")
async def compile_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftCompileRequest | None = None,
) -> dict[str, Any]:
    return await compile_workflow_design_draft_from_request(draft_id, payload)
