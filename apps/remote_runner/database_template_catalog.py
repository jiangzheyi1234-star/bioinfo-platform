from __future__ import annotations

from typing import Any


_PATH_KIND_DEFAULTS: dict[str, dict[str, str]] = {
    "directory": {"pathLabel": "数据库目录", "runtimeValue": "selected_path"},
    "file": {"pathLabel": "数据库文件", "runtimeValue": "resolved_file"},
    "prefix": {"pathLabel": "索引目录或索引文件", "runtimeValue": "resolved_prefix"},
    "primary_with_sidecars": {"pathLabel": "FASTA 主文件", "runtimeValue": "primary_file"},
    "composite": {"pathLabel": "复合数据库路径", "runtimeValue": "resolved_entries"},
}

_TYPE_CATEGORY_DEFAULTS = {
    "taxonomy": "taxonomy",
    "amr": "annotation",
    "sequence_index": "alignment",
    "functional_profile": "annotation",
    "profile_hmm": "annotation",
    "annotation": "annotation",
}

_TYPE_CAPABILITY_DEFAULTS = {
    "taxonomy": ["taxonomy_database"],
    "amr": ["amr_database"],
    "sequence_index": ["sequence_search_database"],
    "functional_profile": ["functional_profile_database"],
    "profile_hmm": ["profile_hmm_database"],
    "annotation": ["annotation_database"],
    "reference": ["reference_database"],
}

_RUNTIME_SHAPE_DEFAULTS = {
    "directory": {"kind": "scalarPath", "valueKey": "default", "jsonType": "string"},
    "file": {"kind": "scalarPath", "valueKey": "default", "jsonType": "string"},
    "prefix": {"kind": "prefix", "valueKey": "default", "jsonType": "string"},
    "primary_with_sidecars": {"kind": "primaryFile", "valueKey": "default", "jsonType": "string"},
    "composite": {"kind": "namedEntries", "valueKey": "resolved", "jsonType": "object"},
}


def build_database_template_catalog(templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": template_id,
            "name": str(template.get("label") or template_id),
            "supportLevel": str(template.get("supportLevel") or "stable"),
            "type": str(template.get("type") or "reference"),
            "category": _template_category(template),
            "icon": str(template.get("icon") or "custom"),
            "pathKind": str(template.get("pathKind") or "directory"),
            "pathLabel": _template_path_label(template),
            "runtimeValue": _template_runtime_value(template),
            "runtimeShape": _template_runtime_shape(template),
            "capabilities": _template_capabilities(template),
            "selectorKind": str(template.get("pathKind") or "directory"),
            "selector": {
                "kind": str(template.get("pathKind") or "directory"),
                "hint": str(template.get("pathHint") or ""),
            },
            "description": str(template.get("description") or ""),
            "pathHint": str(template.get("pathHint") or ""),
            "expectedFiles": _template_expected_files(template),
            "anyPatterns": list(template.get("anyPatterns") or []),
            "primaryExtensions": list(template.get("primaryExtensions") or []),
            "sidecars": list(template.get("sidecars") or []),
            "indexSuffixes": list(template.get("indexSuffixes") or []),
            "companionSuffixes": list(template.get("companionSuffixes") or []),
            "prefixPatternSets": list(template.get("prefixPatternSets") or []),
            "prefixAliasPatterns": list(template.get("prefixAliasPatterns") or []),
            "fields": dict(template.get("fields") or {}),
            "select": _template_select(template),
            "resolve": _template_resolve(template),
            "validation": _template_validation(template),
            "output": _template_output(template),
            "runtime": _template_runtime(template),
        }
        for template_id, template in templates.items()
    ]


def database_template_runtime_shape(template: dict[str, Any]) -> dict[str, Any]:
    return _template_runtime_shape(template)


def database_template_capabilities(template: dict[str, Any]) -> list[str]:
    return _template_capabilities(template)


def _template_category(template: dict[str, Any]) -> str:
    if template.get("category"):
        return str(template["category"])
    return _TYPE_CATEGORY_DEFAULTS.get(str(template.get("type") or ""), "custom")


def _template_path_label(template: dict[str, Any]) -> str:
    if template.get("pathLabel"):
        return str(template["pathLabel"])
    path_kind = str(template.get("pathKind") or "directory")
    return _PATH_KIND_DEFAULTS.get(path_kind, _PATH_KIND_DEFAULTS["directory"])["pathLabel"]


def _template_runtime_value(template: dict[str, Any]) -> str:
    if template.get("runtimeValue"):
        return str(template["runtimeValue"])
    path_kind = str(template.get("pathKind") or "directory")
    return _PATH_KIND_DEFAULTS.get(path_kind, _PATH_KIND_DEFAULTS["directory"])["runtimeValue"]


