from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import database_validation
from .database_errors import DatabaseRegistryError
from .database_pack_catalog import downloadable_database_pack_by_id
from .database_runtime_paths import (
    _composite_input_metadata,
    _composite_resolved_metadata,
    _validate_composite_resolved,
    compute_database_entry_path,
    database_input_metadata,
    database_resolved_metadata,
)
from .database_templates import DATABASE_TEMPLATES, database_template_capabilities, database_template_runtime_shape


DATABASE_PACK_READY_SCAN_SCHEMA_VERSION = "h2ometa.database-pack-ready-scan.v1"


def scan_database_pack_ready(payload: dict[str, Any]) -> dict[str, Any]:
    pack_id = str(payload.get("packId") or "").strip()
    if not pack_id:
        raise DatabaseRegistryError("DATABASE_PACK_ID_REQUIRED")
    pack = downloadable_database_pack_by_id(pack_id)
    if pack is None:
        raise DatabaseRegistryError("DATABASE_PACK_UNKNOWN")
    template_id = str(pack["templateId"]).strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    if template is None:
        raise DatabaseRegistryError("DATABASE_PACK_TEMPLATE_UNSUPPORTED")
    ready_path = str(payload.get("readyPath") or "").strip()
    if not ready_path:
        raise DatabaseRegistryError("DATABASE_PACK_READY_PATH_REQUIRED")

    path_kind = str(template.get("pathKind") or "directory")
    try:
        if path_kind == "composite":
            return _scan_composite_pack(pack, template, ready_path, payload)
        return _scan_single_path_pack(pack, template, ready_path)
    except OSError as exc:
        return _scan_result(
            pack,
            template,
            status="failed",
            message=f"Database pack ready path could not be inspected: {exc}",
            ready_path=ready_path,
            resolved_path={"kind": path_kind, "path": ready_path},
        )


def _scan_single_path_pack(pack: dict[str, Any], template: dict[str, Any], ready_path: str) -> dict[str, Any]:
    template_id = str(pack["templateId"])
    path_kind = str(template.get("pathKind") or "directory")
    data_path = Path(ready_path)
    path_error = _path_error(data_path, path_kind)
    resolved = database_validation.resolve_template_path(data_path, template)
    if path_error:
        return _scan_result(pack, template, status="missing", message=path_error, ready_path=ready_path, resolved_path=resolved)

    item = {
        "path": ready_path,
        "metadata": {
            "templateId": template_id,
            "expectedFiles": list(pack.get("expectedFiles") or []),
        },
    }
    template_error = database_validation.validate_template_files(data_path, item, template, resolved=resolved)
    if template_error:
        return _scan_result(
            pack,
            template,
            status="missing",
            message=template_error,
            ready_path=ready_path,
            resolved_path=resolved,
        )
    metadata = _ready_metadata(pack, template, ready_path, resolved)
    entry_path = compute_database_entry_path({"path": ready_path, "metadata": metadata})
    return _scan_result(
        pack,
        template,
        status="ready",
        message="Database pack ready path satisfies the template checks.",
        ready_path=ready_path,
        resolved_path=resolved,
        input_metadata=database_input_metadata(ready_path),
        resolved_metadata=database_resolved_metadata(entry_path),
        entry_path=entry_path,
    )


