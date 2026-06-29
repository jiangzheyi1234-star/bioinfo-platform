from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core.contracts.pipeline_remote_endpoints import PIPELINE_LIST, PIPELINE_READ
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS

from .control_service import get_pipeline_from_request, list_pipelines_from_request
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/pipelines", operation_id=REMOTE_ENDPOINTS[PIPELINE_LIST].operation_id)
async def get_pipelines(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_pipelines_from_request(authorization)


@router.get(
    "/api/v1/pipelines/{pipeline_id}",
    operation_id=REMOTE_ENDPOINTS[PIPELINE_READ].operation_id,
)
async def get_pipeline_api(pipeline_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await get_pipeline_from_request(pipeline_id, authorization)
