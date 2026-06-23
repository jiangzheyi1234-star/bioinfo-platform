from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError, RemoteRunnerNotFoundError
from .storage_core import get_connection, now_iso


BACKFILL_LAUNCH_LIST_SCHEMA = "workflow-backfill-launch-list.v1"
BACKFILL_LAUNCH_DETAIL_SCHEMA = "workflow-backfill-launch-detail.v1"


def record_workflow_backfill_launch(
    cfg: RemoteRunnerConfig,
    *,
    launch_id: str,
    trigger_id: str,
    preview_id: str,
    range_start: str,
    range_end: str,
    timezone: str,
    partition_unit: str,
    run_order: str,
    reprocess_behavior: str,
    partition_count: int,
    actor: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    payload_hash = _payload_hash(request)
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        existing = connection.execute(
            """
            SELECT *
            FROM workflow_backfill_launches
            WHERE trigger_id = ? AND preview_id = ?
            """,
            (trigger_id, preview_id),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise IdempotencyKeyReusedError("WORKFLOW_BACKFILL_LAUNCH_REPLAY_PAYLOAD_MISMATCH")
            return _launch_row_to_dict(existing, created=False)
        connection.execute(
            """
            INSERT INTO workflow_backfill_launches (
                launch_id, trigger_id, preview_id, source_type, range_start, range_end,
                timezone, partition_unit, run_order, reprocess_behavior, partition_count,
                state, actor, request_json, payload_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                launch_id,
                trigger_id,
                preview_id,
                "backfill",
                range_start,
                range_end,
                timezone,
                partition_unit,
                run_order,
                reprocess_behavior,
                int(partition_count),
                "launching",
                actor,
                _stable_json(request),
                payload_hash,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_launches WHERE launch_id = ?",
            (launch_id,),
        ).fetchone()
        return _launch_row_to_dict(row, created=True)


def record_workflow_backfill_partition(
    cfg: RemoteRunnerConfig,
    *,
    launch_id: str,
    trigger_id: str,
    partition: dict[str, Any],
) -> dict[str, Any]:
    run_spec = partition.get("runSpecPreview") if isinstance(partition.get("runSpecPreview"), dict) else {}
    run_spec_hash = _payload_hash(run_spec)
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        existing = connection.execute(
            """
            SELECT *
            FROM workflow_backfill_partitions
            WHERE trigger_id = ? AND partition_id = ?
            """,
            (trigger_id, partition["partitionId"]),
        ).fetchone()
        if existing is not None:
            if str(existing["run_spec_hash"]) != run_spec_hash:
                raise IdempotencyKeyReusedError("WORKFLOW_BACKFILL_PARTITION_REPLAY_PAYLOAD_MISMATCH")
            return _partition_row_to_dict(existing, created=False)
        connection.execute(
            """
            INSERT INTO workflow_backfill_partitions (
                partition_id, launch_id, trigger_id, partition_key, partition_index,
                window_start, window_end, cursor, idempotency_key, trigger_event_id,
                run_id, state, run_spec_hash, run_spec_json, error_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                partition["partitionId"],
                launch_id,
                trigger_id,
                partition["partitionKey"],
                int(partition["index"]),
                partition["window"]["start"],
                partition["window"]["end"],
                partition["cursor"],
                partition["idempotencyKey"],
                None,
                None,
                "pending",
                run_spec_hash,
                _stable_json(run_spec),
                None,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_partitions WHERE partition_id = ?",
            (partition["partitionId"],),
        ).fetchone()
        return _partition_row_to_dict(row, created=True)


def mark_workflow_backfill_partition_submitted(
    cfg: RemoteRunnerConfig,
    *,
    partition_id: str,
    trigger_event_id: str,
    run_id: str,
    replayed: bool,
) -> dict[str, Any]:
    timestamp = now_iso()
    state = "replayed" if replayed else "submitted"
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_backfill_partitions
            SET state = ?, trigger_event_id = ?, run_id = ?, error_json = NULL, updated_at = ?
            WHERE partition_id = ?
            """,
            (state, trigger_event_id, run_id, timestamp, partition_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_partitions WHERE partition_id = ?",
            (partition_id,),
        ).fetchone()
        return _partition_row_to_dict(row, created=False)


def mark_workflow_backfill_partition_failed(
    cfg: RemoteRunnerConfig,
    *,
    partition_id: str,
    error: dict[str, Any],
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_backfill_partitions
            SET state = 'failed', error_json = ?, updated_at = ?
            WHERE partition_id = ?
            """,
            (_stable_json(error), timestamp, partition_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_partitions WHERE partition_id = ?",
            (partition_id,),
        ).fetchone()
        return _partition_row_to_dict(row, created=False)


def mark_workflow_backfill_launch_finished(
    cfg: RemoteRunnerConfig,
    *,
    launch_id: str,
    state: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_backfill_launches
            SET state = ?, updated_at = ?
            WHERE launch_id = ?
            """,
            (state, timestamp, launch_id),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_launches WHERE launch_id = ?",
            (launch_id,),
        ).fetchone()
        return _launch_row_to_dict(row, created=False)


def list_workflow_backfill_launches(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    normalized_trigger_id = str(trigger_id or "").strip()
    normalized_limit = _bounded_limit(limit)
    params: list[Any] = []
    where_clause = ""
    if normalized_trigger_id:
        where_clause = "WHERE trigger_id = ?"
        params.append(normalized_trigger_id)
    params.append(normalized_limit)
    with get_connection(cfg) as connection:
        launches = connection.execute(
            f"""
            SELECT *
            FROM workflow_backfill_launches
            {where_clause}
            ORDER BY created_at DESC, launch_id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        items = [
            {
                **_launch_row_to_dict(row, created=None),
                "partitionSummary": _partition_summary(
                    _partition_row_to_dict(item, created=None)
                    for item in _partition_rows_for_launch(connection, str(row["launch_id"]))
                ),
            }
            for row in launches
        ]
    return {"schemaVersion": BACKFILL_LAUNCH_LIST_SCHEMA, "items": items}


def fetch_workflow_backfill_launch(cfg: RemoteRunnerConfig, launch_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        launch = connection.execute(
            "SELECT * FROM workflow_backfill_launches WHERE launch_id = ?",
            (_required_text(launch_id, "WORKFLOW_BACKFILL_LAUNCH_ID_REQUIRED"),),
        ).fetchone()
        if launch is None:
            return None
        partitions = [
            _partition_row_to_dict(row, created=None)
            for row in _partition_rows_for_launch(connection, str(launch["launch_id"]))
        ]
    return {
        **_launch_row_to_dict(launch, created=None),
        "schemaVersion": BACKFILL_LAUNCH_DETAIL_SCHEMA,
        "partitionSummary": _partition_summary(partitions),
        "partitions": partitions,
    }


def require_workflow_backfill_launch(cfg: RemoteRunnerConfig, launch_id: str) -> dict[str, Any]:
    launch = fetch_workflow_backfill_launch(cfg, launch_id)
    if launch is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_BACKFILL_LAUNCH_NOT_FOUND")
    return launch


def _partition_rows_for_launch(connection: Any, launch_id: str) -> list[Any]:
    return connection.execute(
        """
        SELECT
            partition.*,
            event.event_type AS trigger_event_type,
            dispatch.state AS dispatch_state,
            dispatch.request_id AS dispatch_request_id,
            dispatch.error_json AS dispatch_error_json,
            run.status AS run_status,
            run.stage AS run_stage,
            run.last_updated_at AS run_last_updated_at
        FROM workflow_backfill_partitions partition
        LEFT JOIN workflow_trigger_events event
          ON event.trigger_event_id = partition.trigger_event_id
        LEFT JOIN workflow_trigger_dispatches dispatch
          ON dispatch.trigger_event_id = partition.trigger_event_id
        LEFT JOIN runs run
          ON run.run_id = partition.run_id
        WHERE partition.launch_id = ?
        ORDER BY partition.partition_index ASC
        """,
        (launch_id,),
    ).fetchall()


def _launch_row_to_dict(row: Any, *, created: bool | None) -> dict[str, Any]:
    request = _loads_json(row["request_json"], {})
    payload = {
        "launchId": row["launch_id"],
        "triggerId": row["trigger_id"],
        "previewId": row["preview_id"],
        "sourceType": row["source_type"],
        "rangeStart": row["range_start"],
        "rangeEnd": row["range_end"],
        "timezone": row["timezone"],
        "partitionUnit": row["partition_unit"],
        "runOrder": row["run_order"],
        "reprocessBehavior": row["reprocess_behavior"],
        "partitionCount": int(row["partition_count"]),
        "state": row["state"],
        "actor": row["actor"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "range": {
            "start": row["range_start"],
            "end": row["range_end"],
            "timezone": row["timezone"],
            "partitionUnit": row["partition_unit"],
            "semantics": "half-open",
            "runOrder": row["run_order"],
        },
        "launchStrategy": "one-run-per-partition",
        "concurrency": {
            "limit": _optional_int(request.get("concurrencyLimit")),
            "partitionCount": int(row["partition_count"]),
            "enforced": False,
        },
    }
    if created is not None:
        payload["created"] = created
    return payload


def _partition_row_to_dict(row: Any, *, created: bool | None) -> dict[str, Any]:
    run_id = row["run_id"]
    dispatch_error = _loads_json(_row_value(row, "dispatch_error_json"), None)
    payload = {
        "partitionId": row["partition_id"],
        "launchId": row["launch_id"],
        "triggerId": row["trigger_id"],
        "partitionKey": row["partition_key"],
        "index": int(row["partition_index"]),
        "window": {
            "start": row["window_start"],
            "end": row["window_end"],
            "semantics": "half-open",
        },
        "cursor": row["cursor"],
        "idempotencyKey": row["idempotency_key"],
        "triggerEventId": row["trigger_event_id"],
        "runId": row["run_id"],
        "state": row["state"],
        "runSpecHash": row["run_spec_hash"],
        "triggerEventType": _row_value(row, "trigger_event_type"),
        "dispatch": (
            {
                "state": _row_value(row, "dispatch_state"),
                "requestId": _row_value(row, "dispatch_request_id"),
                "error": dispatch_error,
            }
            if _row_value(row, "dispatch_state")
            else None
        ),
        "run": (
            {
                "runId": run_id,
                "status": _row_value(row, "run_status"),
                "stage": _row_value(row, "run_stage"),
                "lastUpdatedAt": _row_value(row, "run_last_updated_at"),
            }
            if run_id and _row_value(row, "run_status")
            else None
        ),
        "error": _loads_json(row["error_json"], None),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if created is not None:
        payload["created"] = created
    return payload


def _partition_summary(partitions: Any) -> dict[str, Any]:
    items = list(partitions)
    by_state: dict[str, int] = {}
    for item in items:
        state = str(item.get("state") or "unknown")
        by_state[state] = by_state.get(state, 0) + 1
    return {
        "partitionCount": len(items),
        "states": by_state,
        "submittedRunCount": sum(1 for item in items if item.get("runId")),
        "failedPartitionCount": by_state.get("failed", 0),
        "pendingPartitionCount": by_state.get("pending", 0),
        "replayedPartitionCount": by_state.get("replayed", 0),
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    return max(1, min(parsed, 500))


def _optional_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _required_text(value: str, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        keys = row.keys()
    except AttributeError:
        return default
    return row[key] if key in keys else default
