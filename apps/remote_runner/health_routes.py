from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    RUNNER_HEALTH_EXECUTION_DIAGNOSTICS,
    RUNNER_HEALTH_LIVE,
    RUNNER_HEALTH_META,
    RUNNER_HEALTH_READY,
    RUNNER_HEALTH_STARTUP,
    RUNNER_HEALTH_WORKERS,
)

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


@router.get("/health/startup", operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_STARTUP].operation_id)
async def health_startup(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_startup_from_request(authorization), response=response)


@router.get("/health/live", operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_LIVE].operation_id)
async def health_live(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_live_from_request(authorization), response=response)


@router.get("/health/ready", operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_READY].operation_id)
async def health_ready(
    response: Response,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return _with_probe_status(await health_ready_from_request(authorization), response=response)


@router.get("/health/meta", operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_META].operation_id)
async def health_meta(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_meta_from_request(authorization)


@router.get("/health/workers", operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_WORKERS].operation_id)
async def health_workers(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await health_workers_from_request(authorization)


@router.get(
    "/health/execution-diagnostics",
    operation_id=REMOTE_ENDPOINTS[RUNNER_HEALTH_EXECUTION_DIAGNOSTICS].operation_id,
)
async def health_execution_diagnostics(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await execution_diagnostics_from_request(authorization)


def _with_probe_status(payload: dict[str, Any], *, response: Response | None) -> dict[str, Any]:
    if response is not None:
        response.status_code = 200 if payload.get("status") == "ok" else 503
    return payload
