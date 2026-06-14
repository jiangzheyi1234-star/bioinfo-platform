from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from .control_service import (
    health_live_from_request,
    health_meta_from_request,
    health_ready_from_request,
    health_startup_from_request,
    health_workers_from_request,
    execution_diagnostics_from_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/health/startup")
async def health_startup(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_startup_from_request(authorization), response=response)


@router.get("/health/live")
async def health_live(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_live_from_request(authorization), response=response)


@router.get("/health/ready")
async def health_ready(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_ready_from_request(authorization), response=response)


@router.get("/health/meta")
async def health_meta(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_meta_from_request(authorization)


@router.get("/health/workers")
async def health_workers(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_workers_from_request(authorization)


@router.get("/health/execution-diagnostics")
async def health_execution_diagnostics(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await execution_diagnostics_from_request(authorization)


def _with_probe_status(payload: dict[str, Any], *, response: Response | None) -> dict[str, Any]:
    if response is not None:
        response.status_code = 200 if payload.get("status") == "ok" else 503
    return payload
