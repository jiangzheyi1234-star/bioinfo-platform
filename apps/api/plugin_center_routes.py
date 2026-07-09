from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.plugin_center_service import list_plugin_center_extensions_from_request


router = APIRouter()


@router.get("/api/v1/plugin-center/extensions")
async def list_plugin_center_extensions() -> dict[str, Any]:
    return await list_plugin_center_extensions_from_request()
