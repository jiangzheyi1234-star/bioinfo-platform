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
    scan_database_pack_ready_from_request,
    update_database_from_request,
)
from apps.api.models import DatabaseManifestRequest, DatabasePackReadyScanRequest, DatabaseUpdateRequest
from core.contracts.database_remote_endpoints import (
    DATABASE_CHECK,
    DATABASE_CREATE,
    DATABASE_DELETE,
    DATABASE_LIST,
    DATABASE_PACK_LIST,
    DATABASE_PACK_READY_SCAN,
    DATABASE_TEMPLATE_LIST,
    DATABASE_UPDATE,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS


router = APIRouter()


@router.get("/api/v1/databases", operation_id=REMOTE_ENDPOINTS[DATABASE_LIST].operation_id)
async def list_databases_api(refresh: bool = False) -> dict[str, Any]:
    return await list_databases_from_request(refresh)


@router.get("/api/v1/database-templates", operation_id=REMOTE_ENDPOINTS[DATABASE_TEMPLATE_LIST].operation_id)
async def list_database_templates_api(refresh: bool = False) -> dict[str, Any]:
    return await list_database_templates_from_request(refresh)


@router.get("/api/v1/database-packs", operation_id=REMOTE_ENDPOINTS[DATABASE_PACK_LIST].operation_id)
async def list_database_packs_api(refresh: bool = False) -> dict[str, Any]:
    return await list_database_packs_from_request(refresh)


@router.post(
    "/api/v1/database-pack-ready-scans",
    operation_id=REMOTE_ENDPOINTS[DATABASE_PACK_READY_SCAN].operation_id,
)
async def scan_database_pack_ready_api(payload: DatabasePackReadyScanRequest) -> dict[str, Any]:
    return await scan_database_pack_ready_from_request(payload)


@router.post("/api/v1/databases", status_code=201, operation_id=REMOTE_ENDPOINTS[DATABASE_CREATE].operation_id)
async def add_database_api(payload: DatabaseManifestRequest) -> dict[str, Any]:
    return await add_database_from_request(payload)


@router.delete("/api/v1/databases/{database_id}", operation_id=REMOTE_ENDPOINTS[DATABASE_DELETE].operation_id)
async def delete_database_api(database_id: str) -> dict[str, Any]:
    return await delete_database_from_request(database_id)


@router.patch("/api/v1/databases/{database_id}", operation_id=REMOTE_ENDPOINTS[DATABASE_UPDATE].operation_id)
async def update_database_api(
    database_id: str,
    payload: DatabaseUpdateRequest,
) -> dict[str, Any]:
    return await update_database_from_request(database_id, payload)


@router.post("/api/v1/databases/{database_id}/check", operation_id=REMOTE_ENDPOINTS[DATABASE_CHECK].operation_id)
async def check_database_api(database_id: str) -> dict[str, Any]:
    return await check_database_from_request(database_id)
