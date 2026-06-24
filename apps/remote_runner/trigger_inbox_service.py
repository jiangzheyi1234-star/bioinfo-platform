from __future__ import annotations

import json
from typing import Any

from .api_models import WorkflowTriggerEventRequest, WorkflowTriggerInboxEventRequest
from .config import RemoteRunnerConfig
from .route_utils import request_payload
from .trigger_inbox_storage import (
    inbox_event_summary,
    list_workflow_trigger_inbox_events,
    mark_workflow_trigger_inbox_dead_lettered,
    mark_workflow_trigger_inbox_dispatching,
    mark_workflow_trigger_inbox_replay_failed,
    mark_workflow_trigger_inbox_submitted,
    record_workflow_trigger_inbox_event,
)
from .trigger_service import submit_workflow_trigger_event_from_request
from .trigger_storage import fetch_workflow_trigger_event_for_dedupe, require_workflow_trigger
from .webhook_raw_request import WebhookRawRequestEnvelope


TRIGGER_EVENT_PAYLOAD_MAX_BYTES = 256 * 1024


def list_workflow_trigger_inbox_events_from_storage(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    require_workflow_trigger(cfg, trigger_id)
    return {"data": list_workflow_trigger_inbox_events(cfg, trigger_id, state=state, limit=limit)}


def submit_workflow_trigger_inbox_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerInboxEventRequest,
    *,
    raw_envelope: WebhookRawRequestEnvelope | None = None,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type != "webhook":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {source_type}")
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    _enforce_payload_size(request_payload(request).get("payload") or {})
    inbox = record_workflow_trigger_inbox_event(
        cfg,
        trigger=trigger,
        source=source,
        event_type=str(request.eventType or "webhook"),
        provider_event_id=event_id,
        correlation_id=str(request.correlationId or "").strip(),
        cursor=str(request.cursor or "").strip(),
        dedupe_key=_inbox_dedupe_key(trigger, source=source, event_id=event_id),
        payload=request_payload(request),
        signature_metadata=_signature_metadata_from_envelope(raw_envelope),
    )
    try:
        mark_workflow_trigger_inbox_dispatching(cfg, inbox_event_id=str(inbox["inboxEventId"]))
        response = submit_workflow_trigger_event_from_request(cfg, trigger_id, _inbox_event_request(request))
        event = response["data"]["event"]
        run = response["data"]["run"]
        inbox = mark_workflow_trigger_inbox_submitted(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            trigger_event_id=str(event["triggerEventId"]),
            run_id=str(run["runId"]),
        )
        response["data"]["inbox"] = inbox_event_summary(inbox)
        return response
    except Exception as exc:
        _mark_inbox_dispatch_dead_lettered(cfg, trigger=trigger, request=request, inbox=inbox, exc=exc)
        raise


def find_workflow_trigger_inbox_trigger_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerInboxEventRequest,
) -> dict[str, Any] | None:
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    return fetch_workflow_trigger_event_for_dedupe(
        cfg,
        trigger_id=str(trigger["triggerId"]),
        idempotency_key=f"webhook:{source}:{event_id}",
        external_event_id=f"{source}:{event_id}",
    )


def _inbox_event_request(request: WorkflowTriggerInboxEventRequest) -> WorkflowTriggerEventRequest:
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    correlation_id = str(request.correlationId or "").strip()
    actor = str(request.actor or "").strip()
    external_event_id = f"{source}:{event_id}"
    context = {
        "source": source,
        "eventId": event_id,
        **({"correlationId": correlation_id} if correlation_id else {}),
        **({"actor": actor} if actor else {}),
    }
    return WorkflowTriggerEventRequest(
        eventType=str(request.eventType or "webhook"),
        externalEventId=external_event_id,
        idempotencyKey=f"webhook:{source}:{event_id}",
        cursor=str(request.cursor or external_event_id),
        payload={"eventContext": context, "payload": request_payload(request).get("payload") or {}},
    )


def _inbox_dedupe_key(trigger: dict[str, Any], *, source: str, event_id: str) -> str:
    return f"webhook:{trigger['triggerId']}:{source}:{event_id}"


def _signature_metadata_from_envelope(envelope: WebhookRawRequestEnvelope | None) -> dict[str, Any] | None:
    if envelope is None:
        return None
    return {
        "rawBodySha256": envelope.body_sha256,
        "rawBodySizeBytes": envelope.body_size_bytes,
        "rawContentType": envelope.content_type or "",
        "rawHeaderNames": list(envelope.header_names),
        "receivedAt": envelope.received_at.isoformat(),
    }


def _mark_inbox_dispatch_dead_lettered(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerInboxEventRequest,
    inbox: dict[str, Any],
    exc: Exception,
) -> None:
    event = find_workflow_trigger_inbox_trigger_event(cfg, trigger=trigger, request=request)
    error = {"errorType": exc.__class__.__name__, "message": str(exc)}
    if event is None:
        mark_workflow_trigger_inbox_dead_lettered(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            failure_code="WORKFLOW_TRIGGER_INBOX_DISPATCH_FAILED",
            error=error,
        )
        return
    mark_workflow_trigger_inbox_replay_failed(
        cfg,
        inbox_event_id=str(inbox["inboxEventId"]),
        trigger_event_id=str(event["triggerEventId"]),
        failure_code="WORKFLOW_TRIGGER_INBOX_DISPATCH_FAILED",
        error=error,
    )


def _enforce_payload_size(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > TRIGGER_EVENT_PAYLOAD_MAX_BYTES:
        raise ValueError("WORKFLOW_TRIGGER_EVENT_PAYLOAD_TOO_LARGE")


def _required_text(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text
