from __future__ import annotations

from typing import Any

from .api_models import WorkflowTriggerSchedulerRunOnceRequest
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .trigger_scheduler import run_workflow_trigger_scheduler_once


WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_CONFIRMATION = "run-scheduler-once"
WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_RESULT_SCHEMA = (
    "h2ometa.workflow-trigger-scheduler-run-once-result.v1"
)


def run_governed_workflow_trigger_scheduler_once(
    cfg: RemoteRunnerConfig,
    request: WorkflowTriggerSchedulerRunOnceRequest,
) -> dict[str, Any]:
    if request.confirmation != WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_CONFIRMATION:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_CONFIRMATION_REQUIRED")
    result = run_workflow_trigger_scheduler_once(cfg, limit=int(request.limit))
    public = _public_run_once_result(result, limit=int(request.limit))
    actor = str(request.actor or cfg.api_token_actor or "remote-runner-api")
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.scheduler.run_once",
        actor=actor,
        subject_kind="workflow_trigger_scheduler",
        subject_id=str(public["tickId"]),
        details={
            "schemaVersion": WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_RESULT_SCHEMA,
            "tickId": public["tickId"],
            "evidenceId": public["evidenceId"],
            "evaluatedAt": public["evaluatedAt"],
            "limit": public["limit"],
            "cron": public["cron"],
            "backfills": public["backfills"],
            "controlsExposed": False,
        },
    )
    return {"data": public}


def _public_run_once_result(result: dict[str, Any], *, limit: int) -> dict[str, Any]:
    events = [item for item in result.get("events") or [] if isinstance(item, dict)]
    errors = [item for item in result.get("errors") or [] if isinstance(item, dict)]
    backfills = result.get("backfills") if isinstance(result.get("backfills"), dict) else {}
    return {
        "schemaVersion": WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE_RESULT_SCHEMA,
        "tickId": _text(result.get("tickId")),
        "evidenceId": _text(result.get("evidenceId")),
        "evaluatedAt": _text(result.get("evaluatedAt")),
        "limit": _bounded_limit(limit),
        "controlsExposed": False,
        "cron": {
            "checked": _safe_int(result.get("checked")),
            "skipped": _safe_int(result.get("skipped")),
            "due": _safe_int(result.get("due")),
            "submitted": _safe_int(result.get("submitted")),
            "replayed": _safe_int(result.get("replayed")),
            "overlapSkipped": _safe_int(result.get("overlapSkipped")),
            "eventCount": len(events),
            "dispatchRunCount": _dispatch_run_count(events),
            "errorCount": len(errors),
            "errorTypes": _error_counts(errors),
            "reasonCodes": _reason_counts(errors),
        },
        "backfills": _public_backfill_summary(backfills),
    }


def _public_backfill_summary(backfills: dict[str, Any]) -> dict[str, Any]:
    launches = [item for item in backfills.get("launches") or [] if isinstance(item, dict)]
    errors = [item for item in backfills.get("errors") or [] if isinstance(item, dict)]
    return {
        "checked": _safe_int(backfills.get("checked")),
        "advanced": _safe_int(backfills.get("advanced")),
        "submitted": _safe_int(backfills.get("submitted")),
        "replayed": _safe_int(backfills.get("replayed")),
        "pending": _safe_int(backfills.get("pending")),
        "launchCount": len(launches),
        "stateCounts": _value_counts(launch.get("state") for launch in launches),
        "errorCount": len(errors),
        "errorTypes": _error_counts(errors),
        "reasonCodes": _reason_counts(errors),
    }


def _dispatch_run_count(events: list[dict[str, Any]]) -> int:
    count = 0
    for event in events:
        dispatch = event.get("dispatch") if isinstance(event, dict) else {}
        if isinstance(dispatch, dict) and str(dispatch.get("runId") or "").strip():
            count += 1
    return count


def _error_counts(errors: list[dict[str, Any]]) -> dict[str, int]:
    return _value_counts(error.get("errorType") for error in errors)


def _reason_counts(errors: list[dict[str, Any]]) -> dict[str, int]:
    return _value_counts(_reason_code(str(error.get("message") or "")) for error in errors)


def _reason_code(message: str) -> str:
    return message.split(":", 1)[0].strip() if message.strip() else ""


def _value_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bounded_limit(value: int) -> int:
    return min(100, max(1, int(value)))
