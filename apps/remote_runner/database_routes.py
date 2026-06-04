"""Reference database routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .api_models import DatabaseManifestRequest, DatabaseUpdateRequest
from .database_service import (
    add_database_from_request,
    check_database_from_request,
    delete_database_from_request,
    list_database_templates_from_request,
    list_databases_from_request,
    update_database_from_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/databases")
async def get_databases(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_databases_from_request(authorization)


@router.get("/api/v1/database-templates")
async def get_database_templates(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_database_templates_from_request(authorization)


@router.post("/api/v1/databases", status_code=201)
async def add_database(payload: DatabaseManifestRequest, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await add_database_from_request(payload, authorization)


@router.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await delete_database_from_request(database_id, authorization)


@router.patch("/api/v1/databases/{database_id}")
async def update_database_api(
    database_id: str,
    payload: DatabaseUpdateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await update_database_from_request(database_id, payload, authorization)


@router.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str, authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await check_database_from_request(database_id, authorization)
