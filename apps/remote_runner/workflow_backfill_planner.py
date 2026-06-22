from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .api_models import WorkflowTriggerBackfillPreviewRequest
from .route_utils import request_payload


def build_backfill_plan(
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerBackfillPreviewRequest,
) -> dict[str, Any]:
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
    truncated = total_count > len(partitions)
    launch_supported = bool(trigger.get("enabled")) and not truncated
    reason = (
        "BACKFILL_LAUNCH_REQUIRES_CONFIRMATION"
        if launch_supported
        else "WORKFLOW_TRIGGER_DISABLED"
        if not trigger.get("enabled")
        else "WORKFLOW_BACKFILL_PREVIEW_TRUNCATED"
    )
    return {
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
        "launchSupported": launch_supported,
        "reason": reason,
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
        "truncated": truncated,
        "concurrency": {
            "limit": request.concurrencyLimit,
            "partitionCount": total_count,
            "estimatedBatches": math.ceil(total_count / request.concurrencyLimit),
        },
        "partitions": partitions,
    }


def backfill_launch_id(preview_id: str) -> str:
    return f"bfl_{hashlib.sha256(str(preview_id).encode('utf-8')).hexdigest()[:16]}"


def backfill_partition_event_payload(partition: dict[str, Any], *, actor: str) -> dict[str, Any]:
    return {
        "eventContext": {
            "source": "backfill",
            "eventId": str(partition["partitionId"]),
            "actor": actor,
            "partitionKey": str(partition["partitionKey"]),
        },
        "backfill": {
            "partitionId": partition["partitionId"],
            "partitionKey": partition["partitionKey"],
            "index": partition["index"],
            "window": partition["window"],
            "provenance": partition["provenance"],
        },
        "runSpec": partition["runSpecPreview"],
    }


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
        "runSpecPreview": _backfill_run_spec(
            trigger=trigger,
            request=request,
            partition_key=partition_key,
            window_start=window_start,
            window_end=window_end,
            timezone_name=timezone_name,
        ),
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


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _stable_copy(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))
