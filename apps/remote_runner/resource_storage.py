from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


CONTROLLER_OWNED_CONDITION_TYPES = {
    "Ready",
    "Synced",
    "Reconciling",
    "Stalled",
    "Deleting",
    "Orphaned",
    "GCFailed",
    "Exhausted",
}


def apply_resource(
    cfg: RemoteRunnerConfig,
    *,
    kind: str,
    name: str,
    desired: dict[str, Any],
    owner_kind: str | None = None,
    owner_id: str | None = None,
    finalizers: list[str] | None = None,
    conditions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_kind = _required_text(kind, "RESOURCE_KIND_REQUIRED")
    normalized_name = _required_text(name, "RESOURCE_NAME_REQUIRED")
    normalized_owner_kind = _optional_text(owner_kind)
    normalized_owner_id = _optional_text(owner_id)
    if bool(normalized_owner_kind) != bool(normalized_owner_id):
        raise ValueError("RESOURCE_OWNER_REF_INCOMPLETE")
    desired_json = _stable_json(_required_object(desired, "RESOURCE_DESIRED_OBJECT_REQUIRED"))
    finalizers_json = _stable_json(_text_list(finalizers or []))
    conditions_json = _stable_json(_caller_owned_conditions(conditions or []))
    updated_at = now_iso()

    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT * FROM resources WHERE kind = ? AND name = ?",
            (normalized_kind, normalized_name),
        ).fetchone()
        if existing is None:
            resource_id = f"res_{uuid.uuid4().hex[:12]}"
            connection.execute(
                """
                INSERT INTO resources (
                    resource_id, kind, name, desired_json, observed_json, status,
                    owner_kind, owner_id, finalizers_json, deletion_timestamp,
                    conditions_json, generation, observed_generation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource_id,
                    normalized_kind,
                    normalized_name,
                    desired_json,
                    "{}",
                    "pending",
                    normalized_owner_kind,
                    normalized_owner_id,
                    finalizers_json,
                    None,
                    conditions_json,
                    1,
                    0,
                    updated_at,
                    updated_at,
                ),
            )
            _append_resource_event(
                connection,
                resource_id=resource_id,
                event_type="resource_created",
                payload={"kind": normalized_kind, "name": normalized_name},
                occurred_at=updated_at,
            )
            connection.commit()
            return _fetch_resource_by_id(connection, resource_id)

        generation = int(existing["generation"])
        metadata_changed = (
            existing["owner_kind"] != normalized_owner_kind
            or existing["owner_id"] != normalized_owner_id
            or existing["finalizers_json"] != finalizers_json
            or existing["conditions_json"] != conditions_json
        )
        desired_changed = existing["desired_json"] != desired_json
        if desired_changed or metadata_changed:
            next_generation = generation + 1 if desired_changed else generation
            connection.execute(
                """
                UPDATE resources
                SET desired_json = ?, owner_kind = ?, owner_id = ?, finalizers_json = ?,
                    conditions_json = ?, generation = ?, updated_at = ?
                WHERE resource_id = ?
                """,
                (
                    desired_json,
                    normalized_owner_kind,
                    normalized_owner_id,
                    finalizers_json,
                    conditions_json,
                    next_generation,
                    updated_at,
                    existing["resource_id"],
                ),
            )
            _append_resource_event(
                connection,
                resource_id=existing["resource_id"],
                event_type="resource_desired_changed" if desired_changed else "resource_metadata_changed",
                payload={"generation": next_generation},
                occurred_at=updated_at,
            )
            connection.commit()
        return _fetch_resource_by_id(connection, existing["resource_id"])


def mark_resource_for_deletion(
    cfg: RemoteRunnerConfig,
    resource_id: str,
    *,
    deleted_at: str | None = None,
) -> dict[str, Any]:
    normalized_resource_id = _required_text(resource_id, "RESOURCE_ID_REQUIRED")
    occurred_at = _optional_text(deleted_at) or now_iso()
    with get_connection(cfg) as connection:
        existing = _fetch_resource_row(connection, normalized_resource_id)
        if existing["deletion_timestamp"]:
            return _row_to_resource(existing)
        connection.execute(
            """
            UPDATE resources
            SET deletion_timestamp = ?, status = ?, updated_at = ?
            WHERE resource_id = ?
            """,
            (occurred_at, "deleting", occurred_at, normalized_resource_id),
        )
        _append_resource_event(
            connection,
            resource_id=normalized_resource_id,
            event_type="resource_deletion_requested",
            payload={"deletionTimestamp": occurred_at},
            occurred_at=occurred_at,
        )
        connection.commit()
        return _fetch_resource_by_id(connection, normalized_resource_id)


def enqueue_reconcile(
    cfg: RemoteRunnerConfig,
    resource_id: str,
    *,
    reason: str,
    now: str | None = None,
    dedup_key: str | None = None,
    max_attempts: int = 12,
) -> dict[str, Any]:
    normalized_resource_id = _required_text(resource_id, "RESOURCE_ID_REQUIRED")
    normalized_reason = _required_text(reason, "RECONCILE_REASON_REQUIRED")
    dedup_suffix = _optional_text(dedup_key) or normalized_reason
    normalized_dedup_key = f"{normalized_resource_id}:{dedup_suffix}"
    available_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        _fetch_resource_row(connection, normalized_resource_id)
        existing = connection.execute(
            "SELECT * FROM reconcile_queue WHERE dedup_key = ?",
            (normalized_dedup_key,),
        ).fetchone()
        if existing is not None:
            if existing["state"] == "exhausted":
                connection.execute(
                    """
                    UPDATE reconcile_queue
                    SET state = ?, available_at = ?, claimed_by = NULL, claimed_until = NULL,
                        attempts = 0, backoff_seconds = 1, max_attempts = ?,
                        jitter_seed = ?, last_error = NULL, updated_at = ?
                    WHERE item_id = ?
                    """,
                    (
                        "pending",
                        available_at,
                        int(max_attempts),
                        uuid.uuid4().hex,
                        available_at,
                        existing["item_id"],
                    ),
                )
                connection.commit()
                return _fetch_reconcile_item(connection, existing["item_id"])
            return _row_to_reconcile_item(existing)
        item_id = f"rq_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO reconcile_queue (
                item_id, resource_id, dedup_key, reason, state, available_at,
                claimed_by, claimed_until, attempts, backoff_seconds, max_attempts,
                jitter_seed, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                normalized_resource_id,
                normalized_dedup_key,
                normalized_reason,
                "pending",
                available_at,
                None,
                None,
                0,
                1,
                int(max_attempts),
                uuid.uuid4().hex,
                None,
                available_at,
                available_at,
            ),
        )
        connection.commit()
        return _fetch_reconcile_item(connection, item_id)


def record_reconcile_failure(
    cfg: RemoteRunnerConfig,
    item_id: str,
    *,
    error: str,
    now: str | None = None,
    max_backoff_seconds: int = 300,
) -> dict[str, Any]:
    normalized_item_id = _required_text(item_id, "RECONCILE_ITEM_ID_REQUIRED")
    occurred_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT * FROM reconcile_queue WHERE item_id = ?",
            (normalized_item_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(normalized_item_id)
        attempts = int(existing["attempts"]) + 1
        max_attempts = int(existing["max_attempts"])
        backoff_seconds = min(
            max(int(existing["backoff_seconds"]) * 2, 1),
            max(int(max_backoff_seconds), 1),
        )
        delay_seconds = backoff_seconds + _stable_jitter_seconds(
            str(existing["jitter_seed"]),
            attempts,
            min(backoff_seconds, 5),
        )
        available_at = _add_seconds(occurred_at, delay_seconds)
        state = "exhausted" if attempts >= max_attempts else "pending"
        connection.execute(
            """
            UPDATE reconcile_queue
            SET state = ?, available_at = ?, claimed_by = NULL, claimed_until = NULL,
                attempts = ?, backoff_seconds = ?, last_error = ?, updated_at = ?
            WHERE item_id = ?
            """,
            (
                state,
                available_at,
                attempts,
                backoff_seconds,
                str(error or ""),
                occurred_at,
                normalized_item_id,
            ),
        )
        connection.commit()
        return _fetch_reconcile_item(connection, normalized_item_id)


def claim_reconcile_item(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    normalized_worker_id = _required_text(worker_id, "RECONCILE_WORKER_ID_REQUIRED")
    claimed_at = _optional_text(now) or now_iso()
    claimed_until = _add_seconds(claimed_at, max(1, int(lease_seconds)))
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT *
            FROM reconcile_queue
            WHERE (
                state = 'pending'
                AND available_at <= ?
            ) OR (
                state = 'claimed'
                AND (claimed_until IS NULL OR claimed_until < ?)
            )
            ORDER BY available_at ASC, created_at ASC, item_id ASC
            LIMIT 1
            """,
            (claimed_at, claimed_at),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
            """
            UPDATE reconcile_queue
            SET state = 'claimed', claimed_by = ?, claimed_until = ?, updated_at = ?
            WHERE item_id = ?
            """,
            (normalized_worker_id, claimed_until, claimed_at, row["item_id"]),
        )
        connection.commit()
        return _fetch_reconcile_item(connection, row["item_id"])


