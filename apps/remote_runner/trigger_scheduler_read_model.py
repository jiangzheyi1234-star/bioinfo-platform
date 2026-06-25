from __future__ import annotations

import json
from typing import Any

from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .storage_core import get_connection
from .trigger_scheduler import (
    WORKFLOW_TRIGGER_SCHEDULER_TICK_EVENT_TYPE,
    WORKFLOW_TRIGGER_SCHEDULER_TICK_SCHEMA,
)


WORKFLOW_TRIGGER_SCHEDULER_TICK_READ_MODEL_SCHEMA = "h2ometa.workflow-trigger-scheduler-tick-read-model.v1"
DEFAULT_WORKFLOW_TRIGGER_SCHEDULER_TICK_LIMIT = 20
MAX_WORKFLOW_TRIGGER_SCHEDULER_TICK_LIMIT = 100


def list_governed_workflow_trigger_scheduler_ticks(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = DEFAULT_WORKFLOW_TRIGGER_SCHEDULER_TICK_LIMIT,
) -> dict[str, Any]:
    ticks = list_workflow_trigger_scheduler_ticks(cfg, limit=limit)
    items = ticks["items"]
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.scheduler_ticks.read",
        subject_kind="workflow_trigger_scheduler",
        subject_id="query",
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "limit": _bounded_limit(limit),
            "returnedCount": len(items),
            "cronSubmittedCount": sum(_safe_int(item.get("cron", {}).get("submitted")) for item in items),
            "backfillSubmittedCount": sum(_safe_int(item.get("backfills", {}).get("submitted")) for item in items),
            "errorTickCount": sum(
                1
                for item in items
                if _safe_int(item.get("cron", {}).get("errorCount"))
                or _safe_int(item.get("backfills", {}).get("errorCount"))
            ),
            "controlsExposed": False,
        },
    )
    return ticks


def list_workflow_trigger_scheduler_ticks(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = DEFAULT_WORKFLOW_TRIGGER_SCHEDULER_TICK_LIMIT,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT event_id, seq, subject_id, payload_json, occurred_at
            FROM evidence_events
            WHERE subject_kind = ?
              AND event_type = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (
                "workflow_trigger_scheduler",
                WORKFLOW_TRIGGER_SCHEDULER_TICK_EVENT_TYPE,
                _bounded_limit(limit),
            ),
        ).fetchall()
    return {
        "schemaVersion": WORKFLOW_TRIGGER_SCHEDULER_TICK_READ_MODEL_SCHEMA,
        "items": [_project_tick(row) for row in rows],
    }


def _project_tick(row: Any) -> dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    if not isinstance(payload, dict):
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_TICK_PAYLOAD_INVALID")
    if payload.get("schemaVersion") != WORKFLOW_TRIGGER_SCHEDULER_TICK_SCHEMA:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_TICK_SCHEMA_UNSUPPORTED")
    if payload.get("controlsExposed") is not False:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_TICK_CONTROLS_UNSAFE")
    return {
        "tickId": _text(payload.get("tickId") or row["subject_id"]),
        "evidenceId": _text(row["event_id"]),
        "evidenceSeq": int(row["seq"] or 0),
        "occurredAt": _text(row["occurred_at"]),
        "evaluatedAt": _text(payload.get("evaluatedAt")),
        "limit": _safe_int(payload.get("limit")),
        "controlsExposed": False,
        "cron": _project_cron(_dict(payload.get("cron"))),
        "backfills": _project_backfills(_dict(payload.get("backfills"))),
    }


def _project_cron(value: dict[str, Any]) -> dict[str, Any]:
    return _copy_keys(
        value,
        (
            "checked",
            "skipped",
            "due",
            "submitted",
            "replayed",
            "eventCount",
            "dispatchRunCount",
            "errorCount",
            "errorTypes",
            "reasonCodes",
        ),
    )


def _project_backfills(value: dict[str, Any]) -> dict[str, Any]:
    return _copy_keys(
        value,
        (
            "checked",
            "advanced",
            "submitted",
            "replayed",
            "pending",
            "launchCount",
            "stateCounts",
            "errorCount",
            "errorTypes",
            "reasonCodes",
        ),
    )


def _copy_keys(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bounded_limit(value: int) -> int:
    return min(MAX_WORKFLOW_TRIGGER_SCHEDULER_TICK_LIMIT, max(1, int(value)))
