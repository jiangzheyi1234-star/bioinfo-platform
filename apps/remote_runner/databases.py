from __future__ import annotations

import json
import shlex
import threading
from pathlib import Path
from typing import Any

from . import database_validation
from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from .config import RemoteRunnerConfig
from .database_templates import DATABASE_TEMPLATES, database_template_capabilities, database_template_runtime_shape, list_database_templates
from .storage import get_connection, now_iso


class DatabaseRegistryError(ValueError):
    pass

_DATABASE_REGISTRY_LOCK = threading.Lock()

def list_reference_databases(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT * FROM reference_databases ORDER BY updated_at DESC, name ASC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]

def fetch_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM reference_databases WHERE database_id = ?",
            (database_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None

def add_reference_database(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_payload(payload)
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
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    return saved


def add_verified_reference_database(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _resolve_candidate_payload(payload)
    normalized = _normalize_payload(payload)
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
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
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
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
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
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")


def check_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any]:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    item = fetch_reference_database(cfg, normalized)
    if item is None:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")

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
        if template is not None:
            command = _render_composite_tool_probe_command(template, composite_resolved)
            if command:
                try:
                    command = database_validation.prepare_tool_probe_command(cfg, template_id, template, command)
                except RuntimeError as exc:
                    metadata.setdefault("validation", {})["toolProbe"] = {
                        "ok": False,
                        "command": command,
                        "returncode": 127,
                        "stdout": "",
                        "stderr": str(exc),
                    }
                    return _update_status(
                        cfg,
                        normalized,
                        "failed",
                        f"Tool probe failed for database template {template_id}: {exc}",
                        metadata=metadata,
                    )
                probe = dict(template.get("toolProbe") or {})
                result = database_validation.run_tool_probe(command, timeout=int(probe.get("timeoutSeconds") or 60))
                metadata.setdefault("validation", {})["toolProbe"] = database_validation.probe_metadata(result)
                if not result.ok:
                    detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                    return _update_status(
                        cfg,
                        normalized,
                        "failed",
                        f"Tool probe failed for database template {template_id}: {detail}",
                        metadata=metadata,
                    )
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
        probe = dict(template.get("toolProbe") or {})
        command = database_validation.render_tool_probe_command(template, data_path, resolved)
        if command:
            try:
                command = database_validation.prepare_tool_probe_command(cfg, template_id, template, command)
            except RuntimeError as exc:
                metadata.setdefault("validation", {})["toolProbe"] = {
                    "ok": False,
                    "command": command,
                    "returncode": 127,
                    "stdout": "",
                    "stderr": str(exc),
                }
                return _update_status(
                    cfg,
                    normalized,
                    "failed",
                    f"Tool probe failed for database template {template_id}: {exc}",
                    metadata=metadata,
                )
            result = database_validation.run_tool_probe(command, timeout=int(probe.get("timeoutSeconds") or 60))
            metadata.setdefault("validation", {})["toolProbe"] = database_validation.probe_metadata(result)
            if not result.ok:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                return _update_status(
                    cfg,
                    normalized,
                    "failed",
                    f"Tool probe failed for database template {template_id}: {detail}",
                    metadata=metadata,
                )
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
        "Database path and tool probe are available on the remote runner.",
        metadata=metadata,
    )


def resolve_run_databases(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requested = run_spec.get("databases")
    if requested is None:
        if "database" in run_spec:
            raise ValueError("DATABASES_FIELD_REQUIRED")
        return {}
    entries = requested if isinstance(requested, list) else [requested]
    resolved: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("DATABASE_REFERENCE_INVALID")
        database_id = str(entry.get("id") or entry.get("databaseId") or "").strip()
        if not database_id:
            raise ValueError("DATABASE_ID_REQUIRED")
        database = fetch_reference_database(cfg, database_id)
        if database is None:
            raise ValueError("DATABASE_NOT_FOUND")
        if not str((database.get("metadata") or {}).get("templateId") or "").strip():
            raise ValueError("DATABASE_TEMPLATE_REQUIRED")
        database = check_reference_database(cfg, database_id)
        role = str(entry.get("role") or entry.get("name") or database.get("type") or f"database_{index + 1}").strip()
        if not role:
            raise ValueError("DATABASE_ROLE_REQUIRED")
        status = str(database.get("status") or "")
        if status != "available":
            raise ValueError("DATABASE_UNAVAILABLE")
        data_path = Path(str(database.get("path") or ""))
        template_id = str((database.get("metadata") or {}).get("templateId") or "").strip().lower()
        template = DATABASE_TEMPLATES.get(template_id)
        metadata = dict(database.get("metadata") or {})
        resolved_path = dict(metadata.get("resolvedPath") or {})
        if str((template or {}).get("pathKind") or "") == "composite":
            composite_error = _validate_composite_resolved(
                _composite_resolved_metadata(_composite_input_metadata(metadata, template or {}, str(database.get("path") or "")), template or {}),
                template or {},
            )
            if composite_error:
                raise ValueError("DATABASE_PATH_MISSING")
        elif str((template or {}).get("pathKind") or "") == "prefix":
            prefix_path = Path(str(resolved_path.get("prefix") or data_path))
            if database_validation.prefix_structure_error(prefix_path, template or {}):
                raise ValueError("DATABASE_PATH_MISSING")
        elif str((template or {}).get("pathKind") or "") == "primary_with_sidecars":
            entry_path = Path(str(resolved_path.get("path") or data_path))
            if database_validation.primary_with_sidecars_structure_error(entry_path, template or {}):
                raise ValueError("DATABASE_PATH_MISSING")
        elif not data_path.exists():
            raise ValueError("DATABASE_PATH_MISSING")
        input_path = str(database.get("inputPath") or database["path"])
        entry_path = compute_database_entry_path(database)
        path_mode = str(database.get("pathMode") or (template or {}).get("pathKind") or metadata.get("pathMode") or "directory")
        metadata["inputPath"] = input_path
        metadata["entryPath"] = entry_path
        metadata["pathMode"] = path_mode
        metadata["resolvedPath"] = resolved_path
        if path_mode == "composite":
            metadata["input"] = _composite_input_metadata(metadata, template or {}, str(database.get("path") or ""))
            metadata["resolved"] = _composite_resolved_metadata(metadata["input"], template or {})
        else:
            metadata["input"] = database_input_metadata(input_path)
            metadata["resolved"] = database_resolved_metadata(entry_path)
        resolved[role] = {
            "id": database["id"],
            "name": database["name"],
            "type": database["type"],
            "templateId": str((database.get("metadata") or {}).get("templateId") or ""),
            "version": database["version"],
            "path": entry_path,
            "inputPath": input_path,
            "entryPath": entry_path,
            "pathMode": path_mode,
            "resolvedPath": resolved_path,
            "input": metadata["input"],
            "resolved": metadata["resolved"],
            "manifestPath": database["manifestPath"],
            "checksum": database["checksum"],
            "metadata": metadata,
        }
    return resolved


def compute_database_entry_path(database: dict[str, Any]) -> str:
    metadata = dict(database.get("metadata") or {})
    if str(metadata.get("pathMode") or "") == "composite":
        return str(metadata.get("entryPath") or "")
    resolved = metadata.get("resolved")
    if isinstance(resolved, dict) and len(resolved) == 1:
        return str(next(iter(resolved.values())))
    resolved_path = dict(metadata.get("resolvedPath") or {})
    return str(resolved_path.get("prefix") or resolved_path.get("path") or metadata.get("entryPath") or database.get("path") or "")


def database_input_metadata(path: str) -> dict[str, str]:
    return {"kind": "single", "path": str(path or "")}


def database_resolved_metadata(path: str) -> dict[str, str]:
    return {"default": str(path or "")}


def database_resolved_values(database: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(database.get("metadata") or {})
    resolved = metadata.get("resolved")
    if isinstance(resolved, dict) and resolved:
        return dict(resolved)
    top_level_resolved = database.get("resolved")
    if isinstance(top_level_resolved, dict) and top_level_resolved:
        return dict(top_level_resolved)
    return {}


def database_resolved_config_value(database: dict[str, Any]) -> Any:
    resolved = database_resolved_values(database)
    path_mode = str(database.get("pathMode") or (database.get("metadata") or {}).get("pathMode") or "")
    if path_mode == "composite":
        return resolved
    if len(resolved) == 1:
        return next(iter(resolved.values()))
    if resolved:
        return resolved
    return compute_database_entry_path(database)


def _composite_input_metadata(metadata: dict[str, Any], template: dict[str, Any], fallback_path: str = "") -> dict[str, Any]:
    raw_input = metadata.get("input") if isinstance(metadata.get("input"), dict) else {}
    fields = raw_input.get("fields") if isinstance(raw_input.get("fields"), dict) else {}
    normalized = {str(key): str(value) for key, value in fields.items()}
    field_specs = template.get("fields") if isinstance(template.get("fields"), dict) else {}
    if not normalized and fallback_path and len(field_specs) == 1:
        only_key = next(iter(field_specs))
        normalized[str(only_key)] = str(fallback_path)
    elif not normalized and fallback_path:
        root = Path(fallback_path)
        for field_key, field_spec in field_specs.items():
            spec = field_spec if isinstance(field_spec, dict) else {}
            hint_name = Path(str(spec.get("pathHint") or "")).name
            child_name = hint_name if hint_name else str(field_key)
            normalized[str(field_key)] = str(root / child_name)
    return {"kind": "multi", "fields": normalized}


def _composite_resolved_metadata(raw_input: dict[str, Any], template: dict[str, Any]) -> dict[str, str]:
    input_fields = raw_input.get("fields") if isinstance(raw_input.get("fields"), dict) else {}
    resolved: dict[str, str] = {}
    field_specs = template.get("fields") if isinstance(template.get("fields"), dict) else {}
    for field_key, field_spec in field_specs.items():
        value = str(input_fields.get(str(field_key)) or "").strip()
        if not value:
            continue
        resolved_value = _resolve_composite_field_value(Path(value), field_spec if isinstance(field_spec, dict) else {})
        if resolved_value:
            resolved[str(field_key)] = resolved_value
    return resolved


def _validate_composite_resolved(resolved: dict[str, str], template: dict[str, Any]) -> str:
    field_specs = template.get("fields") if isinstance(template.get("fields"), dict) else {}
    if not field_specs:
        return "Composite database template must define fields."
    for field_key, field_spec in field_specs.items():
        key = str(field_key)
        spec = field_spec if isinstance(field_spec, dict) else {}
        value = str(resolved.get(key) or "").strip()
        if not value:
            if bool(spec.get("required", True)):
                return f"Composite database field is required: {key}"
            continue
        path = Path(value)
        field_kind = str(spec.get("pathKind") or "directory")
        if field_kind == "directory" and not path.is_dir():
            return f"Composite database field {key} requires a directory: {path}"
        if field_kind == "file" and not path.is_file():
            return f"Composite database field {key} requires a file: {path}"
        validation = spec.get("validation") if isinstance(spec.get("validation"), dict) else {}
        required_name = str(validation.get("requiredFileName") or "").strip()
        if required_name and path.name != required_name:
            return f"Composite database field {key} requires file named {required_name}: {path}"
        min_size = validation.get("minSizeBytes")
        if min_size is not None and path.is_file() and path.stat().st_size < int(min_size):
            return f"Composite database field {key} is smaller than required: {path}"
        required_globs = [str(pattern) for pattern in validation.get("requiredGlobs") or [] if str(pattern).strip()]
        for pattern in required_globs:
            if field_kind == "directory" and not any(path.glob(pattern)):
                return f"Composite database field {key} requires a file matching {pattern} in {path}"
            if field_kind == "file" and not path.match(pattern):
                return f"Composite database field {key} requires a file matching {pattern}: {path}"
    return ""


def _resolve_composite_field_value(path: Path, spec: dict[str, Any]) -> str:
    field_kind = str(spec.get("pathKind") or "directory")
    resolve = spec.get("resolve") if isinstance(spec.get("resolve"), dict) else {}
    if field_kind == "file" and path.is_dir() and str(resolve.get("strategy") or "") == "find_named_file":
        filename = str(resolve.get("fileName") or "").strip()
        if filename:
            return str(path / filename)
    return str(path)


def _render_composite_tool_probe_command(template: dict[str, Any], resolved: dict[str, str]) -> str:
    probe = dict(template.get("toolProbe") or {})
    command = str(probe.get("commandTemplate") or "").strip()
    if not command:
        return ""
    for key, value in resolved.items():
        command = command.replace(f"{{{key}}}", value)
        command = command.replace(f"{{{key}:q}}", shlex.quote(value))
    return command


def _ensure_schema(connection) -> None:
    connection.executescript(REFERENCE_DATABASE_SCHEMA_SQL)


def _row_to_dict(row) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"] or "{}")
    item = {
        "id": row["database_id"], "name": row["name"], "type": row["db_type"], "version": row["version"],
        "path": row["path"], "description": row["description"], "source": row["source"],
        "manifestPath": row["manifest_path"], "sizeBytes": row["size_bytes"], "checksum": row["checksum"],
        "metadata": metadata, "status": row["status"], "message": row["message"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"], "lastCheckedAt": row["last_checked_at"],
    }
    return _with_database_path_semantics(item)


def _with_database_path_semantics(item: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    template_id = str(metadata.get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    path_mode = str(metadata.get("pathMode") or (template or {}).get("pathKind") or "directory")
    resolved_path = dict(metadata.get("resolvedPath") or {})
    input_path = str(metadata.get("inputPath") or item.get("path") or "")
    if path_mode == "composite":
        entry_path = str(metadata.get("entryPath") or "")
    else:
        entry_path = str(metadata.get("entryPath") or compute_database_entry_path({**item, "metadata": metadata}))
    input_metadata = metadata.get("input") if isinstance(metadata.get("input"), dict) else database_input_metadata(input_path)
    resolved_metadata = metadata.get("resolved") if isinstance(metadata.get("resolved"), dict) else database_resolved_metadata(entry_path)
    return {
        **item,
        "inputPath": input_path,
        "entryPath": entry_path,
        "pathMode": path_mode,
        "resolvedPath": resolved_path,
        "input": input_metadata,
        "resolved": resolved_metadata,
    }


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "dbType" in payload:
        raise DatabaseRegistryError("DATABASE_FIELD_UNSUPPORTED: dbType")
    name = str(payload.get("name") or "").strip()
    data_path = str(payload.get("path") or "").strip()
    if not name:
        raise DatabaseRegistryError("DATABASE_NAME_REQUIRED")
    if not data_path:
        raise DatabaseRegistryError("DATABASE_PATH_REQUIRED")
    metadata = dict(payload.get("metadata") or {})
    template_id = str(payload.get("templateId") or metadata.get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id) if template_id else None
    if template_id and template is None:
        raise DatabaseRegistryError("DATABASE_TEMPLATE_UNSUPPORTED")
    if template_id:
        metadata["templateId"] = template_id
        metadata["templateLabel"] = str(template.get("label") or template_id)
    db_type = str(payload.get("type") or (template or {}).get("type") or "reference").strip()
    version = str(payload.get("version") or "").strip()
    database_id = str(payload.get("id") or "").strip() or _default_id(name=name, version=version, db_type=db_type)
    return {
        "id": database_id, "name": name, "type": db_type, "version": version, "path": data_path,
        "description": str(payload.get("description") or ""), "source": str(payload.get("source") or "manual"),
        "manifestPath": str(payload.get("manifestPath") or ""), "sizeBytes": payload.get("sizeBytes"),
        "checksum": str(payload.get("checksum") or ""), "metadata": metadata,
        "status": str(payload.get("status") or "declared"), "message": str(payload.get("message") or "Database declared."),
    }


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
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    item = fetch_reference_database(cfg, database_id)
    if item is None:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    return item


def _default_id(*, name: str, version: str, db_type: str) -> str:
    raw = "::".join(part for part in [db_type, name, version] if part)
    return "".join(char.lower() if char.isalnum() else "-" for char in raw).strip("-") or "database"


def _resolve_candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = str(payload.get("templateId") or (payload.get("metadata") or {}).get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    if template is None:
        return payload
    selected_entry = str(payload.get("selectedEntryPath") or (payload.get("metadata") or {}).get("selectedEntryPath") or "").strip()
    input_path = str(payload.get("path") or "").strip()
    if not input_path:
        return payload
    data_path = Path(input_path)
    path_kind = str(template.get("pathKind") or "directory")
    candidates = _candidate_entries(data_path, template_id, template)
    if selected_entry:
        candidate = next((item for item in candidates if item["entryPath"] == selected_entry), None)
        if candidate is None:
            raise DatabaseRegistryError("DATABASE_CANDIDATE_NOT_FOUND")
        return _payload_with_candidate(payload, candidate)
    if len(candidates) == 1:
        return _payload_with_candidate(payload, candidates[0])
    if len(candidates) > 1:
        detail = {
            "status": "multiple_candidates",
            "message": f"检测到多个 {template.get('label') or template_id} 数据库入口，请选择一个。",
            "templateId": template_id,
            "pathKind": path_kind,
            "inputPath": input_path,
            "candidates": candidates,
        }
        raise DatabaseRegistryError(f"DATABASE_CANDIDATES:{json.dumps(detail, ensure_ascii=False)}")
    return payload


def _payload_with_candidate(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    metadata["inputPath"] = candidate["inputPath"]
    metadata["entryPath"] = candidate["entryPath"]
    metadata["resolvedCandidate"] = candidate
    return {
        **payload,
        "metadata": metadata,
    }


def _candidate_entries(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    path_kind = str(template.get("pathKind") or "directory")
    if path_kind == "directory":
        return [_candidate(data_path, input_path=data_path, path_kind=path_kind, template_id=template_id, evidence=list(template.get("requiredFiles") or []))]
    if path_kind == "prefix":
        return _prefix_candidates(data_path, template_id, template)
    if path_kind == "file":
        return _file_candidates(data_path, template_id, template)
    if path_kind == "primary_with_sidecars":
        return _primary_with_sidecar_candidates(data_path, template_id, template)
    return []


def _candidate(entry_path: Path, *, input_path: Path, path_kind: str, template_id: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "label": entry_path.name or str(entry_path),
        "entryPath": str(entry_path),
        "inputPath": str(input_path),
        "pathKind": path_kind,
        "templateId": template_id,
        "evidence": evidence,
    }


def _prefix_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    if data_path.is_dir():
        prefixes = database_validation.prefix_alias_prefixes_in_directory(data_path, template)
        if not prefixes:
            prefixes = database_validation.complete_prefixes_in_directory(data_path, template)
        candidates = []
        for prefix in prefixes:
            evidence = _prefix_evidence(prefix, template)
            candidates.append(_candidate(prefix, input_path=data_path, path_kind="prefix", template_id=template_id, evidence=evidence))
        return candidates
    prefix = database_validation.resolve_prefix_path(data_path, template)
    if database_validation.prefix_structure_error(prefix, template):
        return []
    return [_candidate(prefix, input_path=data_path, path_kind="prefix", template_id=template_id, evidence=_prefix_evidence(prefix, template))]


def _prefix_evidence(prefix: Path, template: dict[str, Any]) -> list[str]:
    for pattern in template.get("prefixAliasPatterns") or []:
        pattern_text = str(pattern)
        if not pattern_text.startswith("*"):
            continue
        alias_path = Path(str(prefix) + pattern_text[1:])
        if alias_path.exists():
            return [alias_path.name]
    for pattern_set in template.get("prefixPatternSets") or []:
        paths = [Path(str(prefix) + str(suffix)) for suffix in pattern_set]
        if all(path.exists() for path in paths):
            return [path.name for path in paths]
    return []


def _file_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    paths = database_validation.template_file_matches(data_path, template) if data_path.is_dir() else [data_path]
    candidates = []
    for path in paths:
        if path.is_file() and not database_validation.validate_template_file_path(path, template_id, template):
            candidates.append(_candidate(path, input_path=data_path, path_kind="file", template_id=template_id, evidence=[path.name]))
    return candidates


def _primary_with_sidecar_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    paths = database_validation.template_file_matches(data_path, template) if data_path.is_dir() else [data_path]
    candidates = []
    for path in paths:
        if path.is_file() and not database_validation.primary_with_sidecars_structure_error(path, template):
            evidence = [path.name, *[path.name + str(suffix) for suffix in template.get("indexSuffixes", [])]]
            candidates.append(_candidate(path, input_path=data_path, path_kind="primary_with_sidecars", template_id=template_id, evidence=evidence))
    return candidates
