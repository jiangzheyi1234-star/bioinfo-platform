from __future__ import annotations

import hashlib
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
    actor: str | None = None,
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
    normalized_actor = _optional_text(actor)
    if command_derived and not normalized_command_id:
        raise ValueError("COMMAND_ID_REQUIRED")
    if correlation_required and not normalized_correlation_id:
        raise ValueError("CORRELATION_ID_REQUIRED")

    sequence = next_run_event_sequence(connection, normalized_run_id)
    event_id = f"evt_{uuid.uuid4().hex[:10]}"
    occurred = _optional_text(occurred_at) or now_iso()
    payload_json = _stable_json(payload)
    payload_hash = _sha256(payload_json)
    prev_event_hash = _latest_event_hash(connection, normalized_run_id)
    event_hash = _compute_event_hash(
        run_id=normalized_run_id,
        event_type=normalized_event_type,
        sequence=sequence,
        schema_version=RUN_EVENT_SCHEMA_VERSION,
        occurred_at=occurred,
        command_id=normalized_command_id,
        correlation_id=normalized_correlation_id,
        actor=normalized_actor,
        payload_hash=payload_hash,
        prev_event_hash=prev_event_hash,
    )
    details = {
        "schema_version": RUN_EVENT_SCHEMA_VERSION,
        "occurred_at": occurred,
        "sequence": sequence,
        "command_id": normalized_command_id,
        "correlation_id": normalized_correlation_id,
        "actor": normalized_actor,
        "payload_hash": payload_hash,
        "event_hash": event_hash,
        "prev_event_hash": prev_event_hash,
        "payload": payload,
    }
    connection.execute(
        """
        INSERT INTO run_events (
            event_id, run_id, event_type, seq, schema_version, from_status, to_status,
            stage, state_version, message, request_id, command_id, correlation_id, actor,
            payload_hash, event_hash, prev_event_hash, created_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            normalized_run_id,
            normalized_event_type,
            sequence,
            RUN_EVENT_SCHEMA_VERSION,
            _optional_text(from_status),
            _optional_text(to_status),
            normalized_stage,
            int(state_version),
            normalized_message,
            normalized_request_id,
            normalized_command_id,
            normalized_correlation_id,
            normalized_actor,
            payload_hash,
            event_hash,
            prev_event_hash,
            occurred,
            _stable_json(details),
        ),
    )
    return {
        "eventId": event_id,
        "runId": normalized_run_id,
        "eventType": normalized_event_type,
        **details,
    }


def record_run_command(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    command_type: str,
    payload: dict[str, Any],
    command_id: str | None = None,
    idempotency_key: str | None = None,
    actor: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_command_type = _required_text(command_type, "COMMAND_TYPE_REQUIRED")
    if not isinstance(payload, dict):
        raise ValueError("COMMAND_PAYLOAD_OBJECT_REQUIRED")
    normalized_command_id = _optional_text(command_id) or f"cmd_{uuid.uuid4().hex[:12]}"
    normalized_idempotency_key = _optional_text(idempotency_key)
    normalized_actor = _optional_text(actor)
    requested = _optional_text(requested_at) or now_iso()
    payload_json = _stable_json(payload)
    payload_hash = _sha256(payload_json)
    existing = connection.execute(
        "SELECT * FROM run_commands WHERE command_id = ?",
        (normalized_command_id,),
    ).fetchone()
    if existing is not None:
        if existing["payload_hash"] != payload_hash or existing["run_id"] != normalized_run_id:
            raise ValueError("RUN_COMMAND_CONFLICT")
        return _command_row_to_dict(existing)
    connection.execute(
        """
        INSERT INTO run_commands (
            command_id, run_id, command_type, idempotency_key, actor,
            payload_json, payload_hash, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalized_command_id,
            normalized_run_id,
            normalized_command_type,
            normalized_idempotency_key,
            normalized_actor,
            payload_json,
            payload_hash,
            requested,
        ),
    )
    row = connection.execute(
        "SELECT * FROM run_commands WHERE command_id = ?",
        (normalized_command_id,),
    ).fetchone()
    return _command_row_to_dict(row)


