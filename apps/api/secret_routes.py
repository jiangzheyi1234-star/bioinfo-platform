"""Secret provider readiness routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.secret_service import get_secret_provider_readiness_from_request
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, SECRET_PROVIDER_READINESS_READ


router = APIRouter()


@router.get(
    "/api/v1/secrets/provider-readiness",
    operation_id=REMOTE_ENDPOINTS[SECRET_PROVIDER_READINESS_READ].operation_id,
)
async def get_secret_provider_readiness(serverId: str | None = None) -> dict[str, Any]:
    return await get_secret_provider_readiness_from_request(server_id=serverId)
