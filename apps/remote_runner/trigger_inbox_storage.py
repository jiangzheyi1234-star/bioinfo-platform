from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError, RemoteRunnerNotFoundError
from .storage_core import get_connection, now_iso


INBOX_LIST_SCHEMA_VERSION = "workflow-trigger-inbox-list.v1"
INBOX_SIGNATURE_STATE_UNSUPPORTED = "unsupported"
INBOX_STATE_ACCEPTED = "accepted"
INBOX_STATE_DISPATCHING = "dispatching"
INBOX_STATE_SUBMITTED = "submitted"
INBOX_STATE_DEAD_LETTERED = "dead_lettered"
INBOX_SIGNATURE_METADATA_SCHEMA = "workflow-trigger-inbox-signature-metadata.v1"


def record_workflow_trigger_inbox_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    source: str,
    event_type: str,
    provider_event_id: str,
    correlation_id: str,
    cursor: str,
    dedupe_key: str,
    payload: dict[str, Any],
    signature_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trigger_id = _required_text(str(trigger.get("triggerId") or ""), "TRIGGER_ID_REQUIRED")
    source = _required_text(source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    provider_event_id = _required_text(provider_event_id, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    dedupe_key = _required_text(dedupe_key, "WORKFLOW_TRIGGER_INBOX_DEDUPE_KEY_REQUIRED")
    payload_hash = _payload_hash(payload)
    payload_json = _stable_json(payload)
    payload_size_bytes = len(payload_json.encode("utf-8"))
    metadata = _signature_metadata(signature_metadata)
    timestamp = now_iso()
    received_at = str(metadata.get("receivedAt") or timestamp)
    with get_connection(cfg) as connection:
        existing = connection.execute(
            """
            SELECT *
            FROM workflow_trigger_inbox_events
            WHERE trigger_id = ? AND dedupe_key = ?
            """,
            (trigger_id, dedupe_key),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise IdempotencyKeyReusedError("WORKFLOW_TRIGGER_INBOX_DEDUPE_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
            _raise_if_raw_body_hash_changed(existing, metadata)
            connection.execute(
                """
                UPDATE workflow_trigger_inbox_events
                SET delivery_count = delivery_count + 1,
                    updated_at = ?
                WHERE inbox_event_id = ?
                """,
                (timestamp, existing["inbox_event_id"]),
            )
            connection.commit()
            return fetch_workflow_trigger_inbox_event(cfg, str(existing["inbox_event_id"])) | {"created": False}

        inbox_event_id = f"wti_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO workflow_trigger_inbox_events (
                inbox_event_id, trigger_id, source_type, source, event_type,
                provider_event_id, correlation_id, cursor, dedupe_key, payload_hash,
                payload_json, payload_size_bytes, signature_state, signature_details_json,
                raw_body_sha256, raw_body_size_bytes, raw_content_type, raw_header_names_json, state, delivery_count,
                trigger_event_id, run_id, failure_code, error_json,
                received_at, updated_at, dead_lettered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inbox_event_id,
                trigger_id,
                "webhook",
                source,
                _required_text(event_type, "WORKFLOW_TRIGGER_INBOX_EVENT_TYPE_REQUIRED"),
                provider_event_id,
                str(correlation_id or ""),
                str(cursor or ""),
                dedupe_key,
                payload_hash,
                payload_json,
                payload_size_bytes,
                INBOX_SIGNATURE_STATE_UNSUPPORTED,
                _stable_json(metadata["signatureDetails"]),
                str(metadata.get("rawBodySha256") or ""),
                int(metadata.get("rawBodySizeBytes") or 0),
                str(metadata.get("rawContentType") or ""),
                _stable_json(metadata.get("rawHeaderNames") or []),
                INBOX_STATE_ACCEPTED,
                1,
                None,
                None,
                "",
                None,
                received_at,
                timestamp,
                None,
            ),
        )
        connection.commit()
    return fetch_workflow_trigger_inbox_event(cfg, inbox_event_id) | {"created": True}


def mark_workflow_trigger_inbox_dispatching(
    cfg: RemoteRunnerConfig,
    *,
    inbox_event_id: str,
) -> dict[str, Any]:
    return _mark_inbox(
        cfg,
        inbox_event_id=inbox_event_id,
        state=INBOX_STATE_DISPATCHING,
        trigger_event_id=None,
        run_id=None,
        failure_code="",
        error=None,
        dead_lettered=False,
    )


def mark_workflow_trigger_inbox_submitted(
    cfg: RemoteRunnerConfig,
    *,
    inbox_event_id: str,
    trigger_event_id: str,
    run_id: str,
) -> dict[str, Any]:
    return _mark_inbox(
        cfg,
        inbox_event_id=inbox_event_id,
        state=INBOX_STATE_SUBMITTED,
        trigger_event_id=trigger_event_id,
        run_id=run_id,
        failure_code="",
        error=None,
        dead_lettered=False,
    )


def mark_workflow_trigger_inbox_dead_lettered(
    cfg: RemoteRunnerConfig,
    *,
    inbox_event_id: str,
    failure_code: str,
    error: dict[str, Any],
) -> dict[str, Any]:
    return _mark_inbox(
        cfg,
        inbox_event_id=inbox_event_id,
        state=INBOX_STATE_DEAD_LETTERED,
        trigger_event_id=None,
        run_id=None,
        failure_code=_required_text(failure_code, "WORKFLOW_TRIGGER_INBOX_FAILURE_CODE_REQUIRED"),
        error=error,
        dead_lettered=True,
    )


def mark_workflow_trigger_inbox_replay_failed(
    cfg: RemoteRunnerConfig,
    *,
    inbox_event_id: str,
    trigger_event_id: str,
    failure_code: str,
    error: dict[str, Any],
) -> dict[str, Any]:
    return _mark_inbox(
        cfg,
        inbox_event_id=inbox_event_id,
        state=INBOX_STATE_DEAD_LETTERED,
        trigger_event_id=trigger_event_id,
        run_id=None,
        failure_code=_required_text(failure_code, "WORKFLOW_TRIGGER_INBOX_FAILURE_CODE_REQUIRED"),
        error=error,
        dead_lettered=True,
    )


def fetch_workflow_trigger_inbox_event(
    cfg: RemoteRunnerConfig,
    inbox_event_id: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM workflow_trigger_inbox_events WHERE inbox_event_id = ?",
            (_required_text(inbox_event_id, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED"),),
        ).fetchone()
    if row is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_TRIGGER_INBOX_EVENT_NOT_FOUND")
    return _inbox_row_to_dict(row)


def fetch_workflow_trigger_inbox_payload(
    cfg: RemoteRunnerConfig,
    inbox_event_id: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT payload_hash, payload_json FROM workflow_trigger_inbox_events WHERE inbox_event_id = ?",
            (_required_text(inbox_event_id, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED"),),
        ).fetchone()
    if row is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_TRIGGER_INBOX_EVENT_NOT_FOUND")
    payload = _loads_json(row["payload_json"], {})
    if not isinstance(payload, dict):
        raise ValueError("WORKFLOW_TRIGGER_INBOX_PAYLOAD_INVALID")
    if _payload_hash(payload) != str(row["payload_hash"] or ""):
        raise ValueError("WORKFLOW_TRIGGER_INBOX_PAYLOAD_HASH_MISMATCH")
    return payload


def list_workflow_trigger_inbox_events(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    trigger_id = _required_text(trigger_id, "TRIGGER_ID_REQUIRED")
    bounded_limit = max(1, min(int(limit), 500))
    state_value = str(state or "").strip()
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM workflow_trigger_inbox_events
            WHERE trigger_id = ?
              AND (? = '' OR state = ?)
            ORDER BY received_at DESC, inbox_event_id ASC
            LIMIT ?
            """,
            (trigger_id, state_value, state_value, bounded_limit),
        ).fetchall()
    return {
        "schemaVersion": INBOX_LIST_SCHEMA_VERSION,
        "triggerId": trigger_id,
        "state": state_value or None,
        "items": [_inbox_row_to_dict(row) for row in rows],
    }


def inbox_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "inboxEventId": event["inboxEventId"],
        "triggerId": event["triggerId"],
        "source": event["source"],
        "eventId": event["eventId"],
        "eventType": event["eventType"],
        "correlationId": event["correlationId"] or None,
        "cursor": event["cursor"] or None,
        "dedupeKey": event["dedupeKey"],
        "payloadHash": event["payloadHash"],
        "payloadSizeBytes": event["payloadSizeBytes"],
        "signatureState": event["signatureState"],
        "signatureDetails": event["signatureDetails"],
        "rawBodySha256": event["rawBodySha256"],
        "rawBodySizeBytes": event["rawBodySizeBytes"],
        "rawContentType": event["rawContentType"],
        "rawHeaderNames": event["rawHeaderNames"],
        "state": event["state"],
        "deliveryCount": event["deliveryCount"],
        "triggerEventId": event["triggerEventId"],
        "runId": event["runId"],
        "failureCode": event["failureCode"] or None,
        "error": event["error"],
        "receivedAt": event["receivedAt"],
        "updatedAt": event["updatedAt"],
        "deadLetteredAt": event["deadLetteredAt"],
    }


def _mark_inbox(
    cfg: RemoteRunnerConfig,
    *,
    inbox_event_id: str,
    state: str,
    trigger_event_id: str | None,
    run_id: str | None,
    failure_code: str,
    error: dict[str, Any] | None,
    dead_lettered: bool,
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_trigger_inbox_events
            SET state = ?,
                trigger_event_id = COALESCE(?, trigger_event_id),
                run_id = COALESCE(?, run_id),
                failure_code = ?,
                error_json = ?,
                updated_at = ?,
                dead_lettered_at = CASE
                    WHEN ? = 1 THEN ?
                    WHEN ? = 'submitted' THEN NULL
                    ELSE dead_lettered_at
                END
            WHERE inbox_event_id = ?
            """,
            (
                state,
                trigger_event_id,
                run_id,
                failure_code,
                _stable_json(error) if error else None,
                timestamp,
                1 if dead_lettered else 0,
                timestamp,
                state,
                _required_text(inbox_event_id, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED"),
            ),
        )
        connection.commit()
    return fetch_workflow_trigger_inbox_event(cfg, inbox_event_id)


def _inbox_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "inboxEventId": row["inbox_event_id"],
        "triggerId": row["trigger_id"],
        "sourceType": row["source_type"],
        "source": row["source"],
        "eventType": row["event_type"],
        "eventId": row["provider_event_id"],
        "correlationId": row["correlation_id"],
        "cursor": row["cursor"],
        "dedupeKey": row["dedupe_key"],
        "payloadHash": row["payload_hash"],
        "payloadSizeBytes": int(row["payload_size_bytes"] or 0),
        "signatureState": row["signature_state"],
        "signatureDetails": _loads_json(row["signature_details_json"], {}),
        "rawBodySha256": row["raw_body_sha256"],
        "rawBodySizeBytes": int(row["raw_body_size_bytes"] or 0),
        "rawContentType": row["raw_content_type"],
        "rawHeaderNames": _loads_json(row["raw_header_names_json"], []),
        "state": row["state"],
        "deliveryCount": int(row["delivery_count"] or 0),
        "triggerEventId": row["trigger_event_id"],
        "runId": row["run_id"],
        "failureCode": row["failure_code"],
        "error": _loads_json(row["error_json"], None),
        "receivedAt": row["received_at"],
        "updatedAt": row["updated_at"],
        "deadLetteredAt": row["dead_lettered_at"],
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _signature_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(metadata or {})
    header_names = [str(name) for name in raw.get("rawHeaderNames") or []]
    details = {
        "schemaVersion": INBOX_SIGNATURE_METADATA_SCHEMA,
        "signatureState": INBOX_SIGNATURE_STATE_UNSUPPORTED,
        **({"rawBodySha256": str(raw.get("rawBodySha256") or "")} if raw.get("rawBodySha256") else {}),
        **({"rawBodySizeBytes": int(raw.get("rawBodySizeBytes") or 0)} if raw.get("rawBodySizeBytes") else {}),
        **({"contentType": str(raw.get("rawContentType") or "")} if raw.get("rawContentType") else {}),
        **({"receivedAt": str(raw.get("receivedAt") or "")} if raw.get("receivedAt") else {}),
        **({"headerNames": header_names} if header_names else {}),
    }
    return {
        "rawBodySha256": str(raw.get("rawBodySha256") or ""),
        "rawBodySizeBytes": int(raw.get("rawBodySizeBytes") or 0),
        "rawContentType": str(raw.get("rawContentType") or ""),
        "rawHeaderNames": header_names,
        "receivedAt": str(raw.get("receivedAt") or ""),
        "signatureDetails": details,
    }


def _raise_if_raw_body_hash_changed(existing: Any, metadata: dict[str, Any]) -> None:
    existing_hash = str(existing["raw_body_sha256"] or "")
    incoming_hash = str(metadata.get("rawBodySha256") or "")
    if existing_hash and incoming_hash and existing_hash != incoming_hash:
        raise IdempotencyKeyReusedError("WORKFLOW_TRIGGER_INBOX_DEDUPE_KEY_REUSED_WITH_DIFFERENT_RAW_BODY")


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _loads_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized
