from __future__ import annotations

import json
import uuid
from typing import Any

from .api_models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest, WorkflowTriggerInboxEventRequest
from .config import RemoteRunnerConfig
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from .governance_audit import record_governance_audit_event
from .health_service import ensure_execution_admission_ready, ensure_submission_ready
from .pipeline import get_pipeline, validate_run_spec_for_pipeline
from .preflight import preflight_run_spec
from .route_utils import request_payload
from .storage import canonical_payload_hash
from .trigger_storage import (
    create_workflow_trigger,
    list_workflow_trigger_events,
    list_workflow_triggers,
    mark_workflow_trigger_dispatch_failed,
    mark_workflow_trigger_dispatch_submitted,
    record_workflow_trigger_event,
    require_workflow_trigger,
)
from .workflow_run_storage import create_run_record


TRIGGER_EVENT_PAYLOAD_MAX_BYTES = 256 * 1024
LAUNCH_SUPPORTED_TRIGGER_SOURCES = {"manual", "cron", "webhook"}


def create_workflow_trigger_from_request(
    cfg: RemoteRunnerConfig,
    request: WorkflowTriggerCreateRequest,
    *,
    actor: str,
) -> dict[str, Any]:
    run_spec = request_payload(request.runSpec)
    pipeline = _validate_trigger_run_spec(cfg, run_spec)
    if request.sourceType not in LAUNCH_SUPPORTED_TRIGGER_SOURCES and request.enabled:
        raise ValueError(f"WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: {request.sourceType}")
    if request.runSpec.pipelineId != GENERATED_TOOL_RUN_PIPELINE_ID and not str(request.runSpec.pipelineVersion or "").strip():
        run_spec["pipelineVersion"] = pipeline.version
    trigger = create_workflow_trigger(
        cfg,
        name=request.name,
        source_type=request.sourceType,
        server_id=request.serverId,
        pipeline_id=request.runSpec.pipelineId,
        run_spec=run_spec,
        trigger_spec=request_payload(request).get("triggerSpec") or {},
        enabled=bool(request.enabled),
        actor=actor,
    )
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.create",
        actor=actor,
        subject_kind="workflow_trigger",
        subject_id=str(trigger["triggerId"]),
        details={
            "serverId": trigger["serverId"],
            "pipelineId": trigger["pipelineId"],
            "sourceType": trigger["sourceType"],
            "enabled": bool(trigger["enabled"]),
        },
    )
    return {"data": trigger}


