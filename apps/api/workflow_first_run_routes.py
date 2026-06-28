from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.workflow_first_run_service import build_first_run_validation_card_from_request


router = APIRouter()


@router.get("/api/v1/first-run/runs/{run_id}/validation-card")
async def get_first_run_validation_card(
    run_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await build_first_run_validation_card_from_request(run_id, server_id=serverId)
