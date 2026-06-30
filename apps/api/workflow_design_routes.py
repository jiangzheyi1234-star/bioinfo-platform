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
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status
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


router = APIRouter()


@router.get(
    "/api/v1/workflow-design-drafts",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_LIST].operation_id,
)
async def list_workflow_design_drafts_api(
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_workflow_design_drafts_from_request(
        refresh=refresh,
        server_id=serverId,
    )


@router.post(
    "/api/v1/workflow-design-drafts",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_CREATE].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_CREATE),
)
async def create_workflow_design_draft_api(
    payload: WorkflowDesignDraftCreateRequest,
) -> dict[str, Any]:
    return await create_workflow_design_draft_from_request(payload)


@router.get(
    "/api/v1/workflow-design-drafts/{draft_id}",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_READ].operation_id,
)
async def get_workflow_design_draft_api(
    draft_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await get_workflow_design_draft_from_request(
        draft_id,
        server_id=serverId,
    )


@router.patch(
    "/api/v1/workflow-design-drafts/{draft_id}",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_UPDATE].operation_id,
)
async def update_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    return await update_workflow_design_draft_from_request(draft_id, payload)


@router.post(
    "/api/v1/workflow-design-drafts/{draft_id}/fork",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_FORK].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_FORK),
)
async def fork_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    return await fork_workflow_design_draft_from_request(draft_id, payload)


@router.delete(
    "/api/v1/workflow-design-drafts/{draft_id}",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_DELETE].operation_id,
)
async def delete_workflow_design_draft_api(
    draft_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await delete_workflow_design_draft_from_request(draft_id, server_id=serverId)


@router.post(
    "/api/v1/workflow-design-drafts/{draft_id}/plan",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_PLAN].operation_id,
)
async def plan_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftPlanRequest | None = None,
) -> dict[str, Any]:
    return await plan_workflow_design_draft_from_request(draft_id, payload)


@router.post(
    "/api/v1/workflow-design-drafts/{draft_id}/compile",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_COMPILE].operation_id,
)
async def compile_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftCompileRequest | None = None,
) -> dict[str, Any]:
    return await compile_workflow_design_draft_from_request(draft_id, payload)
