from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, RUN_CREATE, UPLOAD_CREATE, remote_endpoint_success_status

from .api_models import RunCreateRequest, UploadCreateRequest
from .control_service import create_run_from_request, create_upload_from_request
from .route_headers import AuthorizationHeader, IdempotencyKeyHeader, RequestIdHeader


router = APIRouter()


@router.post("/api/v1/uploads", operation_id=REMOTE_ENDPOINTS[UPLOAD_CREATE].operation_id)
async def create_upload(
    payload: UploadCreateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_upload_from_request(payload, authorization)


@router.post(
    "/api/v1/runs",
    operation_id=REMOTE_ENDPOINTS[RUN_CREATE].operation_id,
    status_code=remote_endpoint_success_status(RUN_CREATE),
)
async def create_run(
    payload: RunCreateRequest,
    authorization: AuthorizationHeader = None,
    idempotency_key: IdempotencyKeyHeader = None,
    x_request_id: RequestIdHeader = None,
) -> dict[str, Any]:
    return await create_run_from_request(
        payload,
        authorization,
        idempotency_key=idempotency_key,
        x_request_id=x_request_id,
    )
