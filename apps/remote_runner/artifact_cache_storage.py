from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from .artifact_io import artifact_record_exists, artifact_record_stats
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso


ARTIFACT_CACHE_KEY_SCHEMA = "h2ometa.artifact-cache-key.v1"
ARTIFACT_CACHE_LOOKUP_SCHEMA_NAME = "ArtifactCacheLookupEvent"
ARTIFACT_CACHE_LOOKUP_EVENT_TYPE = "artifact.cache.lookup.v1"


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
        "inputDigest": _digest_json(_normalize_cache_inputs(connection, inputs or [])),
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
        exists = artifact_record_exists(cfg, record)
        actual_size, actual_sha = artifact_record_stats(cfg, record)
    except ValueError:
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


def _normalize_cache_inputs(connection: sqlite3.Connection | None, value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_cache_inputs(connection, item) for item in value if item not in (None, "", [], {})]
    if not isinstance(value, dict):
        return _normalize(value)
    upload_id = str(value.get("uploadId") or "").strip()
    normalized = {
        str(key): _normalize_cache_inputs(connection, item)
        for key, item in sorted(value.items())
        if item not in (None, "", [], {}) and key not in {"uploadId", "path", "filename"}
    }
    if upload_id and connection is not None:
        upload = connection.execute(
            "SELECT sha256, size_bytes, mime_type FROM uploads WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
        if upload is not None:
            normalized["content"] = {
                "sha256": str(upload["sha256"]),
                "sizeBytes": int(upload["size_bytes"]),
                "mimeType": str(upload["mime_type"]),
            }
            return normalized
    if upload_id:
        normalized["uploadId"] = upload_id
    return normalized


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
