"""Secret provider readiness routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.secret_service import get_secret_provider_readiness_from_request


router = APIRouter()


@router.get("/api/v1/secrets/provider-readiness")
async def get_secret_provider_readiness(serverId: str | None = None) -> dict[str, Any]:
    return await get_secret_provider_readiness_from_request(server_id=serverId)
