from __future__ import annotations

import json
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def fetch_readiness_observation(cfg: RemoteRunnerConfig, trigger_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM workflow_trigger_readiness_observations
            WHERE trigger_id = ?
            """,
            (trigger_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def upsert_readiness_observation(
    cfg: RemoteRunnerConfig,
    *,
    trigger_id: str,
    source_type: str,
    resource_type: str,
    resource_id: str,
    resource_uri: str,
    watcher_adapter: str,
    observation_hash: str,
    observed_version: str,
    observed_checksum: str,
    observed_state: str,
    dispatch_state: str = "",
    trigger_event_id: str | None = None,
    run_id: str | None = None,
    error: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    observed = observed_at or timestamp
    error_json = _stable_json(error or {})
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT created_at FROM workflow_trigger_readiness_observations WHERE trigger_id = ?",
            (trigger_id,),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing is not None else timestamp
        connection.execute(
            """
            INSERT INTO workflow_trigger_readiness_observations (
                trigger_id, source_type, resource_type, resource_id, resource_uri,
                watcher_adapter, observation_hash, observed_version, observed_checksum,
                observed_state, dispatch_state, trigger_event_id, run_id, error_json,
                observed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trigger_id) DO UPDATE SET
                source_type = excluded.source_type,
                resource_type = excluded.resource_type,
                resource_id = excluded.resource_id,
                resource_uri = excluded.resource_uri,
                watcher_adapter = excluded.watcher_adapter,
                observation_hash = excluded.observation_hash,
                observed_version = excluded.observed_version,
                observed_checksum = excluded.observed_checksum,
                observed_state = excluded.observed_state,
                dispatch_state = excluded.dispatch_state,
                trigger_event_id = excluded.trigger_event_id,
                run_id = excluded.run_id,
                error_json = excluded.error_json,
                observed_at = excluded.observed_at,
                updated_at = excluded.updated_at
            """,
            (
                trigger_id,
                source_type,
                resource_type,
                resource_id,
                resource_uri,
                watcher_adapter,
                observation_hash,
                observed_version,
                observed_checksum,
                observed_state,
                dispatch_state,
                trigger_event_id,
                run_id,
                error_json,
                observed,
                created_at,
                timestamp,
            ),
        )
        connection.commit()
    observation = fetch_readiness_observation(cfg, trigger_id)
    if observation is None:
        raise RuntimeError("WORKFLOW_TRIGGER_READINESS_OBSERVATION_NOT_RECORDED")
    return observation


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "triggerId": row["trigger_id"],
        "sourceType": row["source_type"],
        "resourceType": row["resource_type"],
        "resourceId": row["resource_id"],
        "resourceUri": row["resource_uri"],
        "watcherAdapter": row["watcher_adapter"],
        "observationHash": row["observation_hash"],
        "observedVersion": row["observed_version"],
        "observedChecksum": row["observed_checksum"],
        "observedState": row["observed_state"],
        "dispatchState": row["dispatch_state"],
        "triggerEventId": row["trigger_event_id"],
        "runId": row["run_id"],
        "error": _loads_json(row["error_json"], {}),
        "observedAt": row["observed_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, type(default)) else default