def list_workflow_triggers_from_storage(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    return {"data": list_workflow_triggers(cfg)}


def list_workflow_trigger_events_from_storage(cfg: RemoteRunnerConfig, trigger_id: str) -> dict[str, Any]:
    require_workflow_trigger(cfg, trigger_id)
    return {"data": list_workflow_trigger_events(cfg, trigger_id)}


def submit_workflow_trigger_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerEventRequest,
) -> dict[str, Any]:
    ensure_submission_ready(cfg)
    trigger = require_workflow_trigger(cfg, trigger_id)
    if not trigger.get("enabled"):
        raise ValueError("WORKFLOW_TRIGGER_DISABLED")
    source_type = str(trigger.get("sourceType") or "")
    if source_type not in LAUNCH_SUPPORTED_TRIGGER_SOURCES:
        raise ValueError(f"WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: {source_type}")

    payload = request_payload(request).get("payload") or {}
    _enforce_payload_size(payload)
    idempotency_key = _event_idempotency_key(request)
    event = record_workflow_trigger_event(
        cfg,
        trigger=trigger,
        event_type=str(request.eventType or source_type),
        external_event_id=str(request.externalEventId or ""),
        idempotency_key=idempotency_key,
        cursor=str(request.cursor or ""),
        payload=payload,
    )
    dispatch = event.get("dispatch") if isinstance(event.get("dispatch"), dict) else {}
    if dispatch.get("state") == "submitted" and dispatch.get("runId"):
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.dispatch",
            actor=_dispatch_actor(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
            subject_kind="workflow_trigger_event",
            subject_id=str(event["triggerEventId"]),
            details=_dispatch_details(
                trigger_id=trigger_id,
                source_type=source_type,
                event=event,
                run_id=str(dispatch["runId"]),
                dispatch_state=str(dispatch.get("state") or ""),
                replayed=True,
            ),
        )
        return {
            "data": {
                "event": event,
                "run": {"runId": dispatch["runId"]},
                "replayed": True,
            },
            "location": f"/api/v1/runs/{dispatch['runId']}",
            "retryAfter": 2,
            "requestId": str(dispatch.get("requestId") or ""),
        }

    try:
        run_spec = dict(trigger.get("runSpec") or {})
        run_spec.pop("runId", None)
        pipeline = _validate_trigger_run_spec(cfg, run_spec)
        if run_spec.get("pipelineId") != GENERATED_TOOL_RUN_PIPELINE_ID and not str(run_spec.get("pipelineVersion") or "").strip():
            run_spec["pipelineVersion"] = pipeline.version
        ensure_execution_admission_ready(cfg)
        request_id = str(dispatch.get("requestId") or f"req_{uuid.uuid4().hex[:8]}")
        run_create = create_run_record(
            cfg,
            server_id=str(trigger["serverId"]),
            request_id=request_id,
            run_spec=run_spec,
            idempotency_key=str(dispatch.get("idempotencyKey") or f"trigger:{event['triggerEventId']}"),
            payload_hash=canonical_payload_hash(
                {
                    "serverId": trigger["serverId"],
                    "runSpec": run_spec,
                    "triggerEventId": event["triggerEventId"],
                }
            ),
        )
        event = mark_workflow_trigger_dispatch_submitted(
            cfg,
            trigger_event_id=str(event["triggerEventId"]),
            run_id=str(run_create.run["runId"]),
        )
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.dispatch",
            actor=_dispatch_actor(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
            subject_kind="workflow_trigger_event",
            subject_id=str(event["triggerEventId"]),
            details=_dispatch_details(
                trigger_id=trigger_id,
                source_type=source_type,
                event=event,
                run_id=str(run_create.run["runId"]),
                dispatch_state="submitted",
                replayed=not run_create.created,
            ),
        )
        return {
            "data": {
                "event": event,
                "run": {
                    "runId": run_create.run["runId"],
                    "status": run_create.run["status"],
                    "stage": run_create.run["stage"],
                    "message": run_create.run["message"],
                },
                "replayed": not run_create.created,
            },
            "location": f"/api/v1/runs/{run_create.run['runId']}",
            "retryAfter": 2,
            "requestId": run_create.run["requestId"],
        }
    except Exception as exc:
        mark_workflow_trigger_dispatch_failed(
            cfg,
            trigger_event_id=str(event["triggerEventId"]),
            error={"errorType": exc.__class__.__name__, "message": str(exc)},
        )
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.dispatch",
            actor=_dispatch_actor(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
            subject_kind="workflow_trigger_event",
            subject_id=str(event["triggerEventId"]),
            decision="error",
            reason_code="WORKFLOW_TRIGGER_DISPATCH_FAILED",
            details=_dispatch_details(
                trigger_id=trigger_id,
                source_type=source_type,
                event=event,
                dispatch_state="failed",
                error_type=exc.__class__.__name__,
            ),
        )
        raise


def submit_workflow_trigger_inbox_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerInboxEventRequest,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type != "webhook":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {source_type}")
    return submit_workflow_trigger_event_from_request(
        cfg,
        trigger_id,
        _inbox_event_request(request),
    )


def _validate_trigger_run_spec(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]):
    ensure_submission_ready(cfg)
    pipeline_id = str(run_spec.get("pipelineId") or "").strip()
    if not pipeline_id:
        raise ValueError("PIPELINE_ID_REQUIRED")
    pipeline = get_pipeline(cfg, pipeline_id)
    validate_run_spec_for_pipeline(pipeline, run_spec)
    preflight_run_spec(cfg, pipeline, run_spec)
    return pipeline


def _event_idempotency_key(request: WorkflowTriggerEventRequest) -> str:
    explicit = str(request.idempotencyKey or "").strip()
    if explicit:
        return explicit
    external = str(request.externalEventId or "").strip()
    if external:
        return f"external:{external}"
    cursor = str(request.cursor or "").strip()
    if cursor:
        return f"cursor:{cursor}"
    return f"manual:{uuid.uuid4().hex[:12]}"


def _enforce_payload_size(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > TRIGGER_EVENT_PAYLOAD_MAX_BYTES:
        raise ValueError("WORKFLOW_TRIGGER_EVENT_PAYLOAD_TOO_LARGE")


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
        payload={
            "eventContext": context,
            "payload": request_payload(request).get("payload") or {},
        },
    )


def _event_context_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("eventContext") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key in ("source", "eventId", "correlationId", "actor")
        if (value := str(raw.get(key) or "").strip())
    }


def _dispatch_actor(payload: dict[str, Any]) -> str:
    return _event_context_from_payload(payload).get("actor") or "remote-runner-api"


def _dispatch_details(
    *,
    trigger_id: str,
    source_type: str,
    event: dict[str, Any],
    dispatch_state: str,
    replayed: bool | None = None,
    run_id: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "triggerId": trigger_id,
        "sourceType": source_type,
        "eventType": event["eventType"],
        "dispatchState": dispatch_state,
    }
    if run_id:
        details["runId"] = run_id
    if replayed is not None:
        details["replayed"] = replayed
    if error_type:
        details["errorType"] = error_type
    event_context = _event_context_from_payload(event.get("payload") if isinstance(event.get("payload"), dict) else {})
    if event_context:
        details["eventContext"] = event_context
    return details


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized
