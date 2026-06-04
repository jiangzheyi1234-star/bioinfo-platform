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
    list_tools_from_request,
    update_tool_rule_template_from_request,
)


router = APIRouter()


@router.get("/api/v1/tools")
async def list_tools_api(refresh: bool = False) -> dict[str, Any]:
    return await list_tools_from_request(refresh)


@router.post("/api/v1/tools", status_code=201)
async def add_tool_api(payload: ToolManifestRequest) -> dict[str, Any]:
    return await add_tool_from_request(payload)


@router.post("/api/v1/tools/prepare-jobs", status_code=202)
async def create_tool_prepare_job_api(payload: ToolManifestRequest) -> dict[str, Any]:
    return await create_tool_prepare_job_from_request(payload)


@router.get("/api/v1/tools/prepare-jobs/{job_id}")
async def get_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    return await get_tool_prepare_job_from_request(job_id)


@router.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")
async def cancel_tool_prepare_job_api(job_id: str) -> dict[str, Any]:
    return await cancel_tool_prepare_job_from_request(job_id)


@router.patch("/api/v1/tools/{tool_id}/rule-template")
async def update_tool_rule_template_api(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
) -> dict[str, Any]:
    return await update_tool_rule_template_from_request(tool_id, payload)


@router.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str) -> dict[str, Any]:
    return await delete_tool_from_request(tool_id)
