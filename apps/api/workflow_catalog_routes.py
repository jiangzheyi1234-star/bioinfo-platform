"""Frontend-oriented workflow catalog and run detail routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.workflow_catalog_service import (
    get_run_detail_from_request,
    get_workflow_catalog_from_request,
)


router = APIRouter()


@router.get("/api/v1/workflow-catalog")
async def get_workflow_catalog(refresh: bool = False) -> dict[str, Any]:
    return await get_workflow_catalog_from_request(refresh)


@router.get("/api/v1/runs/{run_id}/detail")
async def get_run_detail(run_id: str, refresh: bool = False) -> dict[str, Any]:
    return await get_run_detail_from_request(run_id, refresh)
