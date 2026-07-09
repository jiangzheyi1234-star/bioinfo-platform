from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import ManagedExtensionActionRequest
from apps.api.plugin_center_service import (
    execute_plugin_center_extension_action_from_request,
    list_plugin_center_extensions_from_request,
)


router = APIRouter()


@router.get("/api/v1/plugin-center/extensions")
async def list_plugin_center_extensions() -> dict[str, Any]:
    return await list_plugin_center_extensions_from_request()


@router.post("/api/v1/plugin-center/extensions/{extension_id}/actions")
async def execute_plugin_center_extension_action(
    extension_id: str,
    payload: ManagedExtensionActionRequest,
) -> dict[str, Any]:
    return await execute_plugin_center_extension_action_from_request(extension_id, payload)
