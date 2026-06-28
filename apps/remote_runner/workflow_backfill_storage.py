from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError, RemoteRunnerNotFoundError
from .run_admission_read_model import admission_summary_from_prefixed_row
from .storage_core import get_connection, now_iso


BACKFILL_LAUNCH_LIST_SCHEMA = "workflow-backfill-launch-list.v1"
BACKFILL_LAUNCH_DETAIL_SCHEMA = "workflow-backfill-launch-detail.v1"
BACKFILL_RUN_ORDERS = {"forward", "backward"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled", "cancelled"}
NON_CANCELLABLE_RUN_STATUSES = TERMINAL_RUN_STATUSES | {"canceling"}
ADMITTING_PARTITION_STATES = {"admitting"}
ADVANCEABLE_LAUNCH_STATES = {"launching", "running", "submitted"}
BACKFILL_PARTITION_CANCELABLE_STATES = {"pending", "admitting", "submitted", "replayed"}


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
    normalized_run_order = _backfill_run_order(run_order)
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
                normalized_run_order,
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
    initial_state: str = "pending",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_spec = _required_dict(
        partition.get("runSpecPreview"),
        "WORKFLOW_BACKFILL_PARTITION_RUN_SPEC_REQUIRED",
    )
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
                initial_state,
                run_spec_hash,
                _stable_json(run_spec),
                _stable_json(error) if error else None,
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
        current = connection.execute(
            "SELECT error_json FROM workflow_backfill_partitions WHERE partition_id = ?",
            (partition_id,),
        ).fetchone()
        if current is None:
            raise RemoteRunnerNotFoundError("WORKFLOW_BACKFILL_PARTITION_NOT_FOUND")
        current_detail = _loads_json(current["error_json"], None) if current is not None else None
        retained_policy_json = (
            current["error_json"]
            if isinstance(current_detail, dict) and "action" in current_detail
            else None
        )
        cursor = connection.execute(
            """
            UPDATE workflow_backfill_partitions
            SET state = ?, trigger_event_id = ?, run_id = ?, error_json = ?, updated_at = ?
            WHERE partition_id = ? AND state = 'admitting'
            """,
            (state, trigger_event_id, run_id, retained_policy_json, timestamp, partition_id),
        )
        _require_single_row(cursor, "WORKFLOW_BACKFILL_PARTITION_STATE_CHANGED")
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
        cursor = connection.execute(
            """
            UPDATE workflow_backfill_partitions
            SET state = 'failed', error_json = ?, updated_at = ?
            WHERE partition_id = ? AND state = 'admitting'
            """,
            (_stable_json(error), timestamp, partition_id),
        )
        _require_single_row(cursor, "WORKFLOW_BACKFILL_PARTITION_STATE_CHANGED")
        connection.commit()
        row = connection.execute(
            "SELECT * FROM workflow_backfill_partitions WHERE partition_id = ?",
            (partition_id,),
        ).fetchone()
        return _partition_row_to_dict(row, created=False)


def mark_workflow_backfill_partition_cancel_requested(
    cfg: RemoteRunnerConfig,
    *,
    partition_id: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    states = sorted(BACKFILL_PARTITION_CANCELABLE_STATES)
    placeholders = ",".join("?" for _ in states)
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            f"""
            UPDATE workflow_backfill_partitions
            SET state = 'cancel_requested', updated_at = ?
            WHERE partition_id = ? AND state IN ({placeholders})
            """,
            (timestamp, partition_id, *states),
        )
        _require_single_row(cursor, "WORKFLOW_BACKFILL_PARTITION_STATE_CHANGED")
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


def mark_workflow_backfill_launch_canceling(
    cfg: RemoteRunnerConfig,
    *,
    launch_id: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE workflow_backfill_launches
            SET state = 'canceling', updated_at = ?
            WHERE launch_id = ?
            """,
            (timestamp, launch_id),
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
        items = []
        for row in launches:
            partitions = [
                _partition_row_to_dict(item, created=None)
                for item in _partition_rows_for_launch(connection, str(row["launch_id"]))
            ]
            items.append(_launch_with_partition_observability(row, partitions, created=None))
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
        **_launch_with_partition_observability(launch, partitions, created=None),
        "schemaVersion": BACKFILL_LAUNCH_DETAIL_SCHEMA,
        "partitions": partitions,
    }


def require_workflow_backfill_launch(cfg: RemoteRunnerConfig, launch_id: str) -> dict[str, Any]:
    launch = fetch_workflow_backfill_launch(cfg, launch_id)
    if launch is None:
        raise RemoteRunnerNotFoundError("WORKFLOW_BACKFILL_LAUNCH_NOT_FOUND")
    return launch


def latest_workflow_backfill_partitions_by_window(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str,
    windows: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if not windows:
        return {}
    normalized_trigger_id = _required_text(trigger_id, "TRIGGER_ID_REQUIRED")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    with get_connection(cfg) as connection:
        for window_start, window_end in windows:
            row = connection.execute(
                """
                SELECT
                    partition.*,
                    run.status AS run_status,
                    run.stage AS run_stage,
                    run.last_updated_at AS run_last_updated_at
                FROM workflow_backfill_partitions partition
                LEFT JOIN runs run
                  ON run.run_id = partition.run_id
                WHERE partition.trigger_id = ?
                  AND partition.window_start = ?
                  AND partition.window_end = ?
                  AND partition.state != 'skipped'
                ORDER BY partition.created_at DESC, partition.updated_at DESC, partition.partition_id DESC
                LIMIT 1
                """,
                (normalized_trigger_id, window_start, window_end),
            ).fetchone()
            if row is not None:
                result[(window_start, window_end)] = _partition_row_to_dict(row, created=None)
    return result


def claim_workflow_backfill_partitions_for_admission(
    cfg: RemoteRunnerConfig,
    *,
    launch_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized_limit = _bounded_limit(limit)
    timestamp = now_iso()
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        launch = connection.execute(
            "SELECT * FROM workflow_backfill_launches WHERE launch_id = ?",
            (_required_text(launch_id, "WORKFLOW_BACKFILL_LAUNCH_ID_REQUIRED"),),
        ).fetchone()
        if launch is None:
            raise RemoteRunnerNotFoundError("WORKFLOW_BACKFILL_LAUNCH_NOT_FOUND")
        if str(launch["state"] or "") not in ADVANCEABLE_LAUNCH_STATES:
            raise ValueError(f"WORKFLOW_BACKFILL_LAUNCH_STATE_NOT_ADVANCEABLE: {launch['state']}")
        order_direction = _partition_order_direction(launch)
        rows = connection.execute(
            f"""
            SELECT *
            FROM workflow_backfill_partitions
            WHERE launch_id = ? AND state = 'pending'
            ORDER BY partition_index {order_direction}
            LIMIT ?
            """,
            (launch_id, normalized_limit),
        ).fetchall()
        for row in rows:
            _loads_json_object(
                row["run_spec_json"],
                "WORKFLOW_BACKFILL_PARTITION_RUN_SPEC_JSON_INVALID",
            )
        partition_ids = [str(row["partition_id"]) for row in rows]
        if partition_ids:
            placeholders = ",".join("?" for _ in partition_ids)
            cursor = connection.execute(
                f"""
                UPDATE workflow_backfill_partitions
                SET state = 'admitting', updated_at = ?
                WHERE partition_id IN ({placeholders}) AND state = 'pending'
                """,
                (timestamp, *partition_ids),
            )
            if cursor.rowcount != len(partition_ids):
                raise ValueError("WORKFLOW_BACKFILL_PARTITION_CLAIM_CONFLICT")
            rows = connection.execute(
                f"""
                SELECT *
                FROM workflow_backfill_partitions
                WHERE partition_id IN ({placeholders})
                ORDER BY partition_index {order_direction}
                """,
                tuple(partition_ids),
            ).fetchall()
        connection.commit()
    return [_pending_partition_row_to_dict(row, launch=launch) for row in rows]


def list_workflow_backfill_advanceable_launch_ids(cfg: RemoteRunnerConfig, *, limit: int = 100) -> list[str]:
    normalized_limit = _bounded_limit(limit)
    placeholders = ",".join("?" for _ in ADVANCEABLE_LAUNCH_STATES)
    with get_connection(cfg) as connection:
        rows = connection.execute(
            f"""
            SELECT launch.launch_id
            FROM workflow_backfill_launches launch
            WHERE launch.state IN ({placeholders})
              AND EXISTS (
                  SELECT 1
                  FROM workflow_backfill_partitions partition
                  WHERE partition.launch_id = launch.launch_id AND partition.state = 'pending'
              )
            ORDER BY launch.created_at ASC, launch.launch_id ASC
            LIMIT ?
            """,
            (*sorted(ADVANCEABLE_LAUNCH_STATES), normalized_limit),
        ).fetchall()
    return [str(row["launch_id"]) for row in rows]


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
            run.last_updated_at AS run_last_updated_at,
            job.job_id AS admission_job_id,
            job.state AS admission_state,
            job.queue_name AS admission_queue_name,
            job.available_at AS admission_available_at,
            job.wait_reason_json AS admission_wait_reason_json,
            job.attempt_count AS admission_attempt_count,
            job.max_attempts AS admission_max_attempts,
            job.dead_lettered_at AS admission_dead_lettered_at,
            job.updated_at AS admission_updated_at
        FROM workflow_backfill_partitions partition
        LEFT JOIN workflow_trigger_events event
          ON event.trigger_event_id = partition.trigger_event_id
        LEFT JOIN workflow_trigger_dispatches dispatch
          ON dispatch.trigger_event_id = partition.trigger_event_id
        LEFT JOIN runs run
          ON run.run_id = partition.run_id
        LEFT JOIN run_jobs job
          ON job.run_id = partition.run_id
        WHERE partition.launch_id = ?
        ORDER BY partition.partition_index ASC
        """,
        (launch_id,),
    ).fetchall()


def _launch_row_to_dict(row: Any, *, created: bool | None) -> dict[str, Any]:
    request = _loads_json_object(
        row["request_json"],
        "WORKFLOW_BACKFILL_LAUNCH_REQUEST_JSON_INVALID",
    )
    run_order = _backfill_run_order(row["run_order"])
    payload = {
        "launchId": row["launch_id"],
        "triggerId": row["trigger_id"],
        "previewId": row["preview_id"],
        "sourceType": row["source_type"],
        "rangeStart": row["range_start"],
        "rangeEnd": row["range_end"],
        "timezone": row["timezone"],
        "partitionUnit": row["partition_unit"],
        "runOrder": run_order,
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
            "runOrder": run_order,
        },
        "launchStrategy": "one-run-per-partition",
        "concurrency": {
            "limit": _optional_int(request.get("concurrencyLimit")),
            "partitionCount": int(row["partition_count"]),
            "enforced": True,
        },
    }
    if created is not None:
        payload["created"] = created
    return payload


