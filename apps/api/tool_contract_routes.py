"""Local API routes for tool contract state transitions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import ToolProductionEvidenceRequest
from apps.api.tool_contract_service import mark_tool_production_from_request


router = APIRouter()


@router.post("/api/v1/tools/{tool_id}/production")
async def mark_tool_production_api(tool_id: str, payload: ToolProductionEvidenceRequest) -> dict[str, Any]:
    return await mark_tool_production_from_request(tool_id, payload)
