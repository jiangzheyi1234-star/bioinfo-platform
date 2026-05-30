"""Reference database routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from .api_models import DatabaseManifestRequest, DatabaseUpdateRequest
from .database_templates import list_database_templates
from .databases import (
    DatabaseRegistryError,
    add_verified_reference_database,
    check_reference_database,
    list_reference_databases,
    remove_reference_database,
    update_reference_database,
)
from .route_utils import authorized_config, data_response


router = APIRouter()


def _database_registry_status_code(detail: str) -> int:
    if detail.startswith("DATABASE_CANDIDATES:"):
        return 409
    if detail == "DATABASE_NOT_FOUND":
        return 404
    return 400


@router.get("/api/v1/databases")
async def get_databases(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    return data_response({"items": list_reference_databases(cfg)})


@router.get("/api/v1/database-templates")
async def get_database_templates(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorized_config(authorization)
    return data_response({"items": list_database_templates()})


@router.post("/api/v1/databases", status_code=201)
async def add_database(payload: DatabaseManifestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = await run_in_threadpool(add_verified_reference_database, cfg, payload.model_dump(exclude_none=True))
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_database_registry_status_code(detail), detail=detail) from exc
    return data_response(item)


@router.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        remove_reference_database(cfg, database_id)
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_database_registry_status_code(detail), detail=detail) from exc
    return data_response({"id": database_id, "deleted": True})


@router.patch("/api/v1/databases/{database_id}")
async def update_database_api(database_id: str, payload: DatabaseUpdateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = update_reference_database(cfg, database_id, payload.model_dump(exclude_none=True))
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_database_registry_status_code(detail), detail=detail) from exc
    return data_response(item)


@router.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = await run_in_threadpool(check_reference_database, cfg, database_id)
    except DatabaseRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_database_registry_status_code(detail), detail=detail) from exc
    return data_response(item)