def _launch_with_partition_observability(
    row: Any,
    partitions: list[dict[str, Any]],
    *,
    created: bool | None,
) -> dict[str, Any]:
    payload = _launch_row_to_dict(row, created=created)
    summary = _partition_summary(partitions)
    payload["concurrency"] = {
        **payload["concurrency"],
        **_concurrency_observability(payload["concurrency"], summary),
    }
    payload["partitionSummary"] = summary
    payload["operationCapabilities"] = _operation_capabilities(partitions)
    return payload


def _partition_row_to_dict(row: Any, *, created: bool | None) -> dict[str, Any]:
    run_id = row["run_id"]
    dispatch_error = _loads_json(_row_value(row, "dispatch_error_json"), None)
    partition_detail = _loads_json(row["error_json"], None)
    policy_detail = (
        partition_detail
        if isinstance(partition_detail, dict) and "action" in partition_detail
        else None
    )
    state = str(row["state"] or "")
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
        "state": state,
        "blockedReason": _partition_blocked_reason(state, policy_detail or partition_detail),
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
                "admission": admission_summary_from_prefixed_row(row, prefix="admission_"),
            }
            if run_id and _row_value(row, "run_status")
            else None
        ),
        "error": None if policy_detail else partition_detail,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if created is not None:
        payload["created"] = created
    if policy_detail:
        payload["action"] = policy_detail.get("action")
        payload["existingState"] = policy_detail.get("existingState")
        payload["reprocessDecision"] = policy_detail.get("reprocessDecision")
    else:
        payload["action"] = "skip" if state == "skipped" else "create"
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
        "activeRunCount": sum(1 for item in items if _partition_has_active_run(item)),
        "occupiedConcurrencySlotCount": sum(1 for item in items if _partition_occupies_concurrency_slot(item)),
        "admittingPartitionCount": by_state.get("admitting", 0),
        "blockedPartitionCount": by_state.get("pending", 0),
        "failedPartitionCount": by_state.get("failed", 0),
        "pendingPartitionCount": by_state.get("pending", 0),
        "replayedPartitionCount": by_state.get("replayed", 0),
        "cancelRequestedPartitionCount": by_state.get("cancel_requested", 0),
        "cancellableRunCount": sum(1 for item in items if _partition_has_cancellable_run(item)),
    }


