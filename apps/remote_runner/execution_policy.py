from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 5
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 0
DEFAULT_QUEUE_TTL_SECONDS = 0
DEFAULT_START_TO_CLOSE_TIMEOUT_SECONDS = 0

RETRY_POLICY_SCHEMA_VERSION = "execution-retry-policy.v1"
TIMEOUT_POLICY_SCHEMA_VERSION = "execution-timeout-policy.v1"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": RETRY_POLICY_SCHEMA_VERSION,
            "maxAttempts": self.max_attempts,
            "backoffSeconds": self.backoff_seconds,
        }


@dataclass(frozen=True)
class TimeoutPolicy:
    queue_ttl_seconds: int = DEFAULT_QUEUE_TTL_SECONDS
    start_to_close_timeout_seconds: int = DEFAULT_START_TO_CLOSE_TIMEOUT_SECONDS
    heartbeat_timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": TIMEOUT_POLICY_SCHEMA_VERSION,
            "queueTtlSeconds": self.queue_ttl_seconds,
            "startToCloseTimeoutSeconds": self.start_to_close_timeout_seconds,
            "heartbeatTimeoutSeconds": self.heartbeat_timeout_seconds,
        }


@dataclass(frozen=True)
class ExecutionPolicy:
    queue_name: str
    retry: RetryPolicy
    timeout: TimeoutPolicy


def execution_policy_from_run_spec(run_spec: dict[str, Any]) -> ExecutionPolicy:
    execution = _object(run_spec.get("execution"), "EXECUTION_POLICY_INVALID")
    retry_raw = _object(
        execution.get("retryPolicy", execution.get("retry")),
        "EXECUTION_RETRY_POLICY_INVALID",
    )
    timeout_raw = _object(
        execution.get("timeoutPolicy", execution.get("timeouts")),
        "EXECUTION_TIMEOUT_POLICY_INVALID",
    )
    queue_name = _text(execution.get("queueName") or execution.get("queue") or "default", "QUEUE_NAME_REQUIRED")
    retry = RetryPolicy(
        max_attempts=_positive_int(
            _first_present(retry_raw, execution, keys=("maxAttempts",)),
            default=DEFAULT_MAX_ATTEMPTS,
            code="EXECUTION_MAX_ATTEMPTS_INVALID",
        ),
        backoff_seconds=_non_negative_int(
            _first_present(retry_raw, execution, keys=("backoffSeconds", "retryDelaySeconds")),
            default=DEFAULT_RETRY_BACKOFF_SECONDS,
            code="EXECUTION_RETRY_BACKOFF_INVALID",
        ),
    )
    timeout = TimeoutPolicy(
        queue_ttl_seconds=_non_negative_int(
            _first_present(timeout_raw, execution, keys=("queueTtlSeconds",)),
            default=DEFAULT_QUEUE_TTL_SECONDS,
            code="EXECUTION_QUEUE_TTL_INVALID",
        ),
        start_to_close_timeout_seconds=_non_negative_int(
            _first_present(
                timeout_raw,
                execution,
                keys=("startToCloseTimeoutSeconds", "attemptTimeoutSeconds"),
            ),
            default=DEFAULT_START_TO_CLOSE_TIMEOUT_SECONDS,
            code="EXECUTION_ATTEMPT_TIMEOUT_INVALID",
        ),
        heartbeat_timeout_seconds=_non_negative_int(
            _first_present(timeout_raw, execution, keys=("heartbeatTimeoutSeconds", "leaseSeconds")),
            default=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
            code="EXECUTION_HEARTBEAT_TIMEOUT_INVALID",
        ),
    )
    return ExecutionPolicy(queue_name=queue_name, retry=retry, timeout=timeout)


def retry_policy_from_job(row: Any, *, fallback_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS) -> RetryPolicy:
    raw = _json_object(row["retry_policy_json"])
    return RetryPolicy(
        max_attempts=_positive_int(
            raw.get("maxAttempts", row["max_attempts"]),
            default=int(row["max_attempts"]),
            code="EXECUTION_MAX_ATTEMPTS_INVALID",
        ),
        backoff_seconds=_non_negative_int(
            raw.get("backoffSeconds"),
            default=max(0, int(fallback_backoff_seconds)),
            code="EXECUTION_RETRY_BACKOFF_INVALID",
        ),
    )


def timeout_policy_from_job(row: Any) -> TimeoutPolicy:
    raw = _json_object(row["timeout_policy_json"])
    return TimeoutPolicy(
        queue_ttl_seconds=_non_negative_int(
            raw.get("queueTtlSeconds"),
            default=DEFAULT_QUEUE_TTL_SECONDS,
            code="EXECUTION_QUEUE_TTL_INVALID",
        ),
        start_to_close_timeout_seconds=_non_negative_int(
            raw.get("startToCloseTimeoutSeconds", raw.get("attemptTimeoutSeconds")),
            default=DEFAULT_START_TO_CLOSE_TIMEOUT_SECONDS,
            code="EXECUTION_ATTEMPT_TIMEOUT_INVALID",
        ),
        heartbeat_timeout_seconds=_non_negative_int(
            raw.get("heartbeatTimeoutSeconds", raw.get("leaseSeconds")),
            default=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
            code="EXECUTION_HEARTBEAT_TIMEOUT_INVALID",
        ),
    )


def heartbeat_timeout_seconds_for_job(row: Any, *, fallback_seconds: int) -> int:
    timeout = timeout_policy_from_job(row)
    if timeout.heartbeat_timeout_seconds > 0:
        return timeout.heartbeat_timeout_seconds
    return max(1, int(fallback_seconds))


def retry_backoff_seconds_for_job(row: Any, *, fallback_seconds: int) -> int:
    retry = retry_policy_from_job(row, fallback_backoff_seconds=fallback_seconds)
    return retry.backoff_seconds


def queue_ttl_seconds_for_job(row: Any) -> int:
    return timeout_policy_from_job(row).queue_ttl_seconds


def queue_ttl_exceeded(row: Any, *, now: str) -> bool:
    ttl_seconds = queue_ttl_seconds_for_job(row)
    if ttl_seconds <= 0:
        return False
    created_at = _parse_utc(row["created_at"])
    return _parse_utc(now) >= created_at + timedelta(seconds=ttl_seconds)


def attempt_start_to_close_exceeded(row: Any, *, now: str) -> bool:
    timeout = timeout_policy_from_job(row)
    if timeout.start_to_close_timeout_seconds <= 0:
        return False
    started_at = _parse_utc(row["started_at"])
    return _parse_utc(now) >= started_at + timedelta(seconds=timeout.start_to_close_timeout_seconds)


def _object(value: Any, code: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _first_present(*sources: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            if key in source:
                return source[key]
    return None


def _text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _positive_int(value: Any, *, default: int, code: str) -> int:
    parsed = _int_or_default(value, default=default, code=code)
    if parsed <= 0:
        raise ValueError(code)
    return parsed


def _non_negative_int(value: Any, *, default: int, code: str) -> int:
    parsed = _int_or_default(value, default=default, code=code)
    if parsed < 0:
        raise ValueError(code)
    return parsed


def _int_or_default(value: Any, *, default: int, code: str) -> int:
    if value in (None, ""):
        return int(default)
    if isinstance(value, bool):
        raise ValueError(code)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc


def _json_object(value: str | None) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("EXECUTION_TIMESTAMP_REQUIRED")
    if text.endswith("Z"):
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
