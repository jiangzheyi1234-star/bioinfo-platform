from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .storage_core import now_iso


RUN_EVENT_SCHEMA_VERSION = "run-event.v2"


def append_run_event_v2(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    event_type: str,
    stage: str,
    state_version: int,
    message: str,
    request_id: str,
    payload: dict[str, Any],
    from_status: str | None = None,
    to_status: str | None = None,
    command_id: str | None = None,
    correlation_id: str | None = None,
    occurred_at: str | None = None,
    command_derived: bool = False,
    correlation_required: bool = False,
) -> dict[str, Any]:
    normalized_event_type = _required_text(event_type, "EVENT_TYPE_REQUIRED")
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_stage = _required_text(stage, "EVENT_STAGE_REQUIRED")
    normalized_message = _required_text(message, "EVENT_MESSAGE_REQUIRED")
    normalized_request_id = _required_text(request_id, "REQUEST_ID_REQUIRED")
    if not isinstance(payload, dict):
        raise ValueError("EVENT_PAYLOAD_OBJECT_REQUIRED")
    normalized_command_id = _optional_text(command_id)
    normalized_correlation_id = _optional_text(correlation_id)
    if command_derived and not normalized_command_id:
        raise ValueError("COMMAND_ID_REQUIRED")
    if correlation_required and not normalized_correlation_id:
        raise ValueError("CORRELATION_ID_REQUIRED")

    sequence = next_run_event_sequence(connection, normalized_run_id)
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    occurred = _optional_text(occurred_at) or now_iso()
    details = {
        "schema_version": RUN_EVENT_SCHEMA_VERSION,
        "occurred_at": occurred,
        "sequence": sequence,
        "command_id": normalized_command_id,
        "correlation_id": normalized_correlation_id,
        "payload": payload,
    }
    connection.execute(
        """
        INSERT INTO run_events (
            event_id, run_id, event_type, from_status, to_status, stage, state_version,
            message, request_id, created_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            normalized_run_id,
            normalized_event_type,
            _optional_text(from_status),
            _optional_text(to_status),
            normalized_stage,
            int(state_version),
            normalized_message,
            normalized_request_id,
            occurred,
            json.dumps(details, sort_keys=True),
        ),
    )
    return {
        "eventId": event_id,
        "runId": normalized_run_id,
        "eventType": normalized_event_type,
        **details,
    }


def next_run_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    rows = connection.execute(
        "SELECT event_id, details_json FROM run_events WHERE run_id = ? ORDER BY created_at ASC, event_id ASC",
        (run_id,),
    ).fetchall()
    highest = 0
    for index, row in enumerate(rows, start=1):
        details_json = row["details_json"]
        if not details_json:
            highest = max(highest, index)
            continue
        try:
            details = json.loads(details_json)
        except json.JSONDecodeError as exc:
            raise ValueError("EVENT_DETAILS_INVALID_JSON") from exc
        sequence = details.get("sequence") if isinstance(details, dict) else None
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            highest = max(highest, sequence)
        else:
            highest = max(highest, index)
    return highest + 1


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
