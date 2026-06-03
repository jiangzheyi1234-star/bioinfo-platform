"""Local API routes for tool contract state transitions."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.models import ToolProductionEvidenceRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.runtime import get_runtime_service
from apps.remote_runner.tool_route_status import tool_production_status_code
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@router.post("/api/v1/tools/{tool_id}/production")
async def mark_tool_production_api(tool_id: str, payload: ToolProductionEvidenceRequest) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    try:
        value = await asyncio.to_thread(get_runtime_service().mark_tool_production_enabled, tool_id, body)
    except RuntimeServiceError as exc:
        detail = str(exc)
        raise HTTPException(status_code=tool_production_status_code(detail), detail=detail) from exc
    await invalidate_response_cache("tools", "workflow_catalog")
    return value if isinstance(value, dict) and "data" in value else {"data": value}
