from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    WORKFLOW_BACKFILL_LAUNCH_CANCEL,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH,
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW,
    WORKFLOW_TRIGGER_CREATE,
    WORKFLOW_TRIGGER_EVENT_SUBMIT,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_INBOX_REPLAY,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_INBOX_SUBMIT,
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_READINESS_SUBMIT,
    WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE,
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    remote_endpoint_success_status,
)

from .api_models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxReplayRequest,
    WorkflowTriggerReadinessEventRequest,
    WorkflowTriggerReadinessWatcherRunOnceRequest,
    WorkflowTriggerSchedulerRunOnceRequest,
)
from .control_service import (
    cancel_workflow_backfill_launch_request,
    create_workflow_trigger_request,
    get_workflow_backfill_launch_request,
    get_workflow_trigger_readiness_observation_request,
    list_workflow_backfill_launches_request,
    list_workflow_trigger_events_request,
    list_workflow_trigger_inbox_events_request,
    list_workflow_trigger_scheduler_ticks_request,
    list_workflow_triggers_request,
    launch_workflow_trigger_backfill_request,
    preview_workflow_trigger_backfill_request,
    replay_workflow_trigger_inbox_event_request,
    submit_workflow_trigger_event_request,
    submit_workflow_trigger_inbox_event_envelope_request,
    submit_workflow_trigger_readiness_event_request,
)
from .route_headers import AuthorizationHeader
from .trigger_readiness_watcher_control_route_service import run_workflow_trigger_readiness_watcher_once_request
from .trigger_scheduler_control_route_service import run_workflow_trigger_scheduler_once_request
from .webhook_raw_request import WebhookRawRequestEnvelope, build_webhook_raw_request_envelope


router = APIRouter()


@router.get("/api/v1/workflow-triggers", operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_LIST].operation_id)
async def list_workflow_triggers(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_workflow_triggers_request(authorization)


@router.post(
    "/api/v1/workflow-triggers",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_CREATE].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_CREATE),
)
async def create_workflow_trigger(
    payload: WorkflowTriggerCreateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_workflow_trigger_request(payload, authorization)


@router.get(
    "/api/v1/workflow-triggers/{trigger_id}/events",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_EVENTS_READ].operation_id,
)
async def list_workflow_trigger_events(
    trigger_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_workflow_trigger_events_request(trigger_id, authorization)


@router.get(
    "/api/v1/workflow-triggers/{trigger_id}/readiness-observation",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ].operation_id,
)
async def get_workflow_trigger_readiness_observation(
    trigger_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_trigger_readiness_observation_request(trigger_id, authorization)


@router.get(
    "/api/v1/workflow-triggers/{trigger_id}/inbox",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_INBOX_READ].operation_id,
)
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


@router.get(
    "/api/v1/workflow-trigger-scheduler/ticks",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ].operation_id,
)
async def list_workflow_trigger_scheduler_ticks(
    limit: int = 20,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_workflow_trigger_scheduler_ticks_request(
        authorization,
        limit=limit,
    )


@router.post(
    "/api/v1/workflow-trigger-scheduler/run-once",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE),
)
async def run_workflow_trigger_scheduler_once(
    payload: WorkflowTriggerSchedulerRunOnceRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await run_workflow_trigger_scheduler_once_request(payload, authorization)


@router.post(
    "/api/v1/workflow-trigger-readiness-watcher/run-once",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE),
)
async def run_workflow_trigger_readiness_watcher_once(
    payload: WorkflowTriggerReadinessWatcherRunOnceRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await run_workflow_trigger_readiness_watcher_once_request(payload, authorization)


@router.get(
    "/api/v1/workflow-backfill-launches",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_BACKFILL_LAUNCH_LIST].operation_id,
)
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


@router.get(
    "/api/v1/workflow-backfill-launches/{launch_id}",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_BACKFILL_LAUNCH_READ].operation_id,
)
async def get_workflow_backfill_launch(
    launch_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_backfill_launch_request(launch_id, authorization)


@router.post(
    "/api/v1/workflow-backfill-launches/{launch_id}/cancel",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_BACKFILL_LAUNCH_CANCEL].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_BACKFILL_LAUNCH_CANCEL),
)
async def cancel_workflow_backfill_launch(
    launch_id: str,
    payload: WorkflowBackfillCancelRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await cancel_workflow_backfill_launch_request(launch_id, payload, authorization)


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/events",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_EVENT_SUBMIT].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_EVENT_SUBMIT),
)
async def submit_workflow_trigger_event(
    trigger_id: str,
    payload: WorkflowTriggerEventRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_event_request(trigger_id, payload, authorization)


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/inbox",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_INBOX_SUBMIT].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_INBOX_SUBMIT),
)
async def submit_workflow_trigger_inbox_event(
    trigger_id: str,
    request: Request,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    envelope = await build_webhook_inbox_envelope_from_request(request)
    return await submit_workflow_trigger_inbox_event_envelope_request(trigger_id, envelope, authorization)


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_INBOX_REPLAY].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_INBOX_REPLAY),
)
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


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/readiness",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_READINESS_SUBMIT].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_READINESS_SUBMIT),
)
async def submit_workflow_trigger_readiness_event(
    trigger_id: str,
    payload: WorkflowTriggerReadinessEventRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await submit_workflow_trigger_readiness_event_request(trigger_id, payload, authorization)


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/backfill/preview",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_BACKFILL_PREVIEW].operation_id,
)
async def preview_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillPreviewRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await preview_workflow_trigger_backfill_request(trigger_id, payload, authorization)


@router.post(
    "/api/v1/workflow-triggers/{trigger_id}/backfill/launch",
    operation_id=REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_BACKFILL_LAUNCH].operation_id,
    status_code=remote_endpoint_success_status(WORKFLOW_TRIGGER_BACKFILL_LAUNCH),
)
async def launch_workflow_trigger_backfill(
    trigger_id: str,
    payload: WorkflowTriggerBackfillLaunchRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await launch_workflow_trigger_backfill_request(trigger_id, payload, authorization)
