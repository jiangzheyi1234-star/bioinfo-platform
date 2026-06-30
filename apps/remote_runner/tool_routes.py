"""Tool registry routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status
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

from .api_models import ToolManifestRequest, ToolProductionEvidenceRequest, ToolRuleTemplateRequest
from .route_headers import AuthorizationHeader
from .tool_service import (
    add_tool_from_request,
    cancel_tool_prepare_job_from_request,
    create_tool_prepare_job_response_from_request,
    delete_tool_from_request,
    get_tool_prepare_job_from_request,
    list_latest_tool_prepare_jobs_from_request,
    list_tool_prepare_job_queue_from_request,
    list_tool_index_from_request,
    list_tools_from_request,
    mark_tool_production_from_request,
    update_tool_rule_template_from_request,
)


router = APIRouter()


@router.get("/api/v1/tools", operation_id=REMOTE_ENDPOINTS[TOOL_LIST].operation_id)
async def get_tools(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_tools_from_request(authorization)


@router.get("/api/v1/tools/index", operation_id=REMOTE_ENDPOINTS[TOOL_INDEX_READ].operation_id)
async def get_tool_index(
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
    state: str | None = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_tool_index_from_request(
        authorization,
        query=query,
        limit=limit,
        offset=offset,
        source=source,
        state=state,
    )


@router.post(
    "/api/v1/tools",
    status_code=remote_endpoint_success_status(TOOL_CREATE),
    operation_id=REMOTE_ENDPOINTS[TOOL_CREATE].operation_id,
)
async def add_tool(payload: ToolManifestRequest, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await add_tool_from_request(payload, authorization)


@router.post(
    "/api/v1/tools/prepare-jobs",
    status_code=remote_endpoint_success_status(TOOL_PREPARE_JOB_CREATE),
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].operation_id,
)
async def create_prepare_job(
    payload: ToolManifestRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_tool_prepare_job_response_from_request(
        payload,
        authorization,
    )


@router.get("/api/v1/tools/prepare-jobs", operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_LATEST_READ].operation_id)
async def list_latest_prepare_jobs(toolIds: str = "", authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_latest_tool_prepare_jobs_from_request(toolIds, authorization)


@router.get(
    "/api/v1/tools/prepare-jobs/queue",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].operation_id,
)
async def list_prepare_job_queue(
    status: str = "",
    limit: int = 50,
    offset: int = 0,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_tool_prepare_job_queue_from_request(
        authorization,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/tools/prepare-jobs/{job_id}",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_READ].operation_id,
)
async def get_prepare_job(job_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_tool_prepare_job_from_request(job_id, authorization)


@router.post(
    "/api/v1/tools/prepare-jobs/{job_id}/cancel",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CANCEL].operation_id,
)
async def cancel_prepare_job(job_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await cancel_tool_prepare_job_from_request(job_id, authorization)


@router.patch(
    "/api/v1/tools/{tool_id}/rule-template",
    operation_id=REMOTE_ENDPOINTS[TOOL_RULE_TEMPLATE_UPDATE].operation_id,
)
async def update_tool_rule_template_api(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await update_tool_rule_template_from_request(tool_id, payload, authorization)


@router.delete("/api/v1/tools/{tool_id}", operation_id=REMOTE_ENDPOINTS[TOOL_DELETE].operation_id)
async def delete_tool_api(tool_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await delete_tool_from_request(tool_id, authorization)


@router.post(
    "/api/v1/tools/{tool_id}/production",
    operation_id=REMOTE_ENDPOINTS[TOOL_PRODUCTION_ENABLE].operation_id,
)
async def mark_tool_production_api(
    tool_id: str,
    payload: ToolProductionEvidenceRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await mark_tool_production_from_request(tool_id, payload, authorization)
