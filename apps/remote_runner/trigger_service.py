from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .api_models import (
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerReadinessEventRequest,
)
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
READINESS_TRIGGER_SOURCES = {"dataset", "file", "database_ready"}
READINESS_RESOURCE_TYPES_BY_SOURCE = {
    "dataset": "dataset",
    "file": "file",
    "database_ready": "database",
}
BACKFILL_LAUNCH_DISABLED_REASON = "WORKFLOW_BACKFILL_LAUNCH_UNSUPPORTED_UNTIL_PROVENANCE_STABLE"


def create_workflow_trigger_from_request(
    cfg: RemoteRunnerConfig,
    request: WorkflowTriggerCreateRequest,
    *,
    actor: str,
) -> dict[str, Any]:
    run_spec = request_payload(request.runSpec)
    pipeline = _validate_trigger_run_spec(cfg, run_spec)
    trigger_payload = request_payload(request)
    trigger_spec = trigger_payload.get("triggerSpec") or {}
    if request.sourceType in READINESS_TRIGGER_SOURCES:
        _validate_readiness_trigger_resource_spec(request.sourceType, trigger_spec)
    if request.sourceType not in (LAUNCH_SUPPORTED_TRIGGER_SOURCES | READINESS_TRIGGER_SOURCES) and request.enabled:
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
        trigger_spec=trigger_spec,
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
    *,
    supported_sources: set[str] | None = None,
) -> dict[str, Any]:
    ensure_submission_ready(cfg)
    trigger = require_workflow_trigger(cfg, trigger_id)
    if not trigger.get("enabled"):
        raise ValueError("WORKFLOW_TRIGGER_DISABLED")
    source_type = str(trigger.get("sourceType") or "")
    if source_type not in (supported_sources or LAUNCH_SUPPORTED_TRIGGER_SOURCES):
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


def submit_workflow_trigger_readiness_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerReadinessEventRequest,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type not in READINESS_TRIGGER_SOURCES:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_SOURCE_MISMATCH: {source_type}")
    return submit_workflow_trigger_event_from_request(
        cfg,
        trigger_id,
        _readiness_event_request(trigger, request),
        supported_sources=READINESS_TRIGGER_SOURCES,
    )


def preview_workflow_trigger_backfill_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerBackfillPreviewRequest,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type != "backfill":
        raise ValueError(f"WORKFLOW_BACKFILL_PREVIEW_SOURCE_MISMATCH: {source_type}")

    timezone_name, timezone = _backfill_timezone(request.timezone)
    step = _backfill_step(request.partitionUnit)
    range_start = _backfill_boundary(request.rangeStart, timezone=timezone, partition_unit=request.partitionUnit)
    range_end = _backfill_boundary(request.rangeEnd, timezone=timezone, partition_unit=request.partitionUnit)
    if range_start >= range_end:
        raise ValueError("WORKFLOW_BACKFILL_RANGE_INVALID")
    total_count = _backfill_partition_count(range_start, range_end, step)
    indices = _backfill_preview_indices(
        total_count,
        limit=request.maxPartitions,
        run_order=request.runOrder,
    )
    partitions = [
        _backfill_partition_preview(
            trigger=trigger,
            request=request,
            index=index,
            timezone_name=timezone_name,
            partition_unit=request.partitionUnit,
            window_start=range_start + (step * index),
            window_end=range_start + (step * (index + 1)),
        )
        for index in indices
    ]
    preview = {
        "schemaVersion": "workflow-trigger-backfill-preview.v1",
        "previewId": _backfill_preview_id(
            trigger_id=str(trigger["triggerId"]),
            range_start=range_start,
            range_end=range_end,
            request=request,
        ),
        "triggerId": trigger["triggerId"],
        "sourceType": source_type,
        "triggerEnabled": bool(trigger.get("enabled")),
        "pipelineId": trigger["pipelineId"],
        "launchSupported": False,
        "reason": "BACKFILL_PREVIEW_ONLY",
        "launchDisabledReason": BACKFILL_LAUNCH_DISABLED_REASON,
        "range": {
            "start": _format_utc(range_start),
            "end": _format_utc(range_end),
            "timezone": timezone_name,
            "partitionUnit": request.partitionUnit,
            "semantics": "half-open",
            "runOrder": request.runOrder,
        },
        "runOrder": request.runOrder,
        "reprocessBehavior": request.reprocessBehavior,
        "launchStrategy": "one-run-per-partition",
        "estimatedRunCount": total_count,
        "returnedRunCount": len(partitions),
        "truncated": total_count > len(partitions),
        "concurrency": {
            "limit": request.concurrencyLimit,
            "partitionCount": total_count,
            "estimatedBatches": math.ceil(total_count / request.concurrencyLimit),
        },
        "partitions": partitions,
    }
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.backfill_preview",
        subject_kind="workflow_trigger",
        subject_id=str(trigger["triggerId"]),
        details={
            "sourceType": source_type,
            "pipelineId": trigger["pipelineId"],
            "partitionUnit": request.partitionUnit,
            "estimatedRunCount": total_count,
            "returnedRunCount": len(partitions),
            "truncated": total_count > len(partitions),
            "launchSupported": False,
        },
    )
    return {"data": preview}


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


