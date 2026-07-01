from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from core.contracts.execution_activity import summarize_execution_activity

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerOperationBlockedError, RemoteRunnerReadinessError
from .execution_diagnostics import build_execution_diagnostics
from .storage_core import get_connection, now_iso


EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard.v1"
EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard-release.v1"
EXECUTION_LIFECYCLE_MAINTENANCE_KEY = "execution_lifecycle_maintenance"
EXECUTION_MAINTENANCE_ACTIVE_REASON = "EXECUTION_MAINTENANCE_ACTIVE"
EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES_REASON = "EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES"
EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON = "EXECUTION_LIFECYCLE_GUARD_BLOCKED"
EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON = "EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE"
EXECUTION_LIFECYCLE_GUARD_OWNER_MISMATCH_REASON = "EXECUTION_LIFECYCLE_GUARD_OWNER_MISMATCH"
EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON = "EXECUTION_LIFECYCLE_GUARD_INVALID_STATE"
EXECUTION_LIFECYCLE_ALLOWED_ACTIONS = {"ensure", "upgrade", "stop", "prune", "uninstall"}


def request_execution_lifecycle_guard(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    owner: str,
    ttl_seconds: int = 600,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_action = _action(action)
    normalized_owner = _owner(owner)
    timestamp = _timestamp(now)
    expires_at = _expires_at(timestamp, ttl_seconds)
    maintenance = _maintenance_payload(
        action=normalized_action,
        owner=normalized_owner,
        requested_at=timestamp,
        expires_at=expires_at,
        ttl_seconds=ttl_seconds,
    )
    active_worker_count = 0
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = _read_maintenance(connection, now=timestamp, clear_expired=True)
            if _is_conflicting_maintenance(existing, action=normalized_action, owner=normalized_owner):
                connection.rollback()
                raise RemoteRunnerOperationBlockedError(
                    EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON,
                    _active_conflict_payload(existing, requested_action=normalized_action, requested_owner=normalized_owner),
                )
            active_worker_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM run_workers WHERE stopped_at IS NULL",
                ).fetchone()["count"]
            )
            connection.execute(
                """
                UPDATE run_workers
                SET drain_requested_at = COALESCE(drain_requested_at, ?), updated_at = ?
                WHERE stopped_at IS NULL
                """,
                (timestamp, timestamp),
            )
            connection.execute(
                """
                INSERT INTO service_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (EXECUTION_LIFECYCLE_MAINTENANCE_KEY, _stable_json(maintenance)),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise

    try:
        diagnostics = build_execution_diagnostics(cfg, now=timestamp)
        activity = summarize_execution_activity(
            diagnostics,
            make_error=ValueError,
            require_diagnostics_ok=False,
            block_queued_jobs=False,
        )
    except Exception:
        _release_owned_maintenance_best_effort(
            cfg,
            action=normalized_action,
            owner=normalized_owner,
            now=timestamp,
        )
        raise
    payload = _guard_payload(
        action=normalized_action,
        owner=normalized_owner,
        maintenance=maintenance,
        active_worker_count=active_worker_count,
        activity=activity,
    )
    block_reasons = [str(item) for item in payload["blockReasons"]]
    if block_reasons:
        payload["reasonCode"] = _blocked_reason_code(block_reasons)
        payload["nextAction"] = "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_LIFECYCLE"
        if activity["activeLeases"]:
            payload["activeLeases"] = activity["activeLeases"]
        raise RemoteRunnerOperationBlockedError(str(payload["reasonCode"]), payload)
    return payload


def release_execution_lifecycle_guard(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    owner: str,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_action = _action(action)
    normalized_owner = _owner(owner)
    timestamp = _timestamp(now)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = _read_maintenance(connection, now=timestamp, clear_expired=True)
            if existing is None:
                connection.commit()
                return _release_payload(
                    action=normalized_action,
                    owner=normalized_owner,
                    released=False,
                    released_at=timestamp,
                    previous=None,
                )
            if _is_conflicting_maintenance(existing, action=normalized_action, owner=normalized_owner):
                connection.rollback()
                raise RemoteRunnerOperationBlockedError(
                    EXECUTION_LIFECYCLE_GUARD_OWNER_MISMATCH_REASON,
                    _active_conflict_payload(existing, requested_action=normalized_action, requested_owner=normalized_owner),
                )
            connection.execute("DELETE FROM service_state WHERE key = ?", (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,))
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
    return _release_payload(
        action=normalized_action,
        owner=normalized_owner,
        released=True,
        released_at=timestamp,
        previous=existing,
    )


def ensure_execution_lifecycle_admission_open(
    cfg: RemoteRunnerConfig,
    *,
    now: str | None = None,
) -> None:
    timestamp = _timestamp(now)
    with get_connection(cfg) as connection:
        try:
            maintenance = _read_maintenance(connection, now=timestamp, clear_expired=True)
        except ValueError as exc:
            raise RemoteRunnerReadinessError(
                f"{EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON}: execution lifecycle guard state is invalid"
            ) from exc
        if connection.in_transaction:
            connection.commit()
    if maintenance is None:
        return
    raise RemoteRunnerReadinessError(
        f"{EXECUTION_MAINTENANCE_ACTIVE_REASON}: execution control plane is in maintenance"
    )


def _read_maintenance(
    connection,
    *,
    now: str,
    clear_expired: bool,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT value FROM service_state WHERE key = ?",
        (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row["value"] or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
        raise ValueError(EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON)
    if not payload.get("active"):
        return None
    if _is_expired(payload, now):
        if clear_expired:
            connection.execute("DELETE FROM service_state WHERE key = ?", (EXECUTION_LIFECYCLE_MAINTENANCE_KEY,))
        return None
    return payload


def _is_conflicting_maintenance(
    maintenance: dict[str, Any] | None,
    *,
    action: str,
    owner: str,
) -> bool:
    if maintenance is None:
        return False
    return str(maintenance.get("action") or "") != action or str(maintenance.get("owner") or "") != owner


def _active_conflict_payload(
    maintenance: dict[str, Any] | None,
    *,
    requested_action: str,
    requested_owner: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
        "reasonCode": EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON,
        "requestedAction": requested_action,
        "requestedOwner": requested_owner,
        "activeMaintenance": maintenance or {},
        "nextAction": "WAIT_FOR_ACTIVE_MAINTENANCE_OR_RELEASE",
    }


def _maintenance_payload(
    *,
    action: str,
    owner: str,
    requested_at: str,
    expires_at: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
        "active": True,
        "reasonCode": EXECUTION_MAINTENANCE_ACTIVE_REASON,
        "action": action,
        "owner": owner,
        "requestedAt": requested_at,
        "expiresAt": expires_at,
        "ttlSeconds": int(ttl_seconds),
    }


def _guard_payload(
    *,
    action: str,
    owner: str,
    maintenance: dict[str, Any],
    active_worker_count: int,
    activity: dict[str, Any],
) -> dict[str, Any]:
    block_reasons = [str(item) for item in activity["blockReasons"]]
    return {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
        "action": action,
        "owner": owner,
        "idle": not block_reasons,
        "maintenanceActive": True,
        "requestedAt": maintenance["requestedAt"],
        "expiresAt": maintenance["expiresAt"],
        "activeWorkerCount": int(active_worker_count),
        "drainRequestedWorkerCount": int(active_worker_count),
        "activeLeaseCount": activity["activeLeaseCount"],
        "allocatedResourceCount": activity["allocatedResourceCount"],
        "resourceWaitCount": activity["resourceWaitCount"],
        "queuedJobCount": activity["queuedJobCount"],
        "claimedJobCount": activity["claimedJobCount"],
        "runningSlotCount": activity["runningSlotCount"],
        "blockReasons": block_reasons,
    }


def _release_payload(
    *,
    action: str,
    owner: str,
    released: bool,
    released_at: str,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
        "action": action,
        "owner": owner,
        "released": bool(released),
        "releasedAt": released_at,
        "previous": previous or {},
    }


def _blocked_reason_code(block_reasons: list[str]) -> str:
    if "active-workflow-leases" in block_reasons:
        return EXECUTION_LIFECYCLE_GUARD_ACTIVE_LEASES_REASON
    return EXECUTION_LIFECYCLE_GUARD_BLOCKED_REASON


def _release_owned_maintenance_best_effort(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    owner: str,
    now: str,
) -> None:
    try:
        release_execution_lifecycle_guard(cfg, action=action, owner=owner, now=now)
    except Exception:
        return


def _is_expired(payload: dict[str, Any], now: str) -> bool:
    expires_at = str(payload.get("expiresAt") or "")
    if not expires_at:
        return True
    return _parse_iso(expires_at) <= _parse_iso(now)


def _expires_at(now: str, ttl_seconds: int) -> str:
    safe_ttl = max(30, min(int(ttl_seconds or 600), 3600))
    return (_parse_iso(now) + timedelta(seconds=safe_ttl)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(EXECUTION_LIFECYCLE_GUARD_INVALID_STATE_REASON) from exc


def _action(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in EXECUTION_LIFECYCLE_ALLOWED_ACTIONS:
        raise ValueError(f"EXECUTION_LIFECYCLE_ACTION_UNSUPPORTED: {normalized}")
    return normalized


def _owner(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("EXECUTION_LIFECYCLE_OWNER_REQUIRED")
    return normalized


def _timestamp(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized:
        _parse_iso(normalized)
        return normalized
    return now_iso()


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
