"""FastAPI routes for online and local tool capability search."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from apps.api.bioconda_tool_index import bioconda_index_status, refresh_bioconda_index
from apps.api.tool_capabilities import search_tool_capabilities


router = APIRouter()


async def _run_sync(func, *, status_code: int, handled_errors: tuple[type[Exception], ...]):
    try:
        return await asyncio.to_thread(func)
    except handled_errors as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _refresh_bioconda_index_status() -> dict[str, Any]:
    refresh_bioconda_index()
    return {"data": bioconda_index_status()}


@router.get("/api/v1/tool-capabilities/search")
async def search_tool_capabilities_api(
    q: str = "",
    limit: int = 20,
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    try:
        bounded_page = max(1, int(page))
        bounded_page_size = max(1, min(int(pageSize or limit), 50))
        return await _run_sync(
            lambda: search_tool_capabilities(q, limit=bounded_page_size, page=bounded_page, page_size=bounded_page_size),
            status_code=502,
            handled_errors=(ValueError, TimeoutError, OSError),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/tool-capabilities/index/status")
async def tool_capabilities_index_status_api() -> dict[str, Any]:
    return {"data": bioconda_index_status()}


@router.post("/api/v1/tool-capabilities/index/refresh")
async def refresh_tool_capabilities_index_api() -> dict[str, Any]:
    return await _run_sync(
        _refresh_bioconda_index_status,
        status_code=502,
        handled_errors=(OSError, TimeoutError, ValueError),
    )
