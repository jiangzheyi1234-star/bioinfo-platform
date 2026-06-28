from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.workflow_scenario_pack_service import list_workflow_scenario_packs


router = APIRouter()


@router.get("/api/v1/workflow-scenario-packs")
async def list_workflow_scenario_packs_api() -> dict[str, Any]:
    return list_workflow_scenario_packs()
