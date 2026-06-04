from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .control_service import (
    health_live_from_request,
    health_meta_from_request,
    health_ready_from_request,
    health_startup_from_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/health/startup")
async def health_startup(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_startup_from_request(authorization)


@router.get("/health/live")
async def health_live(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_live_from_request(authorization)


@router.get("/health/ready")
async def health_ready(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_ready_from_request(authorization)


@router.get("/health/meta")
async def health_meta(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_meta_from_request(authorization)
