from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from apps.api.models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerInboxReplayRequest,
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


WEBHOOK_INBOX_FORWARD_HEADERS = {
    "content-type": "Content-Type",
    "stripe-signature": "Stripe-Signature",
    "x-github-delivery": "X-GitHub-Delivery",
    "x-github-event": "X-GitHub-Event",
    "x-hub-signature-256": "X-Hub-Signature-256",
    "x-slack-request-timestamp": "X-Slack-Request-Timestamp",
    "x-slack-signature": "X-Slack-Signature",
}


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


async def list_workflow_trigger_inbox_events_from_request(
    trigger_id: str,
    *,
    refresh: bool,
    server_id: str | None,
    state: str | None,
    limit: int,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_trigger_inbox:{server_id or 'default'}:{trigger_id}:{state or 'all'}:{int(limit)}",
        10,
        lambda: runtime_service().list_workflow_trigger_inbox_events(
            trigger_id,
            server_id=server_id,
            state=state,
            limit=limit,
        ),
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
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events", "workflow_trigger_inbox"))
    return WorkflowTriggerDispatch(
        payload=result,
        headers={
            "Location": str(result["location"]),
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def submit_workflow_trigger_inbox_event_from_raw_request(
    trigger_id: str,
    raw_body: bytes,
    raw_headers: Iterable[tuple[str | bytes, str | bytes]],
    *,
    server_id: str | None,
) -> WorkflowTriggerDispatch:
    result = await run_runtime_payload(
        lambda: runtime_service().submit_workflow_trigger_inbox_event(
            trigger_id,
            server_id=server_id,
            raw_body=bytes(raw_body),
            headers=_webhook_inbox_forward_headers(raw_headers),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events", "workflow_trigger_inbox"))
    return WorkflowTriggerDispatch(
        payload=result,
        headers={
            "Location": str(result["location"]),
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def replay_workflow_trigger_inbox_event_from_request(
    trigger_id: str,
    inbox_event_id: str,
    request: WorkflowTriggerInboxReplayRequest,
    *,
    server_id: str | None,
) -> WorkflowTriggerDispatch:
    result = await run_runtime_payload(
        lambda: runtime_service().replay_workflow_trigger_inbox_event(
            trigger_id,
            inbox_event_id,
            request_payload(request),
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs", prefixes=("workflow_trigger_events", "workflow_trigger_inbox"))
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


async def submit_workflow_trigger_inbox_event_response_from_raw_request(
    trigger_id: str,
    raw_body: bytes,
    raw_headers: Iterable[tuple[str | bytes, str | bytes]],
    response: ResponseWithHeaders,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    dispatch = await submit_workflow_trigger_inbox_event_from_raw_request(
        trigger_id,
        raw_body,
        raw_headers,
        server_id=server_id,
    )
    response.headers.update(dispatch.headers)
    return dispatch.payload


async def replay_workflow_trigger_inbox_event_response_from_request(
    trigger_id: str,
    inbox_event_id: str,
    request: WorkflowTriggerInboxReplayRequest,
    response: ResponseWithHeaders,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    dispatch = await replay_workflow_trigger_inbox_event_from_request(
        trigger_id,
        inbox_event_id,
        request,
        server_id=server_id,
    )
    response.headers.update(dispatch.headers)
    return dispatch.payload


def _webhook_inbox_forward_headers(raw_headers: Iterable[tuple[str | bytes, str | bytes]]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in raw_headers:
        name = _header_text(raw_name)
        canonical = WEBHOOK_INBOX_FORWARD_HEADERS.get(name.lower())
        if not canonical:
            continue
        value = _header_text(raw_value)
        existing = headers.get(canonical)
        if existing is not None and existing != value:
            raise ValueError(f"WORKFLOW_TRIGGER_INBOX_FORWARD_HEADER_CONFLICT: {canonical}")
        headers[canonical] = value
    return headers


def _header_text(value: str | bytes) -> str:
    return value.decode("latin-1") if isinstance(value, bytes) else str(value)


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
