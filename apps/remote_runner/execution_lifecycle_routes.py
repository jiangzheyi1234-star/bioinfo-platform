from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core.contracts.remote_endpoints import (
    EXECUTION_LIFECYCLE_GUARD,
    EXECUTION_LIFECYCLE_GUARD_RELEASE,
    REMOTE_ENDPOINTS,
)

from .api_models import ExecutionLifecycleGuardReleaseRequest, ExecutionLifecycleGuardRequest
from .execution_lifecycle_service import (
    release_execution_lifecycle_guard_from_request,
    request_execution_lifecycle_guard_from_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.post(
    "/api/v1/execution/lifecycle-guard",
    operation_id=REMOTE_ENDPOINTS[EXECUTION_LIFECYCLE_GUARD].operation_id,
)
async def request_lifecycle_guard(
    payload: ExecutionLifecycleGuardRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await request_execution_lifecycle_guard_from_request(payload, authorization)


@router.post(
    "/api/v1/execution/lifecycle-guard/release",
    operation_id=REMOTE_ENDPOINTS[EXECUTION_LIFECYCLE_GUARD_RELEASE].operation_id,
)
async def release_lifecycle_guard(
    payload: ExecutionLifecycleGuardReleaseRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await release_execution_lifecycle_guard_from_request(payload, authorization)
