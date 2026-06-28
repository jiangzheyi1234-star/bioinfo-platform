from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError, RemoteRunnerNotFoundError
from .run_admission_read_model import fetch_run_admission_summary
from .storage_core import get_connection, now_iso


TRIGGER_ACTIVE_RUN_TERMINAL_STATUSES = ("completed", "failed", "canceled", "cancelled")


def create_workflow_trigger(
    cfg: RemoteRunnerConfig,
    *,
    name: str,
    source_type: str,
    server_id: str,
    pipeline_id: str,
    run_spec: dict[str, Any],
    trigger_spec: dict[str, Any],
    enabled: bool,
    actor: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    trigger_id = f"wtr_{uuid.uuid4().hex[:12]}"
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO workflow_triggers (
                trigger_id, name, source_type, server_id, pipeline_id, enabled,
                trigger_spec_json, run_spec_template_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trigger_id,
                _required_text(name, "TRIGGER_NAME_REQUIRED"),
                _required_text(source_type, "TRIGGER_SOURCE_TYPE_REQUIRED"),
                _required_text(server_id, "TRIGGER_SERVER_ID_REQUIRED"),
                _required_text(pipeline_id, "TRIGGER_PIPELINE_ID_REQUIRED"),
                1 if enabled else 0,
                _stable_json(trigger_spec),
                _stable_json(run_spec),
                str(actor or ""),
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
    trigger = fetch_workflow_trigger(cfg, trigger_id)
    if trigger is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_TRIGGER_NOT_FOUND")
    return trigger


def list_workflow_triggers(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM workflow_triggers
            ORDER BY updated_at DESC, trigger_id ASC
            """
        ).fetchall()
    return {"items": [_trigger_row_to_dict(row) for row in rows]}


def list_workflow_triggers_by_source(
    cfg: RemoteRunnerConfig,
    source_type: str,
    *,
    enabled_only: bool = False,
) -> dict[str, Any]:
    source = _required_text(source_type, "TRIGGER_SOURCE_TYPE_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM workflow_triggers
            WHERE source_type = ?
              AND (? = 0 OR enabled = 1)
            ORDER BY updated_at ASC, trigger_id ASC
            """,
            (source, 1 if enabled_only else 0),
        ).fetchall()
    return {"items": [_trigger_row_to_dict(row) for row in rows]}


def fetch_workflow_trigger(cfg: RemoteRunnerConfig, trigger_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM workflow_triggers WHERE trigger_id = ?",
            (_required_text(trigger_id, "TRIGGER_ID_REQUIRED"),),
        ).fetchone()
    return _trigger_row_to_dict(row) if row is not None else None


def require_workflow_trigger(cfg: RemoteRunnerConfig, trigger_id: str) -> dict[str, Any]:
    trigger = fetch_workflow_trigger(cfg, trigger_id)
    if trigger is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_TRIGGER_NOT_FOUND")
    return trigger


def record_workflow_trigger_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    event_type: str,
    external_event_id: str,
    idempotency_key: str,
    cursor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    trigger_id = _required_text(str(trigger.get("triggerId") or ""), "TRIGGER_ID_REQUIRED")
    source_type = _required_text(str(trigger.get("sourceType") or ""), "TRIGGER_SOURCE_TYPE_REQUIRED")
    payload_hash = _payload_hash(
        {
            "triggerId": trigger_id,
            "sourceType": source_type,
            "eventType": event_type,
            "externalEventId": external_event_id,
            "cursor": cursor,
            "payload": payload,
        }
    )
    with get_connection(cfg) as connection:
        existing = _existing_event_for_dedupe(
            connection,
            trigger_id=trigger_id,
            idempotency_key=idempotency_key,
            external_event_id=external_event_id,
        )
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise IdempotencyKeyReusedError("TRIGGER_EVENT_DEDUPE_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
            return _event_with_dispatch(connection, existing, created=False)

        timestamp = now_iso()
        trigger_event_id = f"wte_{uuid.uuid4().hex[:12]}"
        dispatch_id = f"wtd_{uuid.uuid4().hex[:12]}"
        request_id = f"req_{trigger_event_id}"
        dispatch_idempotency_key = f"trigger:{trigger_id}:{trigger_event_id}"
        connection.execute(
            """
            INSERT INTO workflow_trigger_events (
                trigger_event_id, trigger_id, source_type, event_type, external_event_id,
                idempotency_key, payload_hash, payload_json, cursor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trigger_event_id,
                trigger_id,
                source_type,
                _required_text(event_type, "TRIGGER_EVENT_TYPE_REQUIRED"),
                str(external_event_id or ""),
                _required_text(idempotency_key, "TRIGGER_EVENT_IDEMPOTENCY_KEY_REQUIRED"),
                payload_hash,
                _stable_json(payload),
                str(cursor or ""),
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO workflow_trigger_dispatches (
                dispatch_id, trigger_event_id, trigger_id, state, run_id, request_id,
                idempotency_key, error_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dispatch_id,
                trigger_event_id,
                trigger_id,
                "pending",
                None,
                request_id,
                dispatch_idempotency_key,
                None,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        event_row = connection.execute(
            "SELECT * FROM workflow_trigger_events WHERE trigger_event_id = ?",
            (trigger_event_id,),
        ).fetchone()
        return _event_with_dispatch(connection, event_row, created=True)


def mark_workflow_trigger_dispatch_submitted(
    cfg: RemoteRunnerConfig,
    *,
    trigger_event_id: str,
    run_id: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_trigger_dispatches
            SET state = 'submitted', run_id = ?, error_json = NULL, updated_at = ?
            WHERE trigger_event_id = ?
            """,
            (run_id, timestamp, trigger_event_id),
        )
        _stamp_run_trigger_context(connection, trigger_event_id=trigger_event_id, run_id=run_id)
        connection.commit()
    return fetch_workflow_trigger_event(cfg, trigger_event_id) or {}


def mark_workflow_trigger_dispatch_failed(
    cfg: RemoteRunnerConfig,
    *,
    trigger_event_id: str,
    error: dict[str, Any],
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_trigger_dispatches
            SET state = 'failed', error_json = ?, updated_at = ?
            WHERE trigger_event_id = ?
            """,
            (_stable_json(error), timestamp, trigger_event_id),
        )
        connection.commit()
    return fetch_workflow_trigger_event(cfg, trigger_event_id) or {}


def fetch_workflow_trigger_event(cfg: RemoteRunnerConfig, trigger_event_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM workflow_trigger_events WHERE trigger_event_id = ?",
            (_required_text(trigger_event_id, "TRIGGER_EVENT_ID_REQUIRED"),),
        ).fetchone()
        if row is None:
            return None
        return _event_with_dispatch(connection, row, created=False)


def fetch_workflow_trigger_event_for_dedupe(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str,
    idempotency_key: str,
    external_event_id: str,
) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = _existing_event_for_dedupe(
            connection,
            trigger_id=_required_text(trigger_id, "TRIGGER_ID_REQUIRED"),
            idempotency_key=_required_text(idempotency_key, "TRIGGER_EVENT_IDEMPOTENCY_KEY_REQUIRED"),
            external_event_id=str(external_event_id or ""),
        )
        return _event_with_dispatch(connection, row, created=False) if row is not None else None


def list_workflow_trigger_events(cfg: RemoteRunnerConfig, trigger_id: str) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM workflow_trigger_events
            WHERE trigger_id = ?
            ORDER BY created_at DESC, trigger_event_id ASC
            """,
            (_required_text(trigger_id, "TRIGGER_ID_REQUIRED"),),
        ).fetchall()
        return {"items": [_event_with_dispatch(connection, row, created=False) for row in rows]}


def fetch_active_workflow_trigger_dispatch_run(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    *,
    source_type: str | None = None,
) -> dict[str, Any] | None:
    source = str(source_type or "").strip()
    source_filter = "AND event.source_type = ?" if source else ""
    terminal_placeholders = ",".join("?" for _ in TRIGGER_ACTIVE_RUN_TERMINAL_STATUSES)
    params: list[Any] = [_required_text(trigger_id, "TRIGGER_ID_REQUIRED")]
    if source:
        params.append(source)
    params.extend(TRIGGER_ACTIVE_RUN_TERMINAL_STATUSES)
    with get_connection(cfg) as connection:
        row = connection.execute(
            f"""
            SELECT
                event.trigger_event_id,
                event.event_type,
                event.cursor,
                dispatch.run_id,
                run.status,
                run.stage,
                run.last_updated_at
            FROM workflow_trigger_dispatches dispatch
            JOIN workflow_trigger_events event
              ON event.trigger_event_id = dispatch.trigger_event_id
            JOIN runs run
              ON run.run_id = dispatch.run_id
            WHERE dispatch.trigger_id = ?
              {source_filter}
              AND dispatch.state = 'submitted'
              AND dispatch.run_id IS NOT NULL
              AND lower(COALESCE(run.status, '')) NOT IN ({terminal_placeholders})
            ORDER BY event.created_at DESC, dispatch.updated_at DESC, dispatch.dispatch_id DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    if row is None:
        return None
    return {
        "triggerEventId": row["trigger_event_id"],
        "eventType": row["event_type"],
        "cursor": row["cursor"],
        "runId": row["run_id"],
        "runStatus": row["status"],
        "runStage": row["stage"],
        "runLastUpdatedAt": row["last_updated_at"],
    }


def _stamp_run_trigger_context(connection: Any, *, trigger_event_id: str, run_id: str) -> None:
    event = connection.execute(
        "SELECT * FROM workflow_trigger_events WHERE trigger_event_id = ?",
        (trigger_event_id,),
    ).fetchone()
    if event is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_TRIGGER_EVENT_NOT_FOUND")
    connection.execute(
        """
        UPDATE runs
        SET trigger_id = ?, trigger_event_id = ?, trigger_source = ?, trigger_cursor = ?
        WHERE run_id = ?
        """,
        (
            event["trigger_id"],
            event["trigger_event_id"],
            event["source_type"],
            event["cursor"],
            run_id,
        ),
    )


def _existing_event_for_dedupe(
    connection: Any,
    *,
    trigger_id: str,
    idempotency_key: str,
    external_event_id: str,
) -> Any:
    by_idem = connection.execute(
        """
        SELECT *
        FROM workflow_trigger_events
        WHERE trigger_id = ? AND idempotency_key = ?
        """,
        (trigger_id, idempotency_key),
    ).fetchone()
    if by_idem is not None:
        return by_idem
    if not str(external_event_id or "").strip():
        return None
    return connection.execute(
        """
        SELECT *
        FROM workflow_trigger_events
        WHERE trigger_id = ? AND external_event_id = ?
        """,
        (trigger_id, external_event_id),
    ).fetchone()


def _event_with_dispatch(connection: Any, row: Any, *, created: bool) -> dict[str, Any]:
    event = _event_row_to_dict(row)
    dispatch = connection.execute(
        "SELECT * FROM workflow_trigger_dispatches WHERE trigger_event_id = ?",
        (event["triggerEventId"],),
    ).fetchone()
    run = _run_status_for_dispatch(connection, dispatch) if dispatch is not None else None
    event["dispatch"] = _dispatch_row_to_dict(dispatch, run=run) if dispatch is not None else None
    event["created"] = created
    return event


def _trigger_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "triggerId": row["trigger_id"],
        "name": row["name"],
        "sourceType": row["source_type"],
        "serverId": row["server_id"],
        "pipelineId": row["pipeline_id"],
        "enabled": bool(row["enabled"]),
        "triggerSpec": _loads_json(row["trigger_spec_json"], {}),
        "runSpec": _loads_json(row["run_spec_template_json"], {}),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _event_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "triggerEventId": row["trigger_event_id"],
        "triggerId": row["trigger_id"],
        "sourceType": row["source_type"],
        "eventType": row["event_type"],
        "externalEventId": row["external_event_id"],
        "idempotencyKey": row["idempotency_key"],
        "payloadHash": row["payload_hash"],
        "payload": _loads_json(row["payload_json"], {}),
        "cursor": row["cursor"],
        "createdAt": row["created_at"],
    }


def _dispatch_row_to_dict(row: Any, *, run: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "dispatchId": row["dispatch_id"],
        "triggerEventId": row["trigger_event_id"],
        "triggerId": row["trigger_id"],
        "state": row["state"],
        "runId": row["run_id"],
        "run": run,
        "requestId": row["request_id"],
        "idempotencyKey": row["idempotency_key"],
        "error": _loads_json(row["error_json"], None),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _run_status_for_dispatch(connection: Any, dispatch: Any) -> dict[str, Any] | None:
    run_id = str(dispatch["run_id"] or "").strip()
    if not run_id:
        return None
    row = connection.execute(
        """
        SELECT run_id, status, stage, last_updated_at
        FROM runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "runId": row["run_id"],
        "status": row["status"],
        "stage": row["stage"],
        "lastUpdatedAt": row["last_updated_at"],
        "admission": fetch_run_admission_summary(connection, str(row["run_id"])),
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = _stable_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return default
    if default is None:
        return parsed
    return parsed if isinstance(parsed, type(default)) else default


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized
