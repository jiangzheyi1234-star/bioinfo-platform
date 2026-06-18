from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from . import database_validation
from .database_candidates import resolve_candidate_payload
from .database_errors import DatabaseCandidateConflictError, DatabaseNotFoundError, DatabaseRegistryError
from .config import RemoteRunnerConfig
from .database_records import database_row_to_dict, normalize_database_payload
from .database_run_resolution import resolve_run_databases
from .sqlite_migrations import ensure_runtime_schema_current
from .database_runtime_paths import (
    _composite_input_metadata,
    _composite_resolved_metadata,
    _validate_composite_resolved,
    compute_database_entry_path,
    database_input_metadata,
    database_resolved_metadata,
)
from .database_templates import DATABASE_TEMPLATES, database_template_capabilities, database_template_runtime_shape
from .storage import get_connection, now_iso

__all__ = [
    "DatabaseCandidateConflictError",
    "DatabaseNotFoundError",
    "DatabaseRegistryError",
    "resolve_run_databases",
]

_DATABASE_REGISTRY_LOCK = threading.Lock()
def list_reference_databases(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT * FROM reference_databases ORDER BY updated_at DESC, name ASC"
        ).fetchall()
    return [database_row_to_dict(row) for row in rows]

def fetch_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM reference_databases WHERE database_id = ?",
            (database_id,),
        ).fetchone()
    return database_row_to_dict(row) if row is not None else None

