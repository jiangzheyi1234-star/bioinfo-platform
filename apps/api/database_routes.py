"""Reference database routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.database_service import (
    add_database_from_request,
    check_database_from_request,
    delete_database_from_request,
    list_database_packs_from_request,
    list_database_templates_from_request,
    list_databases_from_request,
    update_database_from_request,
)
from apps.api.models import DatabaseManifestRequest, DatabaseUpdateRequest


router = APIRouter()


@router.get("/api/v1/databases")
async def list_databases_api(refresh: bool = False) -> dict[str, Any]:
    return await list_databases_from_request(refresh)


@router.get("/api/v1/database-templates")
async def list_database_templates_api(refresh: bool = False) -> dict[str, Any]:
    return await list_database_templates_from_request(refresh)


@router.get("/api/v1/database-packs")
async def list_database_packs_api(refresh: bool = False) -> dict[str, Any]:
    return await list_database_packs_from_request(refresh)


@router.post("/api/v1/databases", status_code=201)
async def add_database_api(payload: DatabaseManifestRequest) -> dict[str, Any]:
    return await add_database_from_request(payload)


@router.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str) -> dict[str, Any]:
    return await delete_database_from_request(database_id)


@router.patch("/api/v1/databases/{database_id}")
async def update_database_api(
    database_id: str,
    payload: DatabaseUpdateRequest,
) -> dict[str, Any]:
    return await update_database_from_request(database_id, payload)


@router.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str) -> dict[str, Any]:
    return await check_database_from_request(database_id)
