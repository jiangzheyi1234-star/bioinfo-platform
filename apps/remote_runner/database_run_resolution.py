from __future__ import annotations

from pathlib import Path
from typing import Any

from . import database_validation
from .config import RemoteRunnerConfig
from .database_runtime_paths import (
    _composite_input_metadata,
    _composite_resolved_metadata,
    _validate_composite_resolved,
    compute_database_entry_path,
    database_input_metadata,
    database_resolved_metadata,
)
from .database_templates import DATABASE_TEMPLATES


def resolve_run_databases(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from .databases import check_reference_database, fetch_reference_database

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
