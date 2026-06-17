from __future__ import annotations

import json
from typing import Any

from .database_errors import DatabaseRegistryError
from .database_layers import database_layer, layer_metadata, normalize_database_layer
from .database_runtime_paths import (
    compute_database_entry_path,
    database_input_metadata,
    database_resolved_metadata,
)
from .database_templates import DATABASE_TEMPLATES


def database_row_to_dict(row) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"] or "{}")
    item = {
        "id": row["database_id"], "name": row["name"], "type": row["db_type"], "version": row["version"],
        "path": row["path"], "description": row["description"], "source": row["source"],
        "manifestPath": row["manifest_path"], "sizeBytes": row["size_bytes"], "checksum": row["checksum"],
        "metadata": metadata, "status": row["status"], "message": row["message"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"], "lastCheckedAt": row["last_checked_at"],
    }
    item["databaseLayer"] = database_layer(item)
    return _with_database_path_semantics(item)


def normalize_database_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "dbType" in payload:
        raise DatabaseRegistryError("DATABASE_FIELD_UNSUPPORTED: dbType")
    name = str(payload.get("name") or "").strip()
    data_path = str(payload.get("path") or "").strip()
    if not name:
        raise DatabaseRegistryError("DATABASE_NAME_REQUIRED")
    if not data_path:
        raise DatabaseRegistryError("DATABASE_PATH_REQUIRED")
    metadata = dict(payload.get("metadata") or {})
    database_layer_value = normalize_database_layer(payload, metadata)
    metadata = layer_metadata(metadata, database_layer_value)
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


def _default_id(*, name: str, version: str, db_type: str) -> str:
    raw = "::".join(part for part in [db_type, name, version] if part)
    return "".join(char.lower() if char.isalnum() else "-" for char in raw).strip("-") or "database"
