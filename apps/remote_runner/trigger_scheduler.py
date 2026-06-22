from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from .api_models import WorkflowTriggerEventRequest
from .config import RemoteRunnerConfig, load_remote_runner_config
from .trigger_service import submit_workflow_trigger_event_from_request
from .trigger_storage import list_workflow_triggers_by_source


LOGGER = logging.getLogger(__name__)
DEFAULT_CRON_SCHEDULER_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_CRON_SCHEDULER_LIMIT = 100


class WorkflowTriggerSchedulerSupervisor:
    def __init__(
        self,
        cfg: RemoteRunnerConfig,
        *,
        poll_interval_seconds: float = DEFAULT_CRON_SCHEDULER_POLL_INTERVAL_SECONDS,
        limit: int = DEFAULT_CRON_SCHEDULER_LIMIT,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_POLL_INTERVAL_INVALID")
        if limit <= 0:
            raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_LIMIT_INVALID")
        self._cfg = cfg
        self._poll_interval_seconds = poll_interval_seconds
        self._limit = limit
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="h2ometa-workflow-trigger-scheduler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = run_workflow_trigger_scheduler_once(self._cfg, limit=self._limit)
                if result.get("errors"):
                    LOGGER.warning("Workflow trigger scheduler completed with trigger errors: %s", result["errors"])
            except Exception:  # noqa: BLE001 - the scheduler must keep polling after transient storage/runtime errors.
                LOGGER.exception("Workflow trigger scheduler loop failed.")
            self._stop_event.wait(self._poll_interval_seconds)


def run_workflow_trigger_scheduler_once(
    cfg: RemoteRunnerConfig,
    *,
    now: datetime | str | None = None,
    limit: int = DEFAULT_CRON_SCHEDULER_LIMIT,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_LIMIT_INVALID")
    tick_at = _coerce_utc_minute(now)
    checked = 0
    skipped = 0
    due = 0
    submitted = 0
    replayed = 0
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for trigger in list_workflow_triggers_by_source(cfg, "cron", enabled_only=True)["items"]:
        checked += 1
        try:
            request = build_cron_trigger_event_request(trigger, now=tick_at)
        except Exception as exc:  # noqa: BLE001 - one bad trigger definition must not stop other schedules.
            errors.append(_trigger_error(trigger, exc))
            continue
        if request is None:
            skipped += 1
            continue
        if due >= limit:
            skipped += 1
            continue
        due += 1
        try:
            response = submit_workflow_trigger_event_from_request(cfg, str(trigger["triggerId"]), request)
        except Exception as exc:  # noqa: BLE001 - record the failed due tick and keep evaluating other triggers.
            errors.append(_trigger_error(trigger, exc))
            continue
        event = response["data"]["event"]
        events.append(event)
        if response["data"].get("replayed"):
            replayed += 1
        else:
            submitted += 1

    return {
        "checked": checked,
        "skipped": skipped,
        "due": due,
        "submitted": submitted,
        "replayed": replayed,
        "events": events,
        "errors": errors,
        "evaluatedAt": _format_utc(tick_at),
    }


def build_cron_trigger_event_request(
    trigger: dict[str, Any],
    *,
    now: datetime | str | None = None,
) -> WorkflowTriggerEventRequest | None:
    tick_at = _coerce_utc_minute(now)
    trigger_spec = trigger.get("triggerSpec") if isinstance(trigger.get("triggerSpec"), dict) else {}
    cron_expression = _cron_expression(trigger_spec)
    timezone_name, timezone = _cron_timezone(trigger_spec)
    local_tick = tick_at.astimezone(timezone).replace(second=0, microsecond=0)
    if not croniter.match(cron_expression, local_tick):
        return None

    scheduled_at = _format_utc(local_tick.astimezone(UTC))
    trigger_id = str(trigger.get("triggerId") or "").strip()
    if not trigger_id:
        raise ValueError("TRIGGER_ID_REQUIRED")
    event_key = f"cron:{trigger_id}:{scheduled_at}"
    payload = {
        "scheduledAt": scheduled_at,
        "schedule": {
            "cron": cron_expression,
            "timezone": timezone_name,
        },
        "scheduleVersion": str(trigger.get("updatedAt") or trigger.get("createdAt") or ""),
    }
    extra_payload = trigger_spec.get("payload")
    if isinstance(extra_payload, dict) and extra_payload:
        payload["triggerPayload"] = extra_payload
    return WorkflowTriggerEventRequest(
        eventType="cron",
        externalEventId=event_key,
        idempotencyKey=event_key,
        cursor=scheduled_at,
        payload=payload,
    )


def start_workflow_trigger_scheduler_supervisor(
    cfg: RemoteRunnerConfig,
    *,
    poll_interval_seconds: float = DEFAULT_CRON_SCHEDULER_POLL_INTERVAL_SECONDS,
    limit: int = DEFAULT_CRON_SCHEDULER_LIMIT,
) -> WorkflowTriggerSchedulerSupervisor:
    supervisor = WorkflowTriggerSchedulerSupervisor(
        cfg,
        poll_interval_seconds=poll_interval_seconds,
        limit=limit,
    )
    supervisor.start()
    return supervisor


def start_configured_workflow_trigger_scheduler_supervisor() -> WorkflowTriggerSchedulerSupervisor | None:
    cfg = load_remote_runner_config()
    if not cfg.token or not _trigger_scheduler_enabled():
        return None
    return start_workflow_trigger_scheduler_supervisor(
        cfg,
        poll_interval_seconds=_configured_poll_interval_seconds(),
        limit=_configured_limit(),
    )


def _cron_expression(trigger_spec: dict[str, Any]) -> str:
    if "schedules" in trigger_spec:
        raise ValueError("CRON_TRIGGER_MULTI_SCHEDULE_UNSUPPORTED")
    raw = trigger_spec.get("cron")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("CRON_TRIGGER_CRON_REQUIRED")
    expression = raw.strip()
    if len(expression.split()) != 5:
        raise ValueError("CRON_TRIGGER_FIVE_FIELD_REQUIRED")
    if not croniter.is_valid(expression):
        raise ValueError("CRON_TRIGGER_CRON_INVALID")
    return expression


def _cron_timezone(trigger_spec: dict[str, Any]) -> tuple[str, ZoneInfo]:
    name = str(trigger_spec.get("timezone") or "UTC").strip() or "UTC"
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"CRON_TRIGGER_TIMEZONE_INVALID: {name}") from exc


def _coerce_utc_minute(value: datetime | str | None) -> datetime:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_NOW_REQUIRED")
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(second=0, microsecond=0)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trigger_error(trigger: dict[str, Any], exc: BaseException) -> dict[str, str]:
    return {
        "triggerId": str(trigger.get("triggerId") or ""),
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }


def _trigger_scheduler_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_REMOTE_TRIGGER_SCHEDULER", "1") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _configured_poll_interval_seconds() -> float:
    raw = str(os.environ.get("H2OMETA_REMOTE_TRIGGER_SCHEDULER_POLL_SECONDS", "") or "").strip()
    if not raw:
        return DEFAULT_CRON_SCHEDULER_POLL_INTERVAL_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_POLL_INTERVAL_INVALID")
    return value


def _configured_limit() -> int:
    raw = str(os.environ.get("H2OMETA_REMOTE_TRIGGER_SCHEDULER_LIMIT", "") or "").strip()
    if not raw:
        return DEFAULT_CRON_SCHEDULER_LIMIT
    value = int(raw)
    if value <= 0:
        raise ValueError("WORKFLOW_TRIGGER_SCHEDULER_LIMIT_INVALID")
    return value
