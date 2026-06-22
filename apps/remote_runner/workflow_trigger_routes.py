from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .api_models import (
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerReadinessEventRequest,
)
from .control_service import (
    create_workflow_trigger_request,
    list_workflow_trigger_events_request,
    list_workflow_triggers_request,
    preview_workflow_trigger_backfill_request,
    submit_workflow_trigger_event_request,
    submit_workflow_trigger_inbox_event_request,
    submit_workflow_trigger_readiness_event_request,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/workflow-triggers")
async def list_workflow_triggers(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_workflow_triggers_request(authorization)


@router.post("/api/v1/workflow-triggers", status_code=201)
async def create_workflow_trigger(
    payload: WorkflowTriggerCreateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_workflow_trigger_request(payload, authorization)


@router.get("/api/v1/workflow-triggers/{trigger_id}/events")
async def list_workflow_trigger_events(
    trigger_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_workflow_trigger_events_request(trigger_id, authorization)


@router.post("/api/v1/workflow-triggers/{trigger_id}/events", status_code=202)
async def submit_workflow_trigger_event(
    trigger_id: str,
    payload: WorkflowTriggerEventRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_event_request(trigger_id, payload, authorization)


@router.post("/api/v1/workflow-triggers/{trigger_id}/inbox", status_code=202)
async def submit_workflow_trigger_inbox_event(
    trigger_id: str,
    payload: WorkflowTriggerInboxEventRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_inbox_event_request(trigger_id, payload, authorization)


@router.post("/api/v1/workflow-triggers/{trigger_id}/readiness", status_code=202)
async def submit_workflow_trigger_readiness_event(
    trigger_id: str,
    payload: WorkflowTriggerReadinessEventRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_readiness_event_request(trigger_id, payload, authorization)


@router.post("/api/v1/workflow-triggers/{trigger_id}/backfill/preview")
async def preview_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillPreviewRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await preview_workflow_trigger_backfill_request(trigger_id, payload, authorization)
