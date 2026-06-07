from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def append_evidence_event(
    connection: Any,
    *,
    event_type: str,
    schema_name: str,
    subject_kind: str,
    subject_id: str,
    payload: dict[str, Any],
    schema_version: str = "v1",
    producer: str = "remote_runner",
    occurred_at: str | None = None,
) -> dict[str, Any]:
    normalized_event_type = _required(event_type, "EVIDENCE_EVENT_TYPE_REQUIRED")
    normalized_schema_name = _required(schema_name, "EVIDENCE_SCHEMA_NAME_REQUIRED")
    normalized_schema_version = _required(schema_version, "EVIDENCE_SCHEMA_VERSION_REQUIRED")
    normalized_subject_kind = _required(subject_kind, "EVIDENCE_SUBJECT_KIND_REQUIRED")
    normalized_subject_id = _required(subject_id, "EVIDENCE_SUBJECT_ID_REQUIRED")
    normalized_payload = payload if isinstance(payload, dict) else {}
    timestamp = str(occurred_at or now_iso())
    schema = _ensure_evidence_schema(
        connection,
        name=normalized_schema_name,
        version=normalized_schema_version,
        created_at=timestamp,
    )
    previous = connection.execute(
        """
        SELECT seq, event_hash
        FROM evidence_events
        ORDER BY seq DESC
        LIMIT 1
        """
    ).fetchone()
    seq = int(previous["seq"] or 0) + 1 if previous is not None else 1
    prev_event_hash = str(previous["event_hash"] or "") if previous is not None else ""
    payload_hash = _sha256_json(normalized_payload)
    event_hash = _sha256_json(
        {
            "eventSchemaId": schema["schemaId"],
            "eventType": normalized_event_type,
            "occurredAt": timestamp,
            "payloadHash": payload_hash,
            "prevEventHash": prev_event_hash,
            "producer": str(producer or ""),
            "seq": seq,
            "subjectId": normalized_subject_id,
            "subjectKind": normalized_subject_kind,
        }
    )
    event_id = f"evid_{event_hash[:16]}"
    connection.execute(
        """
        INSERT INTO evidence_events (
            event_id, seq, event_type, event_schema_id, subject_kind, subject_id,
            producer, payload_json, payload_hash, event_hash, prev_event_hash,
            occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            seq,
            normalized_event_type,
            schema["schemaId"],
            normalized_subject_kind,
            normalized_subject_id,
            str(producer or ""),
            _json(normalized_payload),
            payload_hash,
            event_hash,
            prev_event_hash,
            timestamp,
        ),
    )
    return {
        "eventId": event_id,
        "seq": seq,
        "eventType": normalized_event_type,
        "schema": schema,
        "subjectKind": normalized_subject_kind,
        "subjectId": normalized_subject_id,
        "producer": str(producer or ""),
        "payload": dict(normalized_payload),
        "payloadHash": payload_hash,
        "eventHash": event_hash,
        "prevEventHash": prev_event_hash,
        "occurredAt": timestamp,
    }


def list_evidence_events(
    cfg: RemoteRunnerConfig,
    *,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if str(subject_kind or "").strip():
        clauses.append("events.subject_kind = ?")
        params.append(str(subject_kind or "").strip())
    if str(subject_id or "").strip():
        clauses.append("events.subject_id = ?")
        params.append(str(subject_id or "").strip())
    if str(event_type or "").strip():
        clauses.append("events.event_type = ?")
        params.append(str(event_type or "").strip())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(cfg) as connection:
        rows = connection.execute(
            f"""
            SELECT events.*, schemas.name AS schema_name, schemas.version AS schema_version,
                   schemas.content_hash AS schema_content_hash
            FROM evidence_events AS events
            JOIN evidence_schemas AS schemas
              ON schemas.schema_id = events.event_schema_id
            {where_sql}
            ORDER BY events.seq ASC
            LIMIT ?
            """,
            (*params, min(500, max(1, int(limit)))),
        ).fetchall()
    return [_event_row_to_dict(row) for row in rows]


def _ensure_evidence_schema(connection: Any, *, name: str, version: str, created_at: str) -> dict[str, str]:
    schema_id = f"{name}:{version}"
    schema_json = {
        "type": "object",
        "title": name,
        "x-h2ometa-evidence-schema-version": version,
    }
    content_hash = _sha256_json(schema_json)
    connection.execute(
        """
        INSERT INTO evidence_schemas (
            schema_id, name, version, json_schema_json, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(schema_id) DO NOTHING
        """,
        (schema_id, name, version, _json(schema_json), content_hash, created_at),
    )
    return {
        "schemaId": schema_id,
        "name": name,
        "version": version,
        "contentHash": content_hash,
    }


def _event_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "eventId": row["event_id"],
        "seq": int(row["seq"] or 0),
        "eventType": row["event_type"],
        "schema": {
            "schemaId": row["event_schema_id"],
            "name": row["schema_name"],
            "version": row["schema_version"],
            "contentHash": row["schema_content_hash"],
        },
        "subjectKind": row["subject_kind"],
        "subjectId": row["subject_id"],
        "producer": row["producer"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "payloadHash": row["payload_hash"],
        "eventHash": row["event_hash"],
        "prevEventHash": row["prev_event_hash"] or "",
        "occurredAt": row["occurred_at"],
    }


def _required(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text


def _sha256_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