def next_run_event_sequence(connection: sqlite3.Connection, run_id: str) -> int:
    rows = connection.execute(
        "SELECT event_id, seq, details_json FROM run_events WHERE run_id = ? ORDER BY created_at ASC, event_id ASC",
        (run_id,),
    ).fetchall()
    highest = 0
    for index, row in enumerate(rows, start=1):
        row_sequence = row["seq"] if "seq" in row.keys() else None
        if isinstance(row_sequence, int) and not isinstance(row_sequence, bool) and row_sequence > 0:
            highest = max(highest, row_sequence)
            continue
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


def verify_run_event_hash_chain(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    rows = connection.execute(
        """
        SELECT *
        FROM run_events
        WHERE run_id = ? AND seq > 0
        ORDER BY seq ASC
        """,
        (normalized_run_id,),
    ).fetchall()
    previous_hash: str | None = None
    expected_sequence = 1
    for row in rows:
        sequence = int(row["seq"])
        if sequence != expected_sequence:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "SEQUENCE_GAP"}
        payload = _payload_from_event_row(row)
        payload_hash = _sha256(_stable_json(payload))
        if payload_hash != row["payload_hash"]:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "PAYLOAD_HASH_MISMATCH"}
        if row["prev_event_hash"] != previous_hash:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "PREV_EVENT_HASH_MISMATCH"}
        event_hash = _compute_event_hash(
            run_id=str(row["run_id"]),
            event_type=str(row["event_type"]),
            sequence=sequence,
            schema_version=str(row["schema_version"]),
            occurred_at=str(row["created_at"]),
            command_id=_optional_text(row["command_id"]),
            correlation_id=_optional_text(row["correlation_id"]),
            actor=_optional_text(row["actor"]),
            payload_hash=str(row["payload_hash"]),
            prev_event_hash=_optional_text(row["prev_event_hash"]),
        )
        if event_hash != row["event_hash"]:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "EVENT_HASH_MISMATCH"}
        previous_hash = str(row["event_hash"])
        expected_sequence += 1
    return {"valid": True, "checked": len(rows), "reason": None}


def _latest_event_hash(connection: sqlite3.Connection, run_id: str) -> str | None:
    row = connection.execute(
        """
        SELECT event_hash
        FROM run_events
        WHERE run_id = ? AND seq > 0 AND event_hash <> ''
        ORDER BY seq DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return _optional_text(row["event_hash"])


def _payload_from_event_row(row: sqlite3.Row) -> dict[str, Any]:
    details_json = row["details_json"]
    if not details_json:
        return {}
    try:
        details = json.loads(details_json)
    except json.JSONDecodeError as exc:
        raise ValueError("EVENT_DETAILS_INVALID_JSON") from exc
    payload = details.get("payload") if isinstance(details, dict) else None
    return payload if isinstance(payload, dict) else {}


def _compute_event_hash(
    *,
    run_id: str,
    event_type: str,
    sequence: int,
    schema_version: str,
    occurred_at: str,
    command_id: str | None,
    correlation_id: str | None,
    actor: str | None,
    payload_hash: str,
    prev_event_hash: str | None,
) -> str:
    return _sha256(
        _stable_json(
            {
                "actor": actor,
                "command_id": command_id,
                "correlation_id": correlation_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload_hash": payload_hash,
                "prev_event_hash": prev_event_hash,
                "run_id": run_id,
                "schema_version": schema_version,
                "sequence": int(sequence),
            }
        )
    )


def _command_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "commandId": row["command_id"],
        "runId": row["run_id"],
        "commandType": row["command_type"],
        "idempotencyKey": row["idempotency_key"],
        "actor": row["actor"],
        "payload": json.loads(row["payload_json"]),
        "payloadHash": row["payload_hash"],
        "requestedAt": row["requested_at"],
    }


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
