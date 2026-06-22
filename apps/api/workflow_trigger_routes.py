"""Workflow trigger routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from apps.api.models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest
from apps.api.workflow_trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_events_from_request,
    list_workflow_triggers_from_request,
    submit_workflow_trigger_event_response_from_request,
)


router = APIRouter()


@router.get("/api/v1/workflow-triggers")
async def list_workflow_triggers(
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_workflow_triggers_from_request(
        refresh=refresh,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-triggers", status_code=201)
async def create_workflow_trigger(payload: WorkflowTriggerCreateRequest) -> dict[str, Any]:
    return await create_workflow_trigger_from_request(payload)


@router.get("/api/v1/workflow-triggers/{trigger_id}/events")
async def list_workflow_trigger_events(
    trigger_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_workflow_trigger_events_from_request(
        trigger_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-triggers/{trigger_id}/events", status_code=202)
async def submit_workflow_trigger_event(
    trigger_id: str,
    payload: WorkflowTriggerEventRequest,
    response: Response,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_event_response_from_request(
        trigger_id,
        payload,
        response,
        server_id=serverId,
    )
