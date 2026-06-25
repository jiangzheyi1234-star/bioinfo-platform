from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .artifact_cache_inputs import normalize_cache_inputs
from .artifact_io import (
    artifact_record_exists,
    artifact_record_stats,
    assert_managed_artifact_storage,
)
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso


ARTIFACT_CACHE_KEY_SCHEMA = "h2ometa.artifact-cache-key.v1"
ARTIFACT_CACHE_LOOKUP_SCHEMA_NAME = "ArtifactCacheLookupEvent"
ARTIFACT_CACHE_LOOKUP_EVENT_TYPE = "artifact.cache.lookup.v1"
ARTIFACT_CACHE_PIN_PROTECTION_REASON = "artifact_cache_pin"
ARTIFACT_CACHE_RESTORE_PIN_SCOPE = "restore"
ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND = "run_attempt"
ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS = 3600


def build_artifact_cache_key_payload(
    *,
    workflow_revision_id: str,
    artifact_key: str,
    role: str = "output",
    step_id: str | None = None,
    connection: sqlite3.Connection | None = None,
    inputs: Any = None,
    params: Any = None,
    resource_bindings: Any = None,
    execution: Any = None,
) -> dict[str, Any]:
    normalized_revision_id = _required_text(workflow_revision_id, "ARTIFACT_CACHE_WORKFLOW_REVISION_REQUIRED")
    normalized_artifact_key = _required_text(artifact_key, "ARTIFACT_CACHE_ARTIFACT_KEY_REQUIRED")
    normalized_role = _required_text(role, "ARTIFACT_CACHE_ROLE_REQUIRED")
    return {
        "schemaVersion": ARTIFACT_CACHE_KEY_SCHEMA,
        "workflowRevisionId": normalized_revision_id,
        "artifactKey": normalized_artifact_key,
        "role": normalized_role,
        "stepId": _optional_text(step_id) or "",
        "inputDigest": _digest_json(normalize_cache_inputs(connection, inputs or [])),
        "paramsDigest": _digest_json(params or {}),
        "resourceBindingsDigest": _digest_json(resource_bindings or {}),
        "executionDigest": _digest_json(execution or {}),
    }


def cache_key_for_payload(payload: dict[str, Any]) -> str:
    return f"acache_{_digest_json(payload)[:32]}"


def build_artifact_cache_key_from_request(payload: dict[str, Any]) -> dict[str, Any]:
    return build_artifact_cache_key_from_request_record(None, payload)