def _template_select(template: dict[str, Any]) -> dict[str, Any]:
    if isinstance(template.get("select"), dict):
        return dict(template["select"])
    path_kind = str(template.get("pathKind") or "directory")
    return {
        "allowDirectory": path_kind in {"directory", "prefix", "file", "composite"},
        "allowFile": path_kind in {"file", "prefix", "primary_with_sidecars"},
        "fileExtensions": _template_file_extensions(template),
    }


def _template_resolve(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("resolve"), dict):
        return {str(key): str(value) for key, value in template["resolve"].items()}
    path_kind = str(template.get("pathKind") or "directory")
    strategy = {
        "directory": "selected_directory",
        "file": "matching_file",
        "prefix": "index_prefix",
        "primary_with_sidecars": "primary_file_with_sidecars",
        "composite": "composite_fields",
    }.get(path_kind, "selected_path")
    return {"strategy": strategy}


def _template_validation(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("validation"), dict):
        return {str(key): str(value) for key, value in template["validation"].items()}
    path_kind = str(template.get("pathKind") or "directory")
    return {
        "structureCheck": {
            "directory": "required_files_and_patterns",
            "file": "file_pattern",
            "prefix": "complete_prefix_set",
            "primary_with_sidecars": "primary_file_and_sidecars",
            "composite": "field_paths_and_field_rules",
        }.get(path_kind, "path_exists"),
    }


def _template_output(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("output"), dict):
        return {str(key): str(value) for key, value in template["output"].items()}
    if str(template.get("pathKind") or "directory") == "composite":
        return {"valueFrom": "resolved"}
    return {"resolvedKey": "default"}


def _template_runtime(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("runtime"), dict):
        return {str(key): str(value) for key, value in template["runtime"].items()}
    label = str(template.get("label") or "database")
    runtime_value = _template_runtime_value(template)
    examples = {
        "selected_path": f"{label} uses <数据库目录>",
        "resolved_file": f"{label} uses <解析后的文件>",
        "resolved_prefix": f"{label} uses <解析后的 prefix>",
        "primary_file": f"{label} uses <主文件>",
        "resolved_entries": f"{label} uses <resolved 字段对象>",
    }
    return {"example": examples.get(runtime_value, f"{label} uses <resolved.default>")}


def _template_runtime_shape(template: dict[str, Any]) -> dict[str, Any]:
    if isinstance(template.get("runtimeShape"), dict):
        return dict(template["runtimeShape"])
    path_kind = str(template.get("pathKind") or "directory")
    shape = dict(_RUNTIME_SHAPE_DEFAULTS.get(path_kind, _RUNTIME_SHAPE_DEFAULTS["directory"]))
    if path_kind == "composite":
        shape["entries"] = {
            str(key): {
                "pathKind": str((spec if isinstance(spec, dict) else {}).get("pathKind") or "directory"),
                "required": bool((spec if isinstance(spec, dict) else {}).get("required", True)),
            }
            for key, spec in dict(template.get("fields") or {}).items()
        }
    return shape


def _template_capabilities(template: dict[str, Any]) -> list[str]:
    raw = template.get("capabilities")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    db_type = str(template.get("type") or "reference")
    capabilities = list(_TYPE_CAPABILITY_DEFAULTS.get(db_type, ["reference_database"]))
    path_kind = str(template.get("pathKind") or "directory")
    if path_kind == "prefix":
        capabilities.append("indexed_database")
    if path_kind == "composite":
        capabilities.append("multi_asset_database")
    return capabilities


def _template_file_extensions(template: dict[str, Any]) -> list[str]:
    extensions: list[str] = []
    for key in ("requiredSuffixes", "primaryExtensions"):
        extensions.extend(str(value) for value in template.get(key, []) if str(value).startswith("."))
    for pattern in template.get("anyPatterns", []):
        text = str(pattern)
        if text.startswith("*."):
            extensions.append(text[1:])
    return sorted(set(extensions))


def _template_expected_files(template: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "requiredFiles",
        "requiredPatterns",
        "requiredSuffixes",
        "anyPatterns",
        "anyIndexPatterns",
        "anyFiles",
        "primaryExtensions",
        "sidecars",
        "indexSuffixes",
    ):
        values.extend(str(item) for item in template.get(key, []) if str(item).strip())
    for pattern_set in template.get("prefixPatternSets", []):
        values.append("prefix" + " + prefix".join(str(item) for item in pattern_set if str(item).strip()))
    values.extend(str(item) for item in template.get("prefixAliasPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("companionSuffixes", []) if str(item).strip())
    for pattern_set in template.get("anyPatternSets", []):
        values.append(" / ".join(str(item) for item in pattern_set if str(item).strip()))
    return values
