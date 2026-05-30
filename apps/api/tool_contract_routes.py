"""Local API routes for tool contract state transitions."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.models import ToolProductionEvidenceRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.runtime import get_runtime_service
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@router.post("/api/v1/tools/{tool_id}/production")
async def mark_tool_production_api(tool_id: str, payload: ToolProductionEvidenceRequest) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    try:
        value = await asyncio.to_thread(get_runtime_service().mark_tool_production_enabled, tool_id, body)
    except RuntimeServiceError as exc:
        detail = str(exc)
        if detail == "TOOL_NOT_FOUND":
            status_code = 404
        elif detail in {
            "TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION",
            "TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY",
            "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND",
            "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_COMPLETED",
            "TOOL_PRODUCTION_EVIDENCE_PIPELINE_MISMATCH",
            "TOOL_PRODUCTION_EVIDENCE_TOOL_MISMATCH",
            "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_REQUIRED",
            "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_NOT_FOUND",
            "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_EMPTY",
            "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH",
            "TOOL_PRODUCTION_EVIDENCE_DATABASE_UNAVAILABLE",
        }:
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    await invalidate_response_cache("tools", "workflow_catalog")
    return value if isinstance(value, dict) and "data" in value else {"data": value}