def _readiness_event_request(
    trigger: dict[str, Any],
    request: WorkflowTriggerReadinessEventRequest,
) -> WorkflowTriggerEventRequest:
    source_type = str(trigger.get("sourceType") or "")
    expected_resource_type = READINESS_RESOURCE_TYPES_BY_SOURCE.get(source_type)
    if not expected_resource_type:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_SOURCE_MISMATCH: {source_type}")
    if request.resourceType != expected_resource_type:
        raise ValueError(
            f"WORKFLOW_TRIGGER_READINESS_RESOURCE_TYPE_MISMATCH: {expected_resource_type} != {request.resourceType}"
        )
    expected_resource = _readiness_trigger_resource(trigger, expected_resource_type)
    source = _required_text(request.source, "WORKFLOW_TRIGGER_READINESS_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_READINESS_EVENT_ID_REQUIRED")
    resource_id = _required_text(request.resourceId, "WORKFLOW_TRIGGER_READINESS_RESOURCE_ID_REQUIRED")
    if resource_id != expected_resource["id"]:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_RESOURCE_MISMATCH: {resource_id}")
    uri = str(request.uri or "").strip()
    expected_uri = str(expected_resource.get("uri") or "").strip()
    if uri and expected_uri and uri != expected_uri:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_RESOURCE_URI_MISMATCH: {uri}")
    actor = str(request.actor or "").strip()
    version = str(request.version or "").strip()
    checksum = str(request.checksum or "").strip()
    observed_at = str(request.observedAt or "").strip()
    external_event_id = f"{source}:{resource_id}:{event_id}"
    resource = {
        "type": request.resourceType,
        "id": resource_id,
        **({"uri": uri} if uri else {}),
        **({"version": version} if version else {}),
        **({"checksum": checksum} if checksum else {}),
        **({"labels": dict(request.labels)} if request.labels else {}),
    }
    context = {
        "source": source,
        "eventId": event_id,
        "resourceType": request.resourceType,
        "resourceId": resource_id,
        **({"actor": actor} if actor else {}),
    }
    return WorkflowTriggerEventRequest(
        eventType=f"{request.resourceType}.ready",
        externalEventId=external_event_id,
        idempotencyKey=f"readiness:{trigger['triggerId']}:{source}:{resource_id}:{event_id}",
        cursor=str(request.cursor or f"{resource_id}@{version or event_id}"),
        payload={
            "eventContext": context,
            "resource": resource,
            "state": request.state,
            **({"observedAt": observed_at} if observed_at else {}),
            "payload": request_payload(request).get("payload") or {},
        },
    )


def _readiness_trigger_resource(trigger: dict[str, Any], expected_resource_type: str) -> dict[str, str]:
    trigger_spec = trigger.get("triggerSpec") if isinstance(trigger.get("triggerSpec"), dict) else {}
    return _validate_readiness_trigger_resource_spec(
        str(trigger.get("sourceType") or ""),
        trigger_spec,
        expected_resource_type=expected_resource_type,
    )


def _validate_readiness_trigger_resource_spec(
    source_type: str,
    trigger_spec: dict[str, Any],
    *,
    expected_resource_type: str | None = None,
) -> dict[str, str]:
    resource_type_for_source = READINESS_RESOURCE_TYPES_BY_SOURCE.get(source_type)
    if not resource_type_for_source:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_SOURCE_MISMATCH: {source_type}")
    expected_type = expected_resource_type or resource_type_for_source
    if expected_type != resource_type_for_source:
        raise ValueError(
            f"WORKFLOW_TRIGGER_READINESS_TRIGGER_RESOURCE_TYPE_MISMATCH: {resource_type_for_source} != {expected_type}"
        )
    raw_resource = trigger_spec.get("resource") if isinstance(trigger_spec, dict) else None
    if not isinstance(raw_resource, dict):
        raise ValueError("WORKFLOW_TRIGGER_READINESS_RESOURCE_SPEC_REQUIRED")
    resource_type = _required_text(raw_resource.get("type"), "WORKFLOW_TRIGGER_READINESS_RESOURCE_TYPE_REQUIRED")
    if resource_type != expected_type:
        raise ValueError(
            f"WORKFLOW_TRIGGER_READINESS_TRIGGER_RESOURCE_TYPE_MISMATCH: {expected_type} != {resource_type}"
        )
    resource_id = _required_text(raw_resource.get("id"), "WORKFLOW_TRIGGER_READINESS_RESOURCE_ID_REQUIRED")
    uri = str(raw_resource.get("uri") or "").strip()
    return {"type": resource_type, "id": resource_id, **({"uri": uri} if uri else {})}


def _event_context_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("eventContext") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key in ("source", "eventId", "correlationId", "actor", "resourceType", "resourceId")
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