def build_artifact_cache_key_from_request_record(
    connection: sqlite3.Connection | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    key_payload = build_artifact_cache_key_payload(
        workflow_revision_id=str(payload.get("workflowRevisionId") or ""),
        artifact_key=str(payload.get("artifactKey") or ""),
        role=str(payload.get("role") or "output"),
        step_id=str(payload.get("stepId") or ""),
        connection=connection,
        inputs=payload.get("inputs") if "inputs" in payload else [],
        params=payload.get("params") if "params" in payload else {},
        resource_bindings=payload.get("resourceBindings") if "resourceBindings" in payload else {},
        execution=payload.get("execution") if "execution" in payload else {},
    )
    return {"cacheKey": cache_key_for_payload(key_payload), "keyPayload": key_payload}


def record_artifact_cache_entry(
    cfg: RemoteRunnerConfig,
    *,
    artifact: dict[str, Any],
    artifact_key: str,
    role: str,
    step_id: str | None,
    artifact_blob_id: str,
    materialization_id: str,
    created_at: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        entry = record_artifact_cache_entry_record(
            connection,
            cfg=cfg,
            artifact=artifact,
            artifact_key=artifact_key,
            role=role,
            step_id=step_id,
            artifact_blob_id=artifact_blob_id,
            materialization_id=materialization_id,
            created_at=created_at,
        )
        connection.commit()
    return entry


def record_artifact_cache_entry_record(
    connection: sqlite3.Connection,
    *,
    cfg: RemoteRunnerConfig,
    artifact: dict[str, Any],
    artifact_key: str,
    role: str,
    step_id: str | None,
    artifact_blob_id: str,
    materialization_id: str,
    created_at: str,
) -> dict[str, Any]:
    run = connection.execute(
        "SELECT * FROM runs WHERE run_id = ?",
        (str(artifact["runId"]),),
    ).fetchone()
    if run is None:
        return {"cacheEligible": False, "cacheIneligibleReason": "run_missing"}
    workflow_revision_id = str(run["workflow_revision_id"] or "").strip()
    if not workflow_revision_id:
        return {"cacheEligible": False, "cacheIneligibleReason": "workflow_revision_missing"}
    try:
        assert_managed_artifact_storage(
            cfg,
            {"storageBackend": artifact["storageBackend"], "storageUri": artifact["storageUri"]},
        )
    except ValueError as exc:
        if str(exc).startswith("RESULT_ARTIFACT_STORAGE_UNMANAGED"):
            return {"cacheEligible": False, "cacheIneligibleReason": "artifact_unmanaged"}
        raise
    run_spec = _json_object(run["run_spec_json"])
    key_payload = build_artifact_cache_key_payload(
        workflow_revision_id=workflow_revision_id,
        artifact_key=artifact_key,
        role=role,
        step_id=step_id,
        connection=connection,
        inputs=run_spec.get("inputs") if "inputs" in run_spec else [],
        params=run_spec.get("params") if "params" in run_spec else {},
        resource_bindings=run_spec.get("resourceBindings") if "resourceBindings" in run_spec else {},
        execution=run_spec.get("execution") if "execution" in run_spec else {},
    )
    cache_key = cache_key_for_payload(key_payload)
    existing = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if existing is not None:
        if str(existing["sha256"]) != str(artifact["sha256"]):
            return {
                "cacheEligible": False,
                "cacheIneligibleReason": "cache_key_conflict",
                "cacheKey": cache_key,
            }
        return {**_cache_entry_row_to_dict(existing), "created": False}
    cache_entry_id = f"acent_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO artifact_cache_entries (
            cache_entry_id, cache_key, cache_key_schema, key_payload_json,
            workflow_revision_id, artifact_key, step_id, role, run_id,
            artifact_id, artifact_blob_id, materialization_id, storage_backend,
            storage_uri, size_bytes, sha256, lifecycle_state, created_at,
            last_used_at, hit_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, 0)
        """,
        (
            cache_entry_id,
            cache_key,
            ARTIFACT_CACHE_KEY_SCHEMA,
            _stable_json(key_payload),
            workflow_revision_id,
            artifact_key,
            _optional_text(step_id) or "",
            str(role or "output").strip() or "output",
            str(artifact["runId"]),
            str(artifact["artifactId"]),
            artifact_blob_id,
            materialization_id,
            str(artifact["storageBackend"]),
            str(artifact["storageUri"]),
            int(artifact["sizeBytes"]),
            str(artifact["sha256"]),
            created_at,
        ),
    )
    row = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_entry_id = ?",
        (cache_entry_id,),
    ).fetchone()
    return {**_cache_entry_row_to_dict(row), "created": True}


def lookup_artifact_cache_entry(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    looked_up_at = now_iso()
    with get_connection(cfg) as connection:
        key = build_artifact_cache_key_from_request_record(connection, payload)
        cache_key = key["cacheKey"]
        row = connection.execute(
            "SELECT * FROM artifact_cache_entries WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            event = _append_lookup_event(
                connection,
                cache_key=cache_key,
                key_payload=key["keyPayload"],
                hit=False,
                reason="cache_key_not_found",
                entry=None,
                occurred_at=looked_up_at,
            )
            connection.commit()
            return _lookup_result(cache_key, key["keyPayload"], False, "cache_key_not_found", None, event)

        entry = _cache_entry_row_to_dict(row)
        hit, reason = _verify_cache_entry_payload(cfg, entry)
        if hit:
            connection.execute(
                """
                UPDATE artifact_cache_entries
                SET last_used_at = ?, hit_count = hit_count + 1
                WHERE cache_entry_id = ?
                """,
                (looked_up_at, entry["cacheEntryId"]),
            )
            entry = {
                **entry,
                "lastUsedAt": looked_up_at,
                "hitCount": int(entry["hitCount"]) + 1,
            }
        event = _append_lookup_event(
            connection,
            cache_key=cache_key,
            key_payload=key["keyPayload"],
            hit=hit,
            reason=reason,
            entry=entry,
            occurred_at=looked_up_at,
        )
        connection.commit()
    return _lookup_result(cache_key, key["keyPayload"], hit, reason, entry, event)


def preview_artifact_cache_entry(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        return preview_artifact_cache_entry_record(connection, cfg=cfg, payload=payload)


def preview_artifact_cache_entry_record(
    connection: sqlite3.Connection,
    *,
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        key = build_artifact_cache_key_from_request_record(connection, payload)
    except ValueError as exc:
        return _cache_preview_result("", {}, False, str(exc), None)
    cache_key = key["cacheKey"]
    row = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None:
        return _cache_preview_result(cache_key, key["keyPayload"], False, "cache_key_not_found", None)
    entry = _cache_entry_row_to_dict(row)
    hit, reason = _verify_cache_entry_payload(cfg, entry)
    return _cache_preview_result(cache_key, key["keyPayload"], hit, reason, entry)


def list_artifact_cache_entries(
    cfg: RemoteRunnerConfig,
    *,
    workflow_revision_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    normalized_revision_id = _optional_text(workflow_revision_id)
    requested_limit = min(500, max(1, int(limit)))
    params: list[Any] = []
    where_sql = ""
    if normalized_revision_id:
        where_sql = "WHERE workflow_revision_id = ?"
        params.append(normalized_revision_id)
    with get_connection(cfg) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM artifact_cache_entries
            {where_sql}
            ORDER BY created_at DESC, cache_entry_id DESC
            LIMIT ?
            """,
            (*params, requested_limit),
        ).fetchall()
    return {"items": [_cache_entry_row_to_dict(row) for row in rows]}


