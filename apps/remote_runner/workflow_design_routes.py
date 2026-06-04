"""WorkflowDesignDraft routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .api_models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftPlanRequest,
    WorkflowDesignDraftUpdateRequest,
)
from .workflow_design_service import (
    compile_workflow_design_draft_from_request,
    create_workflow_design_draft_response_from_request,
    delete_workflow_design_draft_from_request,
    fork_workflow_design_draft_response_from_request,
    get_workflow_design_draft_from_request,
    list_workflow_design_drafts_from_request,
    plan_workflow_design_draft_from_request,
    update_workflow_design_draft_response_from_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/workflow-design-drafts")
async def get_workflow_design_drafts(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_workflow_design_drafts_from_request(authorization)


@router.post("/api/v1/workflow-design-drafts", status_code=201)
async def create_workflow_design_draft_api(
    payload: WorkflowDesignDraftCreateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_workflow_design_draft_response_from_request(payload, authorization)


@router.get("/api/v1/workflow-design-drafts/{draft_id}")
async def get_workflow_design_draft_api(
    draft_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_design_draft_from_request(draft_id, authorization)


@router.patch("/api/v1/workflow-design-drafts/{draft_id}")
async def update_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftUpdateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await update_workflow_design_draft_response_from_request(
        draft_id,
        payload,
        authorization,
    )


@router.post("/api/v1/workflow-design-drafts/{draft_id}/fork", status_code=201)
async def fork_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftForkRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await fork_workflow_design_draft_response_from_request(
        draft_id,
        payload,
        authorization,
    )


@router.delete("/api/v1/workflow-design-drafts/{draft_id}")
async def delete_workflow_design_draft_api(
    draft_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await delete_workflow_design_draft_from_request(draft_id, authorization)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/plan")
async def plan_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftPlanRequest | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await plan_workflow_design_draft_from_request(draft_id, authorization)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/compile")
async def compile_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftCompileRequest | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await compile_workflow_design_draft_from_request(draft_id, authorization)
