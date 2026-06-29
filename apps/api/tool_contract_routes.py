"""Local API routes for tool contract state transitions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import ToolProductionEvidenceRequest
from apps.api.tool_contract_service import mark_tool_production_from_request
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS
from core.contracts.tool_remote_endpoints import TOOL_PRODUCTION_ENABLE


router = APIRouter()


@router.post(
    "/api/v1/tools/{tool_id}/production",
    operation_id=REMOTE_ENDPOINTS[TOOL_PRODUCTION_ENABLE].operation_id,
)
async def mark_tool_production_api(tool_id: str, payload: ToolProductionEvidenceRequest) -> dict[str, Any]:
    return await mark_tool_production_from_request(tool_id, payload)