def get_artifact_cache_entry(cfg: RemoteRunnerConfig, cache_entry_id: str) -> dict[str, Any]:
    normalized_id = _required_text(cache_entry_id, "ARTIFACT_CACHE_ENTRY_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM artifact_cache_entries WHERE cache_entry_id = ?",
            (normalized_id,),
        ).fetchone()
    if row is None:
        raise KeyError(normalized_id)
    return _cache_entry_row_to_dict(row)


def create_artifact_cache_pins(
    cfg: RemoteRunnerConfig,
    *,
    entries: list[dict[str, Any]],
    pin_scope: str,
    owner_kind: str,
    owner_id: str,
    reason: str,
    created_at: str | None = None,
    expires_at: str | None = None,
    ttl_seconds: int | None = ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
) -> list[dict[str, Any]]:
    occurred_at = str(created_at or now_iso())
    if expires_at is not None:
        pin_expires_at = expires_at
    elif ttl_seconds is not None:
        pin_expires_at = _expires_at(occurred_at, ttl_seconds)
    else:
        pin_expires_at = None
    with get_connection(cfg) as connection:
        pins = [
            create_artifact_cache_pin_record(
                connection,
                entry=entry,
                pin_scope=pin_scope,
                owner_kind=owner_kind,
                owner_id=owner_id,
                reason=reason,
                created_at=occurred_at,
                expires_at=pin_expires_at,
            )
            for entry in entries
        ]
        connection.commit()
    return pins


