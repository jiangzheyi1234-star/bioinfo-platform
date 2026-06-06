"""Tool registry routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks

from .api_models import ToolManifestRequest, ToolProductionEvidenceRequest, ToolRuleTemplateRequest
from .route_headers import AuthorizationHeader
from .tool_service import (
    add_tool_from_request,
    cancel_tool_prepare_job_from_request,
    create_tool_prepare_job_response_from_request,
    delete_tool_from_request,
    get_tool_prepare_job_from_request,
    list_latest_tool_prepare_jobs_from_request,
    list_tools_from_request,
    mark_tool_production_from_request,
    update_tool_rule_template_from_request,
)


router = APIRouter()


@router.get("/api/v1/tools")
async def get_tools(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_tools_from_request(authorization)


@router.post("/api/v1/tools", status_code=201)
async def add_tool(payload: ToolManifestRequest, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await add_tool_from_request(payload, authorization)


@router.post("/api/v1/tools/prepare-jobs", status_code=202)
async def create_prepare_job(
    payload: ToolManifestRequest,
    background_tasks: BackgroundTasks,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_tool_prepare_job_response_from_request(
        payload,
        background_tasks,
        authorization,
    )


@router.get("/api/v1/tools/prepare-jobs")
async def list_latest_prepare_jobs(toolIds: str = "", authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_latest_tool_prepare_jobs_from_request(toolIds, authorization)


@router.get("/api/v1/tools/prepare-jobs/{job_id}")
async def get_prepare_job(job_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_tool_prepare_job_from_request(job_id, authorization)


@router.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")
async def cancel_prepare_job(job_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await cancel_tool_prepare_job_from_request(job_id, authorization)


@router.patch("/api/v1/tools/{tool_id}/rule-template")
async def update_tool_rule_template_api(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await update_tool_rule_template_from_request(tool_id, payload, authorization)


@router.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await delete_tool_from_request(tool_id, authorization)


@router.post("/api/v1/tools/{tool_id}/production")
async def mark_tool_production_api(
    tool_id: str,
    payload: ToolProductionEvidenceRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await mark_tool_production_from_request(tool_id, payload, authorization)