def _backfill_timezone(value: str) -> tuple[str, ZoneInfo]:
    name = _required_text(value, "WORKFLOW_BACKFILL_TIMEZONE_REQUIRED")
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"WORKFLOW_BACKFILL_TIMEZONE_INVALID: {name}") from exc


def _backfill_step(partition_unit: str) -> timedelta:
    if partition_unit == "hour":
        return timedelta(hours=1)
    if partition_unit == "day":
        return timedelta(days=1)
    raise ValueError(f"WORKFLOW_BACKFILL_PARTITION_UNIT_UNSUPPORTED: {partition_unit}")


def _backfill_boundary(value: str, *, timezone: ZoneInfo, partition_unit: str) -> datetime:
    raw = _required_text(value, "WORKFLOW_BACKFILL_RANGE_BOUNDARY_REQUIRED")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"WORKFLOW_BACKFILL_RANGE_BOUNDARY_INVALID: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    local = parsed.astimezone(timezone).replace(microsecond=0)
    if local.second != 0:
        raise ValueError("WORKFLOW_BACKFILL_RANGE_NOT_ALIGNED")
    if partition_unit == "hour" and local.minute != 0:
        raise ValueError("WORKFLOW_BACKFILL_RANGE_NOT_ALIGNED")
    if partition_unit == "day" and (local.hour != 0 or local.minute != 0):
        raise ValueError("WORKFLOW_BACKFILL_RANGE_NOT_ALIGNED")
    return local


def _backfill_partition_count(range_start: datetime, range_end: datetime, step: timedelta) -> int:
    total_seconds = (range_end - range_start).total_seconds()
    step_seconds = step.total_seconds()
    if total_seconds <= 0 or total_seconds % step_seconds:
        raise ValueError("WORKFLOW_BACKFILL_RANGE_NOT_ALIGNED")
    return int(total_seconds // step_seconds)


def _backfill_preview_indices(total_count: int, *, limit: int, run_order: str) -> range:
    returned = min(total_count, limit)
    if run_order == "forward":
        return range(0, returned)
    if run_order == "backward":
        return range(total_count - 1, total_count - returned - 1, -1)
    raise ValueError(f"WORKFLOW_BACKFILL_RUN_ORDER_UNSUPPORTED: {run_order}")


def _backfill_partition_preview(
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerBackfillPreviewRequest,
    index: int,
    timezone_name: str,
    partition_unit: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    trigger_id = str(trigger["triggerId"])
    partition_key = _backfill_partition_key(window_start, partition_unit=partition_unit)
    window_start_utc = _format_utc(window_start)
    window_end_utc = _format_utc(window_end)
    identity = f"backfill:{trigger_id}:{partition_unit}:{window_start_utc}:{window_end_utc}"
    run_spec = _backfill_run_spec(
        trigger=trigger,
        request=request,
        partition_key=partition_key,
        window_start=window_start,
        window_end=window_end,
        timezone_name=timezone_name,
    )
    return {
        "partitionId": identity,
        "partitionKey": partition_key,
        "index": index,
        "window": {
            "start": window_start_utc,
            "end": window_end_utc,
            "timezone": timezone_name,
            "semantics": "half-open",
        },
        "action": "create",
        "existingState": None,
        "cursor": identity,
        "idempotencyKey": identity,
        "provenance": {
            "triggerId": trigger_id,
            "pipelineId": trigger["pipelineId"],
            "sourceType": "backfill",
            "partitionUnit": partition_unit,
            "partitionKey": partition_key,
        },
        "runSpecPreview": run_spec,
    }


def _backfill_run_spec(
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerBackfillPreviewRequest,
    partition_key: str,
    window_start: datetime,
    window_end: datetime,
    timezone_name: str,
) -> dict[str, Any]:
    run_spec = _stable_copy(trigger.get("runSpec") or {})
    run_spec.pop("runId", None)
    params = dict(run_spec.get("params") or {})
    params.update(_stable_copy(request.params))
    params["backfill"] = {
        "partitionKey": partition_key,
        "windowStart": _format_utc(window_start),
        "windowEnd": _format_utc(window_end),
        "timezone": timezone_name,
        "reprocessBehavior": request.reprocessBehavior,
    }
    run_spec["params"] = params
    return run_spec


def _backfill_partition_key(window_start: datetime, *, partition_unit: str) -> str:
    if partition_unit == "hour":
        return window_start.strftime("%Y-%m-%dT%H")
    if partition_unit == "day":
        return window_start.strftime("%Y-%m-%d")
    raise ValueError(f"WORKFLOW_BACKFILL_PARTITION_UNIT_UNSUPPORTED: {partition_unit}")


def _backfill_preview_id(
    *,
    trigger_id: str,
    range_start: datetime,
    range_end: datetime,
    request: WorkflowTriggerBackfillPreviewRequest,
) -> str:
    payload = {
        "triggerId": trigger_id,
        "rangeStart": _format_utc(range_start),
        "rangeEnd": _format_utc(range_end),
        "request": request_payload(request),
    }
    return f"bfprev_{hashlib.sha256(_stable_json(payload).encode('utf-8')).hexdigest()[:16]}"


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_copy(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))