def create_artifact_cache_pin_record(
    connection: sqlite3.Connection,
    *,
    entry: dict[str, Any],
    pin_scope: str,
    owner_kind: str,
    owner_id: str,
    reason: str,
    created_at: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    cache_entry_id = _required_text(entry.get("cacheEntryId"), "ARTIFACT_CACHE_PIN_ENTRY_REQUIRED")
    normalized_scope = _required_text(pin_scope, "ARTIFACT_CACHE_PIN_SCOPE_REQUIRED")
    normalized_owner_kind = _required_text(owner_kind, "ARTIFACT_CACHE_PIN_OWNER_KIND_REQUIRED")
    normalized_owner_id = _required_text(owner_id, "ARTIFACT_CACHE_PIN_OWNER_ID_REQUIRED")
    existing = connection.execute(
        """
        SELECT cache_pin_id
        FROM artifact_cache_pins
        WHERE cache_entry_id = ? AND pin_scope = ? AND owner_kind = ? AND owner_id = ?
        """,
        (cache_entry_id, normalized_scope, normalized_owner_kind, normalized_owner_id),
    ).fetchone()
    cache_pin_id = str(existing["cache_pin_id"]) if existing is not None else f"acpin_{uuid.uuid4().hex[:12]}"
    if existing is None:
        connection.execute(
            """
            INSERT INTO artifact_cache_pins (
                cache_pin_id, cache_entry_id, cache_key, artifact_blob_id,
                storage_backend, storage_uri, sha256, pin_scope, owner_kind,
                owner_id, reason, state, created_at, released_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?)
            """,
            (
                cache_pin_id,
                cache_entry_id,
                _required_text(entry.get("cacheKey"), "ARTIFACT_CACHE_PIN_KEY_REQUIRED"),
                _required_text(entry.get("artifactBlobId"), "ARTIFACT_CACHE_PIN_BLOB_REQUIRED"),
                _required_text(entry.get("storageBackend"), "ARTIFACT_CACHE_PIN_BACKEND_REQUIRED"),
                _required_text(entry.get("storageUri"), "ARTIFACT_CACHE_PIN_URI_REQUIRED"),
                _required_text(entry.get("sha256"), "ARTIFACT_CACHE_PIN_SHA_REQUIRED"),
                normalized_scope,
                normalized_owner_kind,
                normalized_owner_id,
                str(reason or "").strip(),
                created_at,
                expires_at,
            ),
        )
    else:
        connection.execute(
            """
            UPDATE artifact_cache_pins
            SET cache_key = ?,
                artifact_blob_id = ?,
                storage_backend = ?,
                storage_uri = ?,
                sha256 = ?,
                reason = ?,
                state = 'active',
                created_at = ?,
                released_at = NULL,
                expires_at = ?
            WHERE cache_pin_id = ?
            """,
            (
                _required_text(entry.get("cacheKey"), "ARTIFACT_CACHE_PIN_KEY_REQUIRED"),
                _required_text(entry.get("artifactBlobId"), "ARTIFACT_CACHE_PIN_BLOB_REQUIRED"),
                _required_text(entry.get("storageBackend"), "ARTIFACT_CACHE_PIN_BACKEND_REQUIRED"),
                _required_text(entry.get("storageUri"), "ARTIFACT_CACHE_PIN_URI_REQUIRED"),
                _required_text(entry.get("sha256"), "ARTIFACT_CACHE_PIN_SHA_REQUIRED"),
                str(reason or "").strip(),
                created_at,
                expires_at,
                cache_pin_id,
            ),
        )
    row = connection.execute(
        "SELECT * FROM artifact_cache_pins WHERE cache_pin_id = ?",
        (cache_pin_id,),
    ).fetchone()
    return _cache_pin_row_to_dict(row)


def release_artifact_cache_pins(
    cfg: RemoteRunnerConfig,
    *,
    pin_ids: list[str],
    released_at: str | None = None,
) -> None:
    with get_connection(cfg) as connection:
        release_artifact_cache_pins_record(connection, pin_ids=pin_ids, released_at=str(released_at or now_iso()))
        connection.commit()


def release_artifact_cache_pins_record(
    connection: sqlite3.Connection,
    *,
    pin_ids: list[str],
    released_at: str,
) -> None:
    normalized_ids = sorted({_optional_text(pin_id) for pin_id in pin_ids} - {None})
    if not normalized_ids:
        return
    connection.executemany(
        """
        UPDATE artifact_cache_pins
        SET state = 'released', released_at = ?
        WHERE cache_pin_id = ? AND state = 'active'
        """,
        [(released_at, pin_id) for pin_id in normalized_ids],
    )


def list_artifact_cache_pins(
    cfg: RemoteRunnerConfig,
    *,
    cache_entry_id: str | None = None,
    state: str | None = None,
    pin_scope: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    normalized_entry_id = _optional_text(cache_entry_id)
    normalized_state = _optional_text(state)
    normalized_scope = _optional_text(pin_scope)
    if normalized_entry_id:
        clauses.append("cache_entry_id = ?")
        params.append(normalized_entry_id)
    if normalized_state:
        clauses.append("state = ?")
        params.append(normalized_state)
    if normalized_scope:
        clauses.append("pin_scope = ?")
        params.append(normalized_scope)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    requested_limit = min(500, max(1, int(limit)))
    with get_connection(cfg) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM artifact_cache_pins
            {where_sql}
            ORDER BY created_at DESC, cache_pin_id DESC
            LIMIT ?
            """,
            (*params, requested_limit),
        ).fetchall()
    return {"items": [_cache_pin_row_to_dict(row) for row in rows]}


def get_artifact_cache_pin(cfg: RemoteRunnerConfig, cache_pin_id: str) -> dict[str, Any]:
    normalized_id = _required_text(cache_pin_id, "ARTIFACT_CACHE_PIN_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM artifact_cache_pins WHERE cache_pin_id = ?",
            (normalized_id,),
        ).fetchone()
    if row is None:
        raise KeyError(normalized_id)
    return _cache_pin_row_to_dict(row)


def active_artifact_cache_pin_reasons(cfg: RemoteRunnerConfig) -> dict[str, set[str]]:
    checked_at = now_iso()
    reasons: dict[str, set[str]] = {}
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT storage_backend, storage_uri, sha256
            FROM artifact_cache_pins
            WHERE state = 'active'
              AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?)
            """,
            (checked_at,),
        ).fetchall()
    for row in rows:
        storage_key = artifact_cache_storage_ref_key(row["storage_backend"], row["storage_uri"], row["sha256"])
        reasons.setdefault(storage_key, set()).add(ARTIFACT_CACHE_PIN_PROTECTION_REASON)
    return reasons


def artifact_cache_storage_ref_key(storage_backend: str, storage_uri: str, sha256: str) -> str:
    return f"{storage_backend}\n{storage_uri}\n{sha256}"


def mark_artifact_cache_entries_deleted(
    connection: sqlite3.Connection,
    *,
    artifact_ids: list[str],
    storage_backend: str,
    storage_uri: str,
    sha256: str,
) -> None:
    if artifact_ids:
        connection.executemany(
            """
            UPDATE artifact_cache_entries
            SET lifecycle_state = 'deleted'
            WHERE artifact_id = ? AND lifecycle_state = 'active'
            """,
            [(artifact_id,) for artifact_id in artifact_ids],
        )
    connection.execute(
        """
        UPDATE artifact_cache_entries
        SET lifecycle_state = 'deleted'
        WHERE storage_backend = ?
          AND storage_uri = ?
          AND sha256 = ?
          AND lifecycle_state = 'active'
        """,
        (storage_backend, storage_uri, sha256),
    )


def _verify_cache_entry_payload(cfg: RemoteRunnerConfig, entry: dict[str, Any]) -> tuple[bool, str]:
    if str(entry.get("lifecycleState") or "") != "active":
        return False, "cache_entry_not_active"
    record = {
        "storageBackend": entry["storageBackend"],
        "storageUri": entry["storageUri"],
        "sizeBytes": entry["sizeBytes"],
        "sha256": entry["sha256"],
        "path": "",
    }
    try:
        assert_managed_artifact_storage(cfg, record)
        exists = artifact_record_exists(cfg, record)
        actual_size, actual_sha = artifact_record_stats(cfg, record)
    except ValueError as exc:
        if str(exc).startswith("RESULT_ARTIFACT_STORAGE_UNMANAGED"):
            return False, "artifact_unmanaged"
        return False, "artifact_unavailable"
    if not exists:
        return False, "artifact_unavailable"
    if int(actual_size) != int(entry["sizeBytes"]) or str(actual_sha) != str(entry["sha256"]):
        return False, "artifact_checksum_mismatch"
    return True, "hit"


def _append_lookup_event(
    connection: sqlite3.Connection,
    *,
    cache_key: str,
    key_payload: dict[str, Any],
    hit: bool,
    reason: str,
    entry: dict[str, Any] | None,
    occurred_at: str,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": ARTIFACT_CACHE_KEY_SCHEMA,
        "cacheKey": cache_key,
        "keyPayload": key_payload,
        "hit": bool(hit),
        "reason": reason,
        "cacheEntryId": str((entry or {}).get("cacheEntryId") or ""),
        "artifactId": str((entry or {}).get("artifactId") or ""),
        "artifactBlobId": str((entry or {}).get("artifactBlobId") or ""),
        "storageBackend": str((entry or {}).get("storageBackend") or ""),
        "storageUri": str((entry or {}).get("storageUri") or ""),
        "sha256": str((entry or {}).get("sha256") or ""),
    }
    return append_evidence_event(
        connection,
        event_type=ARTIFACT_CACHE_LOOKUP_EVENT_TYPE,
        schema_name=ARTIFACT_CACHE_LOOKUP_SCHEMA_NAME,
        subject_kind="artifact_cache",
        subject_id=cache_key,
        payload=payload,
        producer="artifact_cache_storage",
        occurred_at=occurred_at,
    )


def _lookup_result(
    cache_key: str,
    key_payload: dict[str, Any],
    hit: bool,
    reason: str,
    entry: dict[str, Any] | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    return {
        "cacheKey": cache_key,
        "keyPayload": key_payload,
        "hit": bool(hit),
        "reason": reason,
        "entry": entry,
        "evidenceId": event["eventId"],
        "lookedUpAt": event["occurredAt"],
    }


def _cache_preview_result(
    cache_key: str,
    key_payload: dict[str, Any],
    hit: bool,
    reason: str,
    entry: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "cacheKey": cache_key,
        "keyPayload": key_payload,
        "hit": bool(hit),
        "reason": reason,
        "entry": entry,
        "sideEffectFree": True,
    }


def _cache_entry_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "cacheEntryId": row["cache_entry_id"],
        "cacheKey": row["cache_key"],
        "cacheKeySchema": row["cache_key_schema"],
        "keyPayload": _json_object(row["key_payload_json"]),
        "workflowRevisionId": row["workflow_revision_id"],
        "artifactKey": row["artifact_key"],
        "stepId": row["step_id"],
        "role": row["role"],
        "runId": row["run_id"],
        "artifactId": row["artifact_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "materializationId": row["materialization_id"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "sizeBytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
        "lifecycleState": row["lifecycle_state"],
        "createdAt": row["created_at"],
        "lastUsedAt": row["last_used_at"],
        "hitCount": int(row["hit_count"] or 0),
    }


def _cache_pin_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "cachePinId": row["cache_pin_id"],
        "cacheEntryId": row["cache_entry_id"],
        "cacheKey": row["cache_key"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "sha256": row["sha256"],
        "pinScope": row["pin_scope"],
        "ownerKind": row["owner_kind"],
        "ownerId": row["owner_id"],
        "reason": row["reason"],
        "state": row["state"],
        "createdAt": row["created_at"],
        "releasedAt": row["released_at"],
        "expiresAt": row["expires_at"],
    }


def _expires_at(created_at: str, ttl_seconds: int) -> str:
    try:
        base = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)
    return (base + timedelta(seconds=max(0, int(ttl_seconds)))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(_normalize(value)).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items()) if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_normalize(item) for item in value if item not in (None, "", [], {})]
    return value


def _json_object(payload: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(payload or "{}"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
