from __future__ import annotations

from copy import deepcopy
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


CRON_TRIGGER_SPEC_KEYS = frozenset({"cron", "timezone", "concurrencyPolicy", "payload"})
CRON_TRIGGER_CONCURRENCY_POLICIES = {"allow": "Allow", "forbid": "Forbid"}


def normalize_cron_trigger_spec(trigger_spec: Any) -> dict[str, Any]:
    if not isinstance(trigger_spec, dict):
        raise ValueError("CRON_TRIGGER_SPEC_REQUIRED")
    if "schedules" in trigger_spec:
        raise ValueError("CRON_TRIGGER_MULTI_SCHEDULE_UNSUPPORTED")
    unsupported = sorted(str(key) for key in trigger_spec if key not in CRON_TRIGGER_SPEC_KEYS)
    if unsupported:
        raise ValueError(f"CRON_TRIGGER_SPEC_UNSUPPORTED_FIELD: {unsupported[0]}")
    expression = cron_expression(trigger_spec)
    timezone_name = cron_timezone_name(trigger_spec)
    normalized: dict[str, Any] = {
        "cron": expression,
        "timezone": timezone_name,
        "concurrencyPolicy": cron_concurrency_policy(trigger_spec),
    }
    if "payload" in trigger_spec:
        payload = trigger_spec.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("CRON_TRIGGER_PAYLOAD_INVALID")
        normalized["payload"] = deepcopy(payload)
    return normalized


def cron_expression(trigger_spec: dict[str, Any]) -> str:
    raw = trigger_spec.get("cron")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("CRON_TRIGGER_CRON_REQUIRED")
    expression = raw.strip()
    fields = expression.split()
    if fields and fields[0].upper().startswith(("CRON_TZ=", "TZ=")):
        raise ValueError("CRON_TRIGGER_EMBEDDED_TIMEZONE_UNSUPPORTED")
    if len(fields) != 5:
        raise ValueError("CRON_TRIGGER_FIVE_FIELD_REQUIRED")
    if not croniter.is_valid(expression, strict=True):
        raise ValueError("CRON_TRIGGER_CRON_INVALID")
    return expression


def cron_timezone(trigger_spec: dict[str, Any]) -> tuple[str, ZoneInfo]:
    name = cron_timezone_name(trigger_spec)
    try:
        return name, ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"CRON_TRIGGER_TIMEZONE_INVALID: {name}") from exc


def cron_timezone_name(trigger_spec: dict[str, Any]) -> str:
    raw = trigger_spec.get("timezone")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("CRON_TRIGGER_TIMEZONE_REQUIRED")
    name = raw.strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"CRON_TRIGGER_TIMEZONE_INVALID: {name}") from exc
    return name


def cron_concurrency_policy(trigger_spec: dict[str, Any]) -> str:
    raw = trigger_spec.get("concurrencyPolicy")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("CRON_TRIGGER_CONCURRENCY_POLICY_REQUIRED")
    normalized = raw.strip().lower()
    policy = CRON_TRIGGER_CONCURRENCY_POLICIES.get(normalized)
    if policy is None:
        raise ValueError(f"CRON_TRIGGER_CONCURRENCY_POLICY_UNSUPPORTED: {raw.strip()}")
    return policy
