"""Workflow trigger routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from apps.api.models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerReadinessEventRequest,
)
from apps.api.workflow_trigger_service import (
    cancel_workflow_backfill_launch_from_request,
    create_workflow_trigger_from_request,
    get_workflow_backfill_launch_from_request,
    list_workflow_backfill_launches_from_request,
    list_workflow_trigger_events_from_request,
    list_workflow_triggers_from_request,
    launch_workflow_trigger_backfill_from_request,
    preview_workflow_trigger_backfill_from_request,
    submit_workflow_trigger_event_response_from_request,
    submit_workflow_trigger_inbox_event_response_from_request,
    submit_workflow_trigger_readiness_event_response_from_request,
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


@router.get("/api/v1/workflow-backfill-launches")
async def list_workflow_backfill_launches(
    refresh: bool = False,
    serverId: str | None = None,
    triggerId: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return await list_workflow_backfill_launches_from_request(
        refresh=refresh,
        server_id=serverId,
        trigger_id=triggerId,
        limit=limit,
    )


@router.get("/api/v1/workflow-backfill-launches/{launch_id}")
async def get_workflow_backfill_launch(
    launch_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await get_workflow_backfill_launch_from_request(
        launch_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-backfill-launches/{launch_id}/cancel", status_code=202)
async def cancel_workflow_backfill_launch(
    launch_id: str,
    payload: WorkflowBackfillCancelRequest,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await cancel_workflow_backfill_launch_from_request(
        launch_id,
        payload,
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


@router.post("/api/v1/workflow-triggers/{trigger_id}/inbox", status_code=202)
async def submit_workflow_trigger_inbox_event(
    trigger_id: str,
    payload: WorkflowTriggerInboxEventRequest,
    response: Response,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_inbox_event_response_from_request(
        trigger_id,
        payload,
        response,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-triggers/{trigger_id}/readiness", status_code=202)
async def submit_workflow_trigger_readiness_event(
    trigger_id: str,
    payload: WorkflowTriggerReadinessEventRequest,
    response: Response,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_readiness_event_response_from_request(
        trigger_id,
        payload,
        response,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-triggers/{trigger_id}/backfill/preview")
async def preview_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillPreviewRequest,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await preview_workflow_trigger_backfill_from_request(
        trigger_id,
        payload,
        server_id=serverId,
    )


@router.post("/api/v1/workflow-triggers/{trigger_id}/backfill/launch", status_code=202)
async def launch_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillLaunchRequest,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await launch_workflow_trigger_backfill_from_request(
        trigger_id,
        payload,
        server_id=serverId,
    )