def add_reference_database(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = normalize_database_payload(payload)
    now = now_iso()
    existing = fetch_reference_database(cfg, item["id"])
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO reference_databases (
                database_id, name, db_type, version, path, description, source,
                manifest_path, size_bytes, checksum, metadata_json, status, message,
                created_at, updated_at, last_checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(database_id) DO UPDATE SET
                name = excluded.name,
                db_type = excluded.db_type,
                version = excluded.version,
                path = excluded.path,
                description = excluded.description,
                source = excluded.source,
                manifest_path = excluded.manifest_path,
                size_bytes = excluded.size_bytes,
                checksum = excluded.checksum,
                metadata_json = excluded.metadata_json,
                status = excluded.status,
                message = excluded.message,
                updated_at = excluded.updated_at
            """,
            (
                item["id"],
                item["name"],
                item["type"],
                item["version"],
                item["path"],
                item["description"],
                item["source"],
                item["manifestPath"],
                item.get("sizeBytes"),
                item["checksum"],
                json.dumps(item["metadata"], ensure_ascii=False),
                item["status"],
                item["message"],
                (existing or {}).get("createdAt") or now,
                now,
                (existing or {}).get("lastCheckedAt"),
            ),
        )
        connection.commit()
    saved = fetch_reference_database(cfg, item["id"])
    if saved is None:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")
    return saved


def add_verified_reference_database(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_candidate_payload(payload)
    normalized = normalize_database_payload(payload)
    if not str((normalized.get("metadata") or {}).get("templateId") or "").strip():
        raise DatabaseRegistryError("DATABASE_TEMPLATE_REQUIRED")
    with _DATABASE_REGISTRY_LOCK:
        existing = fetch_reference_database(cfg, normalized["id"])
        saved = add_reference_database(cfg, payload)
        try:
            checked = check_reference_database(cfg, saved["id"])
        except DatabaseRegistryError:
            if existing is not None:
                add_reference_database(cfg, existing)
            else:
                remove_reference_database(cfg, saved["id"])
            raise
        if checked["status"] != "available":
            if existing is not None:
                add_reference_database(cfg, existing)
            else:
                remove_reference_database(cfg, saved["id"])
            detail = str(checked.get("message") or checked.get("status") or "Database validation failed.")
            raise DatabaseRegistryError(detail)
        return checked


def update_reference_database(cfg: RemoteRunnerConfig, database_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    unsupported = set(payload) - {"name", "version", "description"}
    if unsupported:
        raise DatabaseRegistryError(f"DATABASE_FIELD_UNSUPPORTED: {sorted(unsupported)[0]}")
    existing = fetch_reference_database(cfg, normalized)
    if existing is None:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")
    next_name = str(payload.get("name") if payload.get("name") is not None else existing["name"]).strip()
    if not next_name:
        raise DatabaseRegistryError("DATABASE_NAME_REQUIRED")
    next_version = str(payload.get("version") if payload.get("version") is not None else existing["version"]).strip()
    next_description = str(payload.get("description") if payload.get("description") is not None else existing["description"])
    now = now_iso()
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            UPDATE reference_databases
            SET name = ?, version = ?, description = ?, updated_at = ?
            WHERE database_id = ?
            """,
            (next_name, next_version, next_description, now, normalized),
        )
        connection.commit()
    updated = fetch_reference_database(cfg, normalized)
    if updated is None:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")
    return updated


def remove_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> None:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        cursor = connection.execute("DELETE FROM reference_databases WHERE database_id = ?", (normalized,))
        connection.commit()
    if cursor.rowcount == 0:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")


def check_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any]:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    item = fetch_reference_database(cfg, normalized)
    if item is None:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")

    data_path = Path(str(item.get("path") or ""))
    manifest_path = Path(str(item.get("manifestPath") or "")) if item.get("manifestPath") else None
    metadata = dict(item.get("metadata") or {})
    template_id = str(metadata.get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    path_kind = str((template or {}).get("pathKind") or "directory")
    if path_kind == "composite":
        composite_input = _composite_input_metadata(metadata, template or {}, str(item.get("path") or ""))
        composite_resolved = _composite_resolved_metadata(composite_input, template or {})
        composite_error = _validate_composite_resolved(composite_resolved, template or {})
        if composite_error:
            return _update_status(cfg, normalized, "missing", composite_error)
        metadata["input"] = composite_input
        metadata["resolved"] = composite_resolved
        metadata["inputPath"] = str(item.get("path") or "")
        metadata["entryPath"] = ""
        metadata["pathMode"] = path_kind
        metadata["runtimeShape"] = database_template_runtime_shape(template or {})
        metadata["capabilities"] = database_template_capabilities(template or {})
        metadata["resolvedPath"] = {"kind": path_kind, "path": str(item.get("path") or ""), "entries": composite_resolved}
        return _update_status(
            cfg,
            normalized,
            "available",
            "Composite database fields are available on the remote runner.",
            metadata=metadata,
        )
    if path_kind == "prefix":
        if not data_path.parent.exists():
            return _update_status(cfg, normalized, "missing", f"Database prefix parent does not exist: {data_path.parent}")
    elif not data_path.exists():
        return _update_status(cfg, normalized, "missing", f"Database path does not exist: {data_path}")
    if manifest_path is not None and not manifest_path.exists():
        return _update_status(cfg, normalized, "missing", f"Manifest path does not exist: {manifest_path}")
    if data_path.is_dir() and not any(data_path.iterdir()):
        return _update_status(cfg, normalized, "missing", f"Database directory is empty: {data_path}")
    resolved = database_validation.resolve_template_path(data_path, template or {})
    selected_candidate = metadata.get("resolvedCandidate") if isinstance(metadata.get("resolvedCandidate"), dict) else None
    if selected_candidate:
        candidate_entry = str(selected_candidate.get("entryPath") or "").strip()
        if candidate_entry:
            resolved = {"kind": path_kind, "path": str(data_path)}
            if path_kind == "prefix":
                resolved["prefix"] = candidate_entry
            else:
                resolved["path"] = candidate_entry
                resolved["firstMatch"] = candidate_entry
    template_error = database_validation.validate_template_files(data_path, item, template, resolved=resolved)
    if template_error:
        return _update_status(cfg, normalized, "missing", template_error)
    if template is not None:
        if template_id == "bracken":
            metadata["availableReadLengths"] = database_validation.bracken_read_lengths(data_path)
            resolved.pop("firstMatch", None)
        metadata["resolvedPath"] = resolved
    metadata["inputPath"] = str(metadata.get("inputPath") or data_path)
    metadata["entryPath"] = compute_database_entry_path(
        {
            **item,
            "path": str(data_path),
            "metadata": metadata,
        }
    )
    metadata["pathMode"] = path_kind
    metadata["runtimeShape"] = database_template_runtime_shape(template or {})
    metadata["capabilities"] = database_template_capabilities(template or {})
    metadata["resolvedPath"] = dict(metadata.get("resolvedPath") or {})
    metadata["input"] = database_input_metadata(metadata["inputPath"])
    metadata["resolved"] = database_resolved_metadata(metadata["entryPath"])
    return _update_status(
        cfg,
        normalized,
        "available",
        "Database path is available on the remote runner.",
        metadata=metadata,
    )


def _ensure_schema(connection) -> None:
    ensure_runtime_schema_current(connection)


def _update_status(
    cfg: RemoteRunnerConfig,
    database_id: str,
    status: str,
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checked_at = now_iso()
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        values = (status, message, checked_at, checked_at, database_id)
        if metadata is None:
            cursor = connection.execute(
                "UPDATE reference_databases SET status = ?, message = ?, updated_at = ?, last_checked_at = ? WHERE database_id = ?",
                values,
            )
        else:
            cursor = connection.execute(
                "UPDATE reference_databases SET status = ?, message = ?, metadata_json = ?, updated_at = ?, last_checked_at = ? WHERE database_id = ?",
                (status, message, json.dumps(metadata, ensure_ascii=False), checked_at, checked_at, database_id),
            )
        connection.commit()
    if cursor.rowcount == 0:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")
    item = fetch_reference_database(cfg, database_id)
    if item is None:
        raise DatabaseNotFoundError("DATABASE_NOT_FOUND")
    return item