def _concurrency_observability(concurrency: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    limit = _optional_int(concurrency.get("limit")) or int(summary.get("partitionCount") or 1)
    occupied = int(summary.get("occupiedConcurrencySlotCount") or 0)
    return {
        "activeRunCount": int(summary.get("activeRunCount") or 0),
        "occupiedSlotCount": occupied,
        "availableSlots": max(0, limit - occupied),
        "pendingPartitionCount": int(summary.get("pendingPartitionCount") or 0),
        "blockedPartitionCount": int(summary.get("blockedPartitionCount") or 0),
        "admittingPartitionCount": int(summary.get("admittingPartitionCount") or 0),
    }


def _operation_capabilities(partitions: list[dict[str, Any]]) -> dict[str, Any]:
    cancellable = any(_partition_has_cancellable_run(item) for item in partitions)
    return {
        "cancel": cancellable,
        "cancelReason": "active-partition-runs" if cancellable else "no-cancellable-partition-runs",
        "replay": False,
        "deadLetter": False,
        "concurrencyEnforced": True,
    }


def _partition_has_active_run(partition: dict[str, Any]) -> bool:
    run = partition.get("run") if isinstance(partition.get("run"), dict) else {}
    run_id = str((run or {}).get("runId") or partition.get("runId") or "").strip()
    status = str((run or {}).get("status") or "").strip().lower()
    return bool(run_id and (not status or status not in TERMINAL_RUN_STATUSES))


def _partition_occupies_concurrency_slot(partition: dict[str, Any]) -> bool:
    state = str(partition.get("state") or "").strip().lower()
    return state in ADMITTING_PARTITION_STATES or _partition_has_active_run(partition)


def _partition_has_cancellable_run(partition: dict[str, Any]) -> bool:
    run = partition.get("run") if isinstance(partition.get("run"), dict) else {}
    run_id = str((run or {}).get("runId") or partition.get("runId") or "").strip()
    status = str((run or {}).get("status") or "").strip().lower()
    return bool(run_id and (not status or status not in NON_CANCELLABLE_RUN_STATUSES))


def _partition_blocked_reason(state: str, error: Any) -> str | None:
    if state == "pending":
        return "concurrency_limit"
    if state == "skipped" and isinstance(error, dict):
        return str(error.get("reason") or "skipped")
    return None


def _pending_partition_row_to_dict(row: Any, *, launch: Any) -> dict[str, Any]:
    run_spec = _loads_json_object(
        row["run_spec_json"],
        "WORKFLOW_BACKFILL_PARTITION_RUN_SPEC_JSON_INVALID",
    )
    return {
        "partitionId": row["partition_id"],
        "launchId": row["launch_id"],
        "triggerId": row["trigger_id"],
        "partitionKey": row["partition_key"],
        "index": int(row["partition_index"]),
        "window": {
            "start": row["window_start"],
            "end": row["window_end"],
            "timezone": launch["timezone"],
            "semantics": "half-open",
        },
        "cursor": row["cursor"],
        "idempotencyKey": row["idempotency_key"],
        "state": row["state"],
        "provenance": {
            "triggerId": row["trigger_id"],
            "sourceType": "backfill",
            "pipelineId": str(run_spec.get("pipelineId") or ""),
            "partitionUnit": launch["partition_unit"],
            "partitionKey": row["partition_key"],
        },
        "runSpecPreview": run_spec,
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


def _loads_json_object(value: str | None, code: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError as exc:
        raise ValueError(code) from exc
    if not isinstance(parsed, dict):
        raise ValueError(code)
    return parsed


def _required_dict(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 100
    return max(1, min(parsed, 500))


def _partition_order_direction(launch: Any) -> str:
    run_order = _backfill_run_order(launch["run_order"])
    if run_order == "backward":
        return "DESC"
    return "ASC"


def _backfill_run_order(value: Any) -> str:
    run_order = str(value or "").strip().lower()
    if run_order not in BACKFILL_RUN_ORDERS:
        raise ValueError(f"WORKFLOW_BACKFILL_RUN_ORDER_UNSUPPORTED: {value}")
    return run_order


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


def _require_single_row(cursor: Any, code: str) -> None:
    if cursor.rowcount != 1:
        raise ValueError(code)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        keys = row.keys()
    except AttributeError:
        return default
    return row[key] if key in keys else default
