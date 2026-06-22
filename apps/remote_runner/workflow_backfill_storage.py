from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError
from .storage_core import get_connection, now_iso


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


def _launch_row_to_dict(row: Any, *, created: bool) -> dict[str, Any]:
    return {
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
        "created": created,
    }


def _partition_row_to_dict(row: Any, *, created: bool) -> dict[str, Any]:
    return {
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
        "error": _loads_json(row["error_json"], None),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "created": created,
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
