from __future__ import annotations

from pathlib import Path
from typing import Any


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
