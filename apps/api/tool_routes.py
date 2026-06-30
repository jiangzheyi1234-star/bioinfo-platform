"""Tool registry routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import ToolManifestRequest, ToolRuleTemplateRequest
from apps.api.tool_service import (
    add_tool_from_request,
    cancel_tool_prepare_job_from_request,
    create_tool_prepare_job_from_request,
    delete_tool_from_request,
    get_tool_prepare_job_from_request,
    list_tool_index_from_request,
    list_tool_prepare_job_queue_from_request,
    list_tools_from_request,
    update_tool_rule_template_from_request,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status
from core.contracts.tool_remote_endpoints import (
    TOOL_CREATE,
    TOOL_INDEX_READ,
    TOOL_LIST,
    TOOL_PREPARE_JOB_CANCEL,
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
    TOOL_RULE_TEMPLATE_UPDATE,
    TOOL_DELETE,
)


router = APIRouter()


@router.get("/api/v1/tools", operation_id=REMOTE_ENDPOINTS[TOOL_LIST].operation_id)
async def list_tools_api(refresh: bool = False) -> dict[str, Any]:
    return await list_tools_from_request(refresh)


@router.get("/api/v1/tools/index", operation_id=REMOTE_ENDPOINTS[TOOL_INDEX_READ].operation_id)
async def list_tool_index_api(
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
    state: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    return await list_tool_index_from_request(
        query=query,
        limit=limit,
        offset=offset,
        source=source,
        state=state,
        refresh=refresh,
    )


@router.post(
    "/api/v1/tools",
    status_code=remote_endpoint_success_status(TOOL_CREATE),
    operation_id=REMOTE_ENDPOINTS[TOOL_CREATE].operation_id,
)
async def add_tool_api(payload: ToolManifestRequest) -> dict[str, Any]:
    return await add_tool_from_request(payload)


@router.post(
    "/api/v1/tools/prepare-jobs",
    status_code=remote_endpoint_success_status(TOOL_PREPARE_JOB_CREATE),
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].operation_id,
)
async def create_tool_prepare_job_api(payload: ToolManifestRequest) -> dict[str, Any]:
    return await create_tool_prepare_job_from_request(payload)


@router.get(
    "/api/v1/tools/prepare-jobs/queue",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].operation_id,
)
async def list_tool_prepare_job_queue_api(
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    return await list_tool_prepare_job_queue_from_request(
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/v1/tools/prepare-jobs/{job_id}",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_READ].operation_id,
)
async def get_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    return await get_tool_prepare_job_from_request(job_id)


@router.post(
    "/api/v1/tools/prepare-jobs/{job_id}/cancel",
    operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CANCEL].operation_id,
)
async def cancel_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    return await cancel_tool_prepare_job_from_request(job_id)


@router.patch(
    "/api/v1/tools/{tool_id}/rule-template",
    operation_id=REMOTE_ENDPOINTS[TOOL_RULE_TEMPLATE_UPDATE].operation_id,
)
async def update_tool_rule_template_api(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
) -> dict[str, Any]:
    return await update_tool_rule_template_from_request(tool_id, payload)


@router.delete("/api/v1/tools/{tool_id}", operation_id=REMOTE_ENDPOINTS[TOOL_DELETE].operation_id)
async def delete_tool_api(tool_id: str) -> dict[str, Any]:
    return await delete_tool_from_request(tool_id)
