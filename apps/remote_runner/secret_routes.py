from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .route_headers import AuthorizationHeader
from .secret_service import get_secret_provider_readiness_request


router = APIRouter()


@router.get("/api/v1/secrets/provider-readiness")
async def get_secret_provider_readiness_api(
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_secret_provider_readiness_request(authorization)
