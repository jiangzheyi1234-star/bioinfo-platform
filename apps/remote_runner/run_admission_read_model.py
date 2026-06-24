from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


ADMISSION_SUMMARY_SCHEMA = "run-admission-summary.v1"


def fetch_run_admission_summary(connection: Any, run_id: str) -> dict[str, Any] | None:
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return None
    row = connection.execute(
        """
        SELECT
            job_id, state, queue_name, available_at, wait_reason_json,
            attempt_count, max_attempts, dead_lettered_at, updated_at
        FROM run_jobs
        WHERE run_id = ?
        """,
        (normalized_run_id,),
    ).fetchone()
    return admission_summary_from_job_row(row)


def admission_summary_from_job_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    wait_reason = _safe_wait_reason(_loads_json(_row_value(row, "wait_reason_json"), {}))
    return {
        "schemaVersion": ADMISSION_SUMMARY_SCHEMA,
        "jobState": _text(_row_value(row, "state")),
        "queueName": _text(_row_value(row, "queue_name")),
        "availableAt": _text(_row_value(row, "available_at")),
        "attemptCount": _int(_row_value(row, "attempt_count")),
        "maxAttempts": _int(_row_value(row, "max_attempts")),
        "waitReasonCode": wait_reason.get("code") if wait_reason else "",
        "waitReason": wait_reason,
        "deadLetteredAt": _nullable_text(_row_value(row, "dead_lettered_at")),
        "updatedAt": _text(_row_value(row, "updated_at")),
    }


def admission_summary_from_prefixed_row(row: Any, *, prefix: str) -> dict[str, Any] | None:
    if row is None:
        return None
    job_id = _row_value(row, f"{prefix}job_id")
    if not _optional_text(job_id):
        return None
    return admission_summary_from_job_row(
        {
            "job_id": job_id,
            "state": _row_value(row, f"{prefix}state"),
            "queue_name": _row_value(row, f"{prefix}queue_name"),
            "available_at": _row_value(row, f"{prefix}available_at"),
            "wait_reason_json": _row_value(row, f"{prefix}wait_reason_json"),
            "attempt_count": _row_value(row, f"{prefix}attempt_count"),
            "max_attempts": _row_value(row, f"{prefix}max_attempts"),
            "dead_lettered_at": _row_value(row, f"{prefix}dead_lettered_at"),
            "updated_at": _row_value(row, f"{prefix}updated_at"),
        }
    )


def _safe_wait_reason(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    code = _optional_text(value.get("code"))
    if not code:
        return None
    if code == "ADMISSION_SLOT_UNAVAILABLE":
        return {
            "code": "ADMISSION_SLOT_UNAVAILABLE",
            "maxActiveSlots": _int(value.get("maxActiveSlots")),
        }
    if code == "ADMISSION_SLOT_BUSY":
        return {
            "code": "ADMISSION_SLOT_BUSY",
            "slotIdPresent": bool(_optional_text(value.get("slotId"))),
        }
    if code == "ADMISSION_RESOURCES_UNAVAILABLE":
        resource = _optional_text(value.get("resource"))
        return {
            "code": "ADMISSION_RESOURCES_UNAVAILABLE",
            "resource": resource if resource in {"cpu", "memory_mb", "disk_mb", "gpu"} else "unknown",
            "available": _int(value.get("available")),
            "requested": _int(value.get("requested")),
        }
    return {"code": "ADMISSION_WAIT_UNSUPPORTED"}


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _loads_json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _nullable_text(value: Any) -> str | None:
    text = _optional_text(value)
    return text or None


def _text(value: Any) -> str:
    return _optional_text(value)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
