"""Reference database routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.models import DatabaseManifestRequest, DatabaseUpdateRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, run_runtime_payload, runtime_service
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@router.get("/api/v1/databases")
async def list_databases_api(refresh: bool = False) -> dict[str, Any]:
    return await cached_runtime_payload(
        "databases",
        30,
        runtime_service().list_databases,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
        force_refresh=refresh,
    )


@router.get("/api/v1/database-templates")
async def list_database_templates_api(refresh: bool = False) -> dict[str, Any]:
    return await cached_runtime_payload(
        "database_templates",
        60,
        runtime_service().list_database_templates,
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
        force_refresh=refresh,
    )


@router.post("/api/v1/databases", status_code=201)
async def add_database_api(payload: DatabaseManifestRequest) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(
            lambda: runtime_service().add_database(payload.model_dump(exclude_none=True))
        )
        await invalidate_response_cache("databases", "workflow_catalog")
        return result
    except RuntimeServiceError as exc:
        detail = str(exc)
        if detail.startswith("DATABASE_CANDIDATES:"):
            try:
                payload_detail = json.loads(detail.removeprefix("DATABASE_CANDIDATES:"))
            except Exception:
                payload_detail = detail
            raise HTTPException(status_code=409, detail=payload_detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/v1/databases/{database_id}")
async def delete_database_api(database_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().delete_database(database_id),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache("databases", "workflow_catalog")
    return result


@router.patch("/api/v1/databases/{database_id}")
async def update_database_api(database_id: str, payload: DatabaseUpdateRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().update_database(database_id, payload.model_dump(exclude_none=True)),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache("databases", "workflow_catalog")
    return result


@router.post("/api/v1/databases/{database_id}/check")
async def check_database_api(database_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().check_database(database_id),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache("databases")
    return result
