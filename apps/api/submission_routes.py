"""Upload and run submission routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from apps.api.models import RunSubmitRequest, UploadSubmitRequest
from apps.api.submission_service import (
    submit_run_response_from_request,
    upload_file_from_request,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, RUN_CREATE


router = APIRouter()


@router.post("/api/v1/uploads")
async def upload_file(payload: UploadSubmitRequest) -> dict[str, Any]:
    return await upload_file_from_request(payload)


@router.post(
    "/api/v1/runs",
    operation_id=REMOTE_ENDPOINTS[RUN_CREATE].operation_id,
    status_code=202,
)
async def submit_run(payload: RunSubmitRequest, response: Response) -> dict[str, Any]:
    return await submit_run_response_from_request(payload, response)
