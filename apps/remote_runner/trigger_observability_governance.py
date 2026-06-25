from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .trigger_inbox_service import list_workflow_trigger_inbox_events_from_storage
from .trigger_readiness_read_model import get_workflow_trigger_readiness_observation_from_storage
from .trigger_scheduler_read_model import list_governed_workflow_trigger_scheduler_ticks as _list_scheduler_ticks
from .trigger_service import (
    get_workflow_backfill_launch_from_storage,
    list_workflow_backfill_launches_from_storage,
    list_workflow_trigger_events_from_storage,
    list_workflow_triggers_from_storage,
)


def list_governed_workflow_triggers(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    result = list_workflow_triggers_from_storage(cfg)
    data = _response_data(result)
    items = _items(data)
    _record_allow(
        cfg,
        action="workflow_trigger.list",
        subject_kind="workflow_trigger",
        subject_id="query",
        details={
            "returnedCount": len(items),
            "enabledCount": sum(1 for item in items if bool(item.get("enabled"))),
        },
    )
    return result


def list_governed_workflow_trigger_events(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
) -> dict[str, Any]:
    result = list_workflow_trigger_events_from_storage(cfg, trigger_id)
    data = _response_data(result)
    _record_allow(
        cfg,
        action="workflow_trigger.events.read",
        subject_kind="workflow_trigger_event",
        subject_id=trigger_id,
        details={"returnedCount": len(_items(data))},
    )
    return result


def get_governed_workflow_trigger_readiness_observation(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
) -> dict[str, Any]:
    result = get_workflow_trigger_readiness_observation_from_storage(cfg, trigger_id)
    data = _response_data(result)
    observation = data.get("observation") if isinstance(data.get("observation"), dict) else {}
    _record_allow(
        cfg,
        action="workflow_trigger.readiness_observation.read",
        subject_kind="workflow_trigger_readiness_observation",
        subject_id=trigger_id,
        details={
            "hasObservation": bool(observation),
            "sourceType": str(data.get("sourceType") or ""),
            "resourceType": str(observation.get("resourceType") or ""),
            "observedState": str(observation.get("observedState") or ""),
            "dispatchState": str(observation.get("dispatchState") or ""),
            "resourceUriPresent": bool(observation.get("resourceUriPresent")),
        },
    )
    return result


def list_governed_workflow_trigger_inbox_events(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    result = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger_id,
        state=state,
        limit=limit,
    )
    data = _response_data(result)
    _record_allow(
        cfg,
        action="workflow_trigger.inbox.read",
        subject_kind="workflow_trigger_inbox_event",
        subject_id=trigger_id,
        details={
            "filteredByState": bool(str(state or "").strip()),
            "limit": _bounded_limit(limit),
            "returnedCount": len(_items(data)),
        },
    )
    return result


def list_governed_workflow_trigger_scheduler_ticks(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    return _list_scheduler_ticks(cfg, limit=limit)


def list_governed_workflow_backfill_launches(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    result = list_workflow_backfill_launches_from_storage(
        cfg,
        trigger_id=trigger_id,
        limit=limit,
    )
    data = _response_data(result)
    _record_allow(
        cfg,
        action="workflow_trigger.backfill_launch.list",
        subject_kind="workflow_backfill_launch",
        subject_id="query",
        details={
            "filteredByTrigger": bool(str(trigger_id or "").strip()),
            "limit": _bounded_limit(limit),
            "returnedCount": len(_items(data)),
        },
    )
    return result


def get_governed_workflow_backfill_launch(
    cfg: RemoteRunnerConfig,
    launch_id: str,
) -> dict[str, Any]:
    result = get_workflow_backfill_launch_from_storage(cfg, launch_id)
    data = _response_data(result)
    summary = data.get("partitionSummary") if isinstance(data.get("partitionSummary"), dict) else {}
    _record_allow(
        cfg,
        action="workflow_trigger.backfill_launch.read",
        subject_kind="workflow_backfill_launch",
        subject_id=launch_id,
        details={
            "state": str(data.get("state") or ""),
            "partitionCount": _safe_int(summary.get("partitionCount")),
            "submittedRunCount": _safe_int(summary.get("submittedRunCount")),
            "activeRunCount": _safe_int(summary.get("activeRunCount")),
            "pendingPartitionCount": _safe_int(summary.get("pendingPartitionCount")),
            "failedPartitionCount": _safe_int(summary.get("failedPartitionCount")),
            "cancelRequestedPartitionCount": _safe_int(summary.get("cancelRequestedPartitionCount")),
        },
    )
    return result


def _record_allow(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    subject_kind: str,
    subject_id: str,
    details: dict[str, Any],
) -> None:
    record_governance_audit_event(
        cfg,
        action=action,
        actor=cfg.api_token_actor or "remote-runner-api",
        subject_kind=subject_kind,
        subject_id=subject_id,
        details=details,
    )


def _response_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else {}
    return data if isinstance(data, dict) else {}


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items") if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _bounded_limit(value: int) -> int:
    return min(500, max(1, int(value)))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
