from __future__ import annotations

from typing import Any

from .database_layers import database_layer
from .database_runtime_paths import (
    compute_database_entry_path,
    database_resolved_config_value,
    database_resolved_values,
)
from .database_templates import DATABASE_TEMPLATES
from .databases import check_reference_database


def build_workflow_resource_config(
    cfg: Any,
    *,
    workflow_resource_spec: dict[str, Any] | None,
    bindings: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    specs = _normalize_resource_specs(workflow_resource_spec)
    normalized_bindings = {str(key): value for key, value in dict(bindings or {}).items()}
    resources: dict[str, dict[str, Any]] = {}
    config: dict[str, Any] = {}

    for resource_key, spec in specs.items():
        database_id = _binding_database_id(normalized_bindings.get(resource_key))
        required = bool(spec.get("required", True))
        if not database_id:
            if required:
                raise ValueError(f"WORKFLOW_RESOURCE_BINDING_REQUIRED: {resource_key}")
            continue

        database = check_reference_database(cfg, database_id)
        if str(database.get("status") or "") != "available":
            raise ValueError(f"WORKFLOW_RESOURCE_UNAVAILABLE: {resource_key}")

        template_id = str((database.get("metadata") or {}).get("templateId") or "").strip().lower()
        if not template_id:
            raise ValueError(f"WORKFLOW_RESOURCE_TEMPLATE_REQUIRED: {resource_key}")
        accepted_templates = [str(item).strip().lower() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
        if accepted_templates and template_id not in accepted_templates:
            raise ValueError(f"WORKFLOW_RESOURCE_TEMPLATE_UNSUPPORTED: {resource_key}")
        template_capabilities = [
            str(item).strip()
            for item in (database.get("metadata") or {}).get("capabilities") or DATABASE_TEMPLATES.get(template_id, {}).get("capabilities") or []
            if str(item).strip()
        ]
        accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
        if accepted_capabilities and not any(capability in template_capabilities for capability in accepted_capabilities):
            raise ValueError(f"WORKFLOW_RESOURCE_CAPABILITY_UNSUPPORTED: {resource_key}")

        input_path = str(database.get("inputPath") or database.get("path") or "")
        path = compute_database_entry_path(database)
        resolved_values = database_resolved_values(database) or {"default": path}
        config_value = database_resolved_config_value(database)
        runtime_shape = dict((database.get("metadata") or {}).get("runtimeShape") or DATABASE_TEMPLATES.get(template_id, {}).get("runtimeShape") or {})
        path_mode = str(database.get("pathMode") or (database.get("metadata") or {}).get("pathMode") or DATABASE_TEMPLATES.get(template_id, {}).get("pathKind") or "")
        config_key = str(spec.get("configKey") or resource_key).strip()
        if not config_key:
            raise ValueError(f"WORKFLOW_RESOURCE_CONFIG_KEY_REQUIRED: {resource_key}")
        config[config_key] = config_value
        resources[resource_key] = {
            "resourceKey": resource_key,
            "databaseId": database["id"],
            "databaseLayer": database_layer(database),
            "name": database["name"],
            "type": database["type"],
            "templateId": template_id,
            "templateLabel": str((database.get("metadata") or {}).get("templateLabel") or DATABASE_TEMPLATES.get(template_id, {}).get("label") or template_id),
            "version": database["version"],
            "path": path,
            "input": database.get("input") or (database.get("metadata") or {}).get("input") or {"kind": "single", "path": input_path},
            "resolved": resolved_values,
            "inputPath": input_path,
            "entryPath": path,
            "pathMode": path_mode,
            "runtimeShape": runtime_shape,
            "capabilities": template_capabilities,
            "configKey": config_key,
            "required": required,
        }

    return {"resources": resources, "config": config}


def collect_workflow_resource_specs(rule_templates: list[dict[str, Any]]) -> dict[str, Any]:
    specs: dict[str, Any] = {}
    for rule_template in rule_templates:
        raw = rule_template.get("resources")
        if raw is None:
            continue
        for resource_key, spec in _normalize_resource_specs(raw).items():
            if resource_key in specs and specs[resource_key] != spec:
                raise ValueError(f"WORKFLOW_RESOURCE_SPEC_CONFLICT: {resource_key}")
            specs[resource_key] = spec
    return specs


def _normalize_resource_specs(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("WORKFLOW_RESOURCE_SPEC_INVALID")
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key:
            raise ValueError("WORKFLOW_RESOURCE_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise ValueError(f"WORKFLOW_RESOURCE_SPEC_INVALID: {resource_key}")
        normalized[resource_key] = dict(value)
    return normalized


def _binding_database_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("databaseId") or value.get("id") or "").strip()
    return str(value or "").strip()
