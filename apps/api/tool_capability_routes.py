"""FastAPI routes for online and local tool capability search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.api.tool_capability_service import (
    get_tool_capabilities_index_status_from_request,
    refresh_tool_capabilities_index_from_request,
    search_tool_capabilities_from_request,
)


router = APIRouter()


@router.get("/api/v1/tool-capabilities/search")
async def search_tool_capabilities_api(
    q: str = "",
    targetPlatform: str = "",
    limit: int = Query(default=20, ge=1, le=50),
    page: int = Query(default=1, ge=1),
    pageSize: int | None = Query(default=None, ge=1, le=50),
) -> dict[str, Any]:
    return await search_tool_capabilities_from_request(
        q=q,
        target_platform=targetPlatform,
        limit=limit,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/index/status")
async def tool_capabilities_index_status_api() -> dict[str, Any]:
    return await get_tool_capabilities_index_status_from_request()


@router.post("/api/v1/tool-capabilities/index/refresh")
async def refresh_tool_capabilities_index_api() -> dict[str, Any]:
    return await refresh_tool_capabilities_index_from_request()