def record_reconcile_success(
    cfg: RemoteRunnerConfig,
    item_id: str,
    *,
    worker_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_item_id = _required_text(item_id, "RECONCILE_ITEM_ID_REQUIRED")
    normalized_worker_id = _optional_text(worker_id)
    occurred_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT * FROM reconcile_queue WHERE item_id = ?",
            (normalized_item_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(normalized_item_id)
        if normalized_worker_id and existing["claimed_by"] and existing["claimed_by"] != normalized_worker_id:
            raise ValueError("RECONCILE_ITEM_NOT_CLAIMED_BY_WORKER")
        connection.execute(
            """
            UPDATE reconcile_queue
            SET state = 'succeeded', available_at = ?, claimed_by = NULL,
                claimed_until = NULL, last_error = NULL, updated_at = ?
            WHERE item_id = ?
            """,
            (occurred_at, occurred_at, normalized_item_id),
        )
        _append_resource_event(
            connection,
            resource_id=existing["resource_id"],
            event_type="reconcile_succeeded",
            payload={"itemId": normalized_item_id},
            occurred_at=occurred_at,
        )
        connection.commit()
        return _fetch_reconcile_item(connection, normalized_item_id)


def update_resource_status(
    cfg: RemoteRunnerConfig,
    resource_id: str,
    *,
    status: str,
    observed: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_resource_id = _required_text(resource_id, "RESOURCE_ID_REQUIRED")
    normalized_status = _required_text(status, "RESOURCE_STATUS_REQUIRED")
    occurred_at = _optional_text(now) or now_iso()
    with get_connection(cfg) as connection:
        existing = _fetch_resource_row(connection, normalized_resource_id)
        observed_json = (
            _stable_json(_required_object(observed, "RESOURCE_OBSERVED_OBJECT_REQUIRED"))
            if observed is not None
            else existing["observed_json"]
        )
        conditions_json = _stable_json(_object_list(conditions)) if conditions is not None else existing["conditions_json"]
        connection.execute(
            """
            UPDATE resources
            SET observed_json = ?, status = ?, conditions_json = ?,
                observed_generation = generation, updated_at = ?
            WHERE resource_id = ?
            """,
            (observed_json, normalized_status, conditions_json, occurred_at, normalized_resource_id),
        )
        _append_resource_event(
            connection,
            resource_id=normalized_resource_id,
            event_type="resource_status_changed",
            payload={"status": normalized_status, "observedGeneration": int(existing["generation"])},
            occurred_at=occurred_at,
        )
        connection.commit()
        return _fetch_resource_by_id(connection, normalized_resource_id)


def _append_resource_event(
    connection: sqlite3.Connection,
    *,
    resource_id: str,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: str,
) -> None:
    row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) AS seq FROM resource_events WHERE resource_id = ?",
        (resource_id,),
    ).fetchone()
    seq = int(row["seq"]) + 1
    connection.execute(
        """
        INSERT INTO resource_events (
            event_id, resource_id, seq, event_type, payload_json, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"rev_{uuid.uuid4().hex[:12]}",
            resource_id,
            seq,
            event_type,
            _stable_json(payload),
            occurred_at,
        ),
    )


def _fetch_resource_by_id(connection: sqlite3.Connection, resource_id: str) -> dict[str, Any]:
    return _row_to_resource(_fetch_resource_row(connection, resource_id))


def _fetch_resource_row(connection: sqlite3.Connection, resource_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM resources WHERE resource_id = ?",
        (resource_id,),
    ).fetchone()
    if row is None:
        raise KeyError(resource_id)
    return row


def _fetch_reconcile_item(connection: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM reconcile_queue WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise KeyError(item_id)
    return _row_to_reconcile_item(row)


def _row_to_resource(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "resourceId": row["resource_id"],
        "kind": row["kind"],
        "name": row["name"],
        "desired": json.loads(row["desired_json"]),
        "observed": json.loads(row["observed_json"]),
        "status": row["status"],
        "ownerKind": row["owner_kind"],
        "ownerId": row["owner_id"],
        "finalizers": json.loads(row["finalizers_json"] or "[]"),
        "deletionTimestamp": row["deletion_timestamp"],
        "conditions": json.loads(row["conditions_json"] or "[]"),
        "generation": int(row["generation"]),
        "observedGeneration": int(row["observed_generation"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_reconcile_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "itemId": row["item_id"],
        "resourceId": row["resource_id"],
        "dedupKey": row["dedup_key"],
        "reason": row["reason"],
        "state": row["state"],
        "availableAt": row["available_at"],
        "claimedBy": row["claimed_by"],
        "claimedUntil": row["claimed_until"],
        "attempts": int(row["attempts"]),
        "backoffSeconds": int(row["backoff_seconds"]),
        "maxAttempts": int(row["max_attempts"]),
        "lastError": row["last_error"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _required_object(value: dict[str, Any], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _object_list(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("RESOURCE_CONDITIONS_ARRAY_REQUIRED")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("RESOURCE_CONDITION_OBJECT_REQUIRED")
    return value


def _caller_owned_conditions(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conditions = _object_list(value)
    for condition in conditions:
        condition_type = str(condition.get("type") or "").strip()
        if condition_type in CONTROLLER_OWNED_CONDITION_TYPES:
            raise ValueError("RESOURCE_CONDITION_CONTROLLER_OWNED")
    return conditions


def _text_list(value: list[str]) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("RESOURCE_FINALIZERS_ARRAY_REQUIRED")
    normalized = []
    for item in value:
        text = _required_text(str(item), "RESOURCE_FINALIZER_REQUIRED")
        if text not in normalized:
            normalized.append(text)
    return normalized


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_jitter_seconds(seed: str, attempt: int, limit: int) -> int:
    if limit <= 0:
        return 0
    digest = hashlib.sha256(f"{seed}:{attempt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % (limit + 1)


def _add_seconds(value: str, seconds: int) -> str:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (instant + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