def _scan_composite_pack(
    pack: dict[str, Any],
    template: dict[str, Any],
    ready_path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw_fields = payload.get("fieldPaths") if isinstance(payload.get("fieldPaths"), dict) else {}
    metadata = {"input": {"fields": {str(key): str(value) for key, value in raw_fields.items()}}}
    composite_input = _composite_input_metadata(metadata, template, ready_path)
    composite_resolved = _composite_resolved_metadata(composite_input, template)
    composite_error = _validate_composite_resolved(composite_resolved, template)
    resolved_path = {"kind": "composite", "path": ready_path, "entries": composite_resolved}
    if composite_error:
        return _scan_result(
            pack,
            template,
            status="missing",
            message=composite_error,
            ready_path=ready_path,
            resolved_path=resolved_path,
            input_metadata=composite_input,
            resolved_metadata=composite_resolved,
        )
    return _scan_result(
        pack,
        template,
        status="ready",
        message="Database pack composite fields satisfy the template checks.",
        ready_path=ready_path,
        resolved_path=resolved_path,
        input_metadata=composite_input,
        resolved_metadata=composite_resolved,
    )


def _path_error(path: Path, path_kind: str) -> str:
    if path_kind == "prefix":
        if not path.parent.exists():
            return f"Database prefix parent does not exist: {path.parent}"
        return ""
    if not path.exists():
        return f"Database path does not exist: {path}"
    if path.is_dir() and not any(path.iterdir()):
        return f"Database directory is empty: {path}"
    return ""


def _ready_metadata(
    pack: dict[str, Any],
    template: dict[str, Any],
    ready_path: str,
    resolved_path: dict[str, Any],
) -> dict[str, Any]:
    return {
        "templateId": str(pack["templateId"]),
        "templateLabel": str(template.get("label") or pack["templateId"]),
        "databaseLayer": pack["installedLayer"],
        "packId": pack["packId"],
        "installedFromPackId": pack["packId"],
        "packVersion": pack["version"],
        "packSourceUrl": pack["sourceUrl"],
        "packChecksum": pack["checksum"],
        "packArchiveSizeBytes": pack["archiveSizeBytes"],
        "installationMethod": pack["installMode"],
        "inputPath": ready_path,
        "entryPath": str(resolved_path.get("prefix") or resolved_path.get("path") or ready_path),
        "pathMode": str(template.get("pathKind") or "directory"),
        "runtimeShape": database_template_runtime_shape(template),
        "capabilities": database_template_capabilities(template),
        "resolvedPath": resolved_path,
    }


def _scan_result(
    pack: dict[str, Any],
    template: dict[str, Any],
    *,
    status: str,
    message: str,
    ready_path: str,
    resolved_path: dict[str, Any],
    input_metadata: dict[str, Any] | None = None,
    resolved_metadata: dict[str, Any] | None = None,
    entry_path: str = "",
) -> dict[str, Any]:
    path_kind = str(template.get("pathKind") or "directory")
    return {
        "schemaVersion": DATABASE_PACK_READY_SCAN_SCHEMA_VERSION,
        "packId": pack["packId"],
        "templateId": pack["templateId"],
        "name": pack["name"],
        "version": pack["version"],
        "status": status,
        "message": message,
        "pathKind": path_kind,
        "readyPath": ready_path,
        "entryPath": entry_path,
        "resolvedPath": dict(resolved_path),
        "input": input_metadata or database_input_metadata(ready_path),
        "resolved": resolved_metadata or (database_resolved_metadata(entry_path) if entry_path else {}),
        "checksum": {
            "algorithm": pack["checksumAlgorithm"],
            "value": pack["checksumValue"],
            "archivePath": pack["manualInstall"]["archivePath"],
            "verificationMode": "manual_external",
            "operatorVerified": False,
        },
        "registrationPrefill": _registration_prefill(pack, ready_path, input_metadata),
        "redactionPolicy": {
            "rawReadyPathExposed": True,
            "auditReadyPathHashed": True,
            "registryMutated": False,
            "catalogMutated": False,
            "automaticExecution": False,
        },
        "checkedPathHash": _stable_hash(ready_path),
    }


def _registration_prefill(
    pack: dict[str, Any],
    ready_path: str,
    input_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    prefill = {
        "id": pack["registrationHandoff"]["defaultDatabaseId"],
        "name": pack["name"],
        "templateId": pack["templateId"],
        "type": pack["type"],
        "version": pack["version"],
        "path": ready_path,
        "databaseLayer": pack["installedLayer"],
        "source": pack["sourceUrl"],
        "sizeBytes": pack["archiveSizeBytes"],
        "checksum": pack["checksum"],
        "metadata": {
            "templateId": pack["templateId"],
            "databaseLayer": pack["installedLayer"],
            "packId": pack["packId"],
            "installedFromPackId": pack["packId"],
            "packVersion": pack["version"],
            "packSourceUrl": pack["sourceUrl"],
            "packChecksum": pack["checksum"],
            "packArchiveSizeBytes": pack["archiveSizeBytes"],
            "installationMethod": "manual_external",
            **({"input": input_metadata} if input_metadata else {}),
        },
    }
    return prefill


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
