"""System metadata routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.system_service import health_from_request, service_info_from_request, version_from_request

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return await health_from_request()


@router.get("/api/v1/version")
async def get_version() -> dict[str, Any]:
    return await version_from_request()


@router.get("/api/v1/service-info")
async def get_service_info() -> dict[str, Any]:
    return await service_info_from_request()
