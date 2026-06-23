from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.api.models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerReadinessEventRequest,
)
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, request_payload, run_runtime_payload, runtime_service


@dataclass(frozen=True)
class WorkflowTriggerDispatch:
    payload: dict[str, Any]
    headers: dict[str, str]


class ResponseWithHeaders(Protocol):
    headers: Any


async def list_workflow_triggers_from_request(
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_triggers:{server_id or 'default'}",
        10,
        lambda: runtime_service().list_workflow_triggers(server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def create_workflow_trigger_from_request(
    request: WorkflowTriggerCreateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().create_workflow_trigger(request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache(prefixes=("workflow_triggers",))
    return result


async def list_workflow_trigger_events_from_request(
    trigger_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_trigger_events:{server_id or 'default'}:{trigger_id}",
        10,
        lambda: runtime_service().list_workflow_trigger_events(trigger_id, server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def list_workflow_backfill_launches_from_request(
    *,
    refresh: bool,
    server_id: str | None,
    trigger_id: str | None,
    limit: int,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_backfill_launches:{server_id or 'default'}:{trigger_id or 'all'}:{int(limit)}",
        10,
        lambda: runtime_service().list_workflow_backfill_launches(
            server_id=server_id,
            trigger_id=trigger_id,
            limit=limit,
        ),
        wrapper="raw",
        force_refresh=refresh,
    )


async def get_workflow_backfill_launch_from_request(
    launch_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_backfill_launch:{server_id or 'default'}:{launch_id}",
        10,
        lambda: runtime_service().get_workflow_backfill_launch(launch_id, server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def cancel_workflow_backfill_launch_from_request(
    launch_id: str,
    request: WorkflowBackfillCancelRequest,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id_hint = str(payload.pop("serverId", None) or server_id or "").strip() or None
    result = await run_runtime_payload(
        lambda: runtime_service().cancel_workflow_backfill_launch(
            launch_id,
            payload,
            server_id=server_id_hint,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(
        "runs",
        prefixes=("workflow_trigger_events", "workflow_backfill_launches", "workflow_backfill_launch"),
    )
    return result


async def submit_workflow_trigger_event_from_request(
    trigger_id: str,
    request: WorkflowTriggerEventRequest,
    *,
    server_id: str | None,
) -> WorkflowTriggerDispatch:
    result = await run_runtime_payload(
        lambda: runtime_service().submit_workflow_trigger_event(
            trigger_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events",))
    return WorkflowTriggerDispatch(
        payload=result,
        headers={
            "Location": str(result["location"]),
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def submit_workflow_trigger_inbox_event_from_request(
    trigger_id: str,
    request: WorkflowTriggerInboxEventRequest,
    *,
    server_id: str | None,
) -> WorkflowTriggerDispatch:
    result = await run_runtime_payload(
        lambda: runtime_service().submit_workflow_trigger_inbox_event(
            trigger_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events",))
    return WorkflowTriggerDispatch(
        payload=result,
        headers={
            "Location": str(result["location"]),
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def submit_workflow_trigger_readiness_event_from_request(
    trigger_id: str,
    request: WorkflowTriggerReadinessEventRequest,
    *,
    server_id: str | None,
) -> WorkflowTriggerDispatch:
    result = await run_runtime_payload(
        lambda: runtime_service().submit_workflow_trigger_readiness_event(
            trigger_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events",))
    return WorkflowTriggerDispatch(
        payload=result,
        headers={
            "Location": str(result["location"]),
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def preview_workflow_trigger_backfill_from_request(
    trigger_id: str,
    request: WorkflowTriggerBackfillPreviewRequest,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().preview_workflow_trigger_backfill(
            trigger_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )


async def launch_workflow_trigger_backfill_from_request(
    trigger_id: str,
    request: WorkflowTriggerBackfillLaunchRequest,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().launch_workflow_trigger_backfill(
            trigger_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(
        "runs",
        prefixes=("workflow_trigger_events", "workflow_backfill_launches", "workflow_backfill_launch"),
    )
    return result


async def submit_workflow_trigger_event_response_from_request(
    trigger_id: str,
    request: WorkflowTriggerEventRequest,
    response: ResponseWithHeaders,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    dispatch = await submit_workflow_trigger_event_from_request(
        trigger_id,
        request,
        server_id=server_id,
    )
    response.headers.update(dispatch.headers)
    return dispatch.payload


async def submit_workflow_trigger_inbox_event_response_from_request(
    trigger_id: str,
    request: WorkflowTriggerInboxEventRequest,
    response: ResponseWithHeaders,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    dispatch = await submit_workflow_trigger_inbox_event_from_request(
        trigger_id,
        request,
        server_id=server_id,
    )
    response.headers.update(dispatch.headers)
    return dispatch.payload


async def submit_workflow_trigger_readiness_event_response_from_request(
    trigger_id: str,
    request: WorkflowTriggerReadinessEventRequest,
    response: ResponseWithHeaders,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    dispatch = await submit_workflow_trigger_readiness_event_from_request(
        trigger_id,
        request,
        server_id=server_id,
    )
    response.headers.update(dispatch.headers)
    return dispatch.payload
