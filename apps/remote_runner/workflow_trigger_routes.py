from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from .api_models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxReplayRequest,
    WorkflowTriggerReadinessEventRequest,
)
from .control_service import (
    cancel_workflow_backfill_launch_request,
    create_workflow_trigger_request,
    get_workflow_backfill_launch_request,
    get_workflow_trigger_readiness_observation_request,
    list_workflow_backfill_launches_request,
    list_workflow_trigger_events_request,
    list_workflow_trigger_inbox_events_request,
    list_workflow_triggers_request,
    launch_workflow_trigger_backfill_request,
    preview_workflow_trigger_backfill_request,
    replay_workflow_trigger_inbox_event_request,
    submit_workflow_trigger_event_request,
    submit_workflow_trigger_inbox_event_envelope_request,
    submit_workflow_trigger_readiness_event_request,
)
from .route_headers import AuthorizationHeader
from .webhook_raw_request import WebhookRawRequestEnvelope, build_webhook_raw_request_envelope


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


@router.get("/api/v1/workflow-triggers/{trigger_id}/readiness-observation")
async def get_workflow_trigger_readiness_observation(
    trigger_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_trigger_readiness_observation_request(trigger_id, authorization)


@router.get("/api/v1/workflow-triggers/{trigger_id}/inbox")
async def list_workflow_trigger_inbox_events(
    trigger_id: str,
    state: str | None = None,
    limit: int = 100,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_workflow_trigger_inbox_events_request(
        trigger_id,
        authorization,
        state=state,
        limit=limit,
    )


@router.get("/api/v1/workflow-backfill-launches")
async def list_workflow_backfill_launches(
    triggerId: str | None = None,
    limit: int = 100,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_workflow_backfill_launches_request(
        authorization,
        trigger_id=triggerId,
        limit=limit,
    )


@router.get("/api/v1/workflow-backfill-launches/{launch_id}")
async def get_workflow_backfill_launch(
    launch_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_backfill_launch_request(launch_id, authorization)


@router.post("/api/v1/workflow-backfill-launches/{launch_id}/cancel", status_code=202)
async def cancel_workflow_backfill_launch(
    launch_id: str,
    payload: WorkflowBackfillCancelRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await cancel_workflow_backfill_launch_request(launch_id, payload, authorization)


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
    request: Request,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    envelope = await build_webhook_inbox_envelope_from_request(request)
    return await submit_workflow_trigger_inbox_event_envelope_request(trigger_id, envelope, authorization)


@router.post("/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay", status_code=202)
async def replay_workflow_trigger_inbox_event(
    trigger_id: str,
    inbox_event_id: str,
    payload: WorkflowTriggerInboxReplayRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await replay_workflow_trigger_inbox_event_request(
        trigger_id,
        inbox_event_id,
        payload,
        authorization,
    )


async def build_webhook_inbox_envelope_from_request(request: Request) -> WebhookRawRequestEnvelope:
    return build_webhook_raw_request_envelope(
        raw_body=await request.body(),
        headers=_request_header_items(request),
        received_at=datetime.now(timezone.utc),
    )


def _request_header_items(request: Request) -> list[tuple[str, str]]:
    return [
        (name.decode("latin-1"), value.decode("latin-1"))
        for name, value in request.headers.raw
    ]


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


@router.post("/api/v1/workflow-triggers/{trigger_id}/backfill/launch", status_code=202)
async def launch_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillLaunchRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await launch_workflow_trigger_backfill_request(trigger_id, payload, authorization)
