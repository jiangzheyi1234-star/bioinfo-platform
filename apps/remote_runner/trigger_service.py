from __future__ import annotations

import json
import uuid
from typing import Any

from .api_models import (
    WorkflowTriggerBackfillLaunchRequest,
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
from .workflow_backfill_planner import (
    backfill_launch_id,
    backfill_partition_event_payload,
    build_backfill_plan,
)
from .trigger_storage import (
    create_workflow_trigger,
    list_workflow_trigger_events,
    list_workflow_triggers,
    mark_workflow_trigger_dispatch_failed,
    mark_workflow_trigger_dispatch_submitted,
    record_workflow_trigger_event,
    require_workflow_trigger,
)
from .workflow_backfill_storage import (
    list_workflow_backfill_launches,
    mark_workflow_backfill_launch_finished,
    mark_workflow_backfill_partition_failed,
    mark_workflow_backfill_partition_submitted,
    record_workflow_backfill_launch,
    record_workflow_backfill_partition,
    require_workflow_backfill_launch,
)
from .workflow_run_storage import create_run_record


TRIGGER_EVENT_PAYLOAD_MAX_BYTES = 256 * 1024
LAUNCH_SUPPORTED_TRIGGER_SOURCES = {"manual", "cron", "webhook"}
READINESS_TRIGGER_SOURCES = {"dataset", "file", "database_ready"}
ENABLED_TRIGGER_SOURCES = LAUNCH_SUPPORTED_TRIGGER_SOURCES | READINESS_TRIGGER_SOURCES | {"backfill"}
READINESS_RESOURCE_TYPES_BY_SOURCE = {
    "dataset": "dataset",
    "file": "file",
    "database_ready": "database",
}
BACKFILL_LAUNCH_CONFIRMATION = "launch-backfill"


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
    if request.sourceType not in ENABLED_TRIGGER_SOURCES and request.enabled:
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


def list_workflow_backfill_launches_from_storage(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if str(trigger_id or "").strip():
        require_workflow_trigger(cfg, str(trigger_id or ""))
    return {"data": list_workflow_backfill_launches(cfg, trigger_id=trigger_id, limit=limit)}


def get_workflow_backfill_launch_from_storage(cfg: RemoteRunnerConfig, launch_id: str) -> dict[str, Any]:
    return {"data": require_workflow_backfill_launch(cfg, launch_id)}


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
    return _dispatch_recorded_trigger_event(
        cfg,
        trigger_id=trigger_id,
        trigger=trigger,
        event=event,
        source_type=source_type,
    )


def _dispatch_recorded_trigger_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str,
    trigger: dict[str, Any],
    event: dict[str, Any],
    source_type: str,
    run_spec_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        run_spec = _stable_copy(run_spec_override if run_spec_override is not None else trigger.get("runSpec") or {})
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
    plan = build_backfill_plan(trigger=trigger, request=request)
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.backfill_preview",
        subject_kind="workflow_trigger",
        subject_id=str(trigger["triggerId"]),
        details={
            "sourceType": plan["sourceType"],
            "pipelineId": trigger["pipelineId"],
            "partitionUnit": request.partitionUnit,
            "estimatedRunCount": plan["estimatedRunCount"],
            "returnedRunCount": plan["returnedRunCount"],
            "truncated": plan["truncated"],
            "launchSupported": plan["launchSupported"],
        },
    )
    return {"data": plan}


def launch_workflow_trigger_backfill_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerBackfillLaunchRequest,
) -> dict[str, Any]:
    if request.confirmation != BACKFILL_LAUNCH_CONFIRMATION:
        raise ValueError("WORKFLOW_BACKFILL_LAUNCH_CONFIRMATION_REQUIRED")
    ensure_submission_ready(cfg)
    trigger = require_workflow_trigger(cfg, trigger_id)
    if not trigger.get("enabled"):
        raise ValueError("WORKFLOW_TRIGGER_DISABLED")
    plan = build_backfill_plan(trigger=trigger, request=request)
    if plan["truncated"]:
        raise ValueError("WORKFLOW_BACKFILL_LAUNCH_TRUNCATED")
    partitions = list(plan["partitions"])
    ensure_execution_admission_ready(cfg)
    for partition in partitions:
        _validate_trigger_run_spec(cfg, dict(partition["runSpecPreview"]))
    actor = str(request.actor or "remote-runner-api")
    request_for_hash = request_payload(request)
    request_for_hash.pop("actor", None)
    launch = record_workflow_backfill_launch(
        cfg,
        launch_id=backfill_launch_id(plan["previewId"]),
        trigger_id=str(trigger["triggerId"]),
        preview_id=str(plan["previewId"]),
        range_start=str(plan["range"]["start"]),
        range_end=str(plan["range"]["end"]),
        timezone=str(plan["range"]["timezone"]),
        partition_unit=str(plan["range"]["partitionUnit"]),
        run_order=str(plan["runOrder"]),
        reprocess_behavior=str(plan["reprocessBehavior"]),
        partition_count=int(plan["estimatedRunCount"]),
        actor=actor,
        request=request_for_hash,
    )
    launched: list[dict[str, Any]] = []
    replayed_count = 0
    for partition in partitions:
        partition_state = record_workflow_backfill_partition(
            cfg,
            launch_id=str(launch["launchId"]),
            trigger_id=str(trigger["triggerId"]),
            partition=partition,
        )
        try:
            event = record_workflow_trigger_event(
                cfg,
                trigger=trigger,
                event_type="backfill.partition",
                external_event_id=str(partition["partitionId"]),
                idempotency_key=str(partition["idempotencyKey"]),
                cursor=str(partition["cursor"]),
                payload=backfill_partition_event_payload(partition, actor=actor),
            )
            dispatch_response = _dispatch_recorded_trigger_event(
                cfg,
                trigger_id=str(trigger["triggerId"]),
                trigger=trigger,
                event=event,
                source_type="backfill",
                run_spec_override=dict(partition["runSpecPreview"]),
            )
            replayed = bool(dispatch_response["data"]["replayed"])
            if replayed:
                replayed_count += 1
            submitted_partition = mark_workflow_backfill_partition_submitted(
                cfg,
                partition_id=str(partition["partitionId"]),
                trigger_event_id=str(dispatch_response["data"]["event"]["triggerEventId"]),
                run_id=str(dispatch_response["data"]["run"]["runId"]),
                replayed=replayed,
            )
            launched.append(
                {
                    **partition,
                    "state": submitted_partition["state"],
                    "triggerEventId": submitted_partition["triggerEventId"],
                    "runId": submitted_partition["runId"],
                    "replayed": replayed,
                }
            )
        except Exception as exc:
            mark_workflow_backfill_partition_failed(
                cfg,
                partition_id=str(partition_state["partitionId"]),
                error={"errorType": exc.__class__.__name__, "message": str(exc)},
            )
            mark_workflow_backfill_launch_finished(cfg, launch_id=str(launch["launchId"]), state="failed")
            raise
    launch = mark_workflow_backfill_launch_finished(cfg, launch_id=str(launch["launchId"]), state="submitted")
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.backfill_launch",
        actor=actor,
        subject_kind="workflow_backfill_launch",
        subject_id=str(launch["launchId"]),
        details={
            "triggerId": trigger["triggerId"],
            "previewId": plan["previewId"],
            "partitionCount": len(launched),
            "replayedRunCount": replayed_count,
            "range": plan["range"],
        },
    )
    return {
        "data": {
            "schemaVersion": "workflow-trigger-backfill-launch.v1",
            "launchId": launch["launchId"],
            "previewId": plan["previewId"],
            "triggerId": trigger["triggerId"],
            "sourceType": "backfill",
            "state": launch["state"],
            "range": plan["range"],
            "runOrder": plan["runOrder"],
            "reprocessBehavior": plan["reprocessBehavior"],
            "launchStrategy": "one-run-per-partition",
            "launchedRunCount": len(launched),
            "replayedRunCount": replayed_count,
            "partitions": launched,
        }
    }


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


def _stable_copy(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))
