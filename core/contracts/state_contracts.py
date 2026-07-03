from __future__ import annotations

from typing import Any


RUN_STATUSES = frozenset({"queued", "running", "canceling", "completed", "failed", "canceled", "cancelled"})
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "canceled", "cancelled"})
RESULT_EXPORTABLE_RUN_STATUSES = frozenset({"completed", "failed"})
RETRYABLE_RUN_STATUSES = frozenset({"failed", "canceled", "cancelled"})

RUN_JOB_STATES = frozenset({"queued", "claimed", "completed", "failed", "cancelled"})
RUN_JOB_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

ATTEMPT_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "fenced"})
PUBLISHED_ATTEMPT_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
RUN_ATTEMPT_RESUMABLE_STATES = frozenset({"failed", "cancelled", "fenced"})
LEASE_RELEASED_STATES = frozenset({"expired", "fenced", "failed", "canceled", "cancelled"})

TOOL_PREPARE_JOB_STATUSES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "waiting_resource", "exhausted"}
)
ACTIVE_TOOL_PREPARE_JOB_STATUSES = frozenset({"queued", "running"})
TERMINAL_TOOL_PREPARE_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "waiting_resource", "exhausted"}
)

BACKFILL_RUN_ORDERS = frozenset({"forward", "backward"})
BACKFILL_ADVANCEABLE_LAUNCH_STATES = frozenset({"launching", "running", "submitted"})
BACKFILL_PARTITION_CANCELABLE_STATES = frozenset({"pending", "admitting", "submitted", "replayed"})
BACKFILL_PENDING_PARTITION_STATES = frozenset({"pending", "admitting"})


def normalize_state(value: Any) -> str:
    return str(value or "").strip().lower()


def is_terminal_run_status(status: Any) -> bool:
    return normalize_state(status) in TERMINAL_RUN_STATUSES


def is_result_exportable_run_status(status: Any) -> bool:
    return normalize_state(status) in RESULT_EXPORTABLE_RUN_STATUSES


def is_active_tool_prepare_job_status(status: Any) -> bool:
    return normalize_state(status) in ACTIVE_TOOL_PREPARE_JOB_STATUSES


def is_terminal_tool_prepare_job_status(status: Any) -> bool:
    return normalize_state(status) in TERMINAL_TOOL_PREPARE_JOB_STATUSES


def ensure_known_run_status(status: Any, *, code: str = "RUN_STATUS_UNSUPPORTED") -> str:
    normalized = normalize_state(status)
    if normalized not in RUN_STATUSES:
        raise ValueError(f"{code}: {normalized or 'missing'}")
    return normalized


def terminal_status_sql(statuses: set[str] | frozenset[str]) -> str:
    return "(" + ", ".join(f"'{status}'" for status in sorted(statuses)) + ")"
