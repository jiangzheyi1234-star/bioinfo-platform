from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .database_templates import DATABASE_TEMPLATES
from .databases import list_reference_databases
from .tool_resource_codes import WAITING_RESOURCE_CODES


def workflow_resource_failure(cfg: RemoteRunnerConfig, tool: dict[str, Any], exc: Exception) -> dict[str, Any] | None:
    code, resource_key = _split_resource_error(str(exc))
    if code not in WAITING_RESOURCE_CODES:
        return None
    details = build_resource_wait_details(cfg, tool, resource_key)
    code = _normalized_resource_wait_code(code, details)
    return {
        "code": code,
        "message": _resource_wait_message(code, resource_key),
        "details": details,
    }


def build_resource_wait_details(cfg: RemoteRunnerConfig, tool: dict[str, Any], resource_key: str) -> dict[str, Any]:
    spec = _database_resource_specs(tool).get(resource_key, {}) if resource_key else {}
    details: dict[str, Any] = {"resourceType": "database"}
    if resource_key:
        details["resourceKey"] = resource_key
    config_key = str(spec.get("configKey") or resource_key or "").strip()
    if config_key:
        details["configKey"] = config_key
    accepted_templates = [str(item).strip() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates:
        details["acceptedTemplates"] = accepted_templates
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        details["acceptedCapabilities"] = accepted_capabilities
    details["candidates"] = _resource_wait_candidates(cfg, spec)
    return details


def smoke_resource_bindings(
    cfg: RemoteRunnerConfig,
    tool: dict[str, Any],
    smoke_test: dict[str, Any],
) -> dict[str, Any]:
    bindings = dict(smoke_test.get("resourceBindings") or {}) if isinstance(smoke_test.get("resourceBindings"), dict) else {}
    for resource_key, spec in _database_resource_specs(tool).items():
        if spec.get("required", True) is False:
            continue
        if resource_key in bindings:
            continue
        matches = [database for database in list_reference_databases(cfg) if _database_matches_resource_spec(database, spec)]
        if len(matches) == 1:
            bindings[resource_key] = {"databaseId": str(matches[0].get("id") or "")}
    return bindings


def _split_resource_error(raw: str) -> tuple[str, str]:
    code, separator, remainder = str(raw or "").partition(":")
    return code.strip(), remainder.strip() if separator else ""


def _resource_wait_message(code: str, resource_key: str) -> str:
    label = resource_key or "required database resource"
    if code in {"RESOURCE_BINDING_MISSING", "WORKFLOW_RESOURCE_BINDING_REQUIRED"}:
        return f"Required database resource binding is missing: {label}"
    if code == "RESOURCE_BINDING_AMBIGUOUS":
        return f"Required database resource binding is ambiguous: {label}"
    if code == "WORKFLOW_RESOURCE_UNAVAILABLE":
        return f"Required database resource is unavailable: {label}"
    return f"Required database resource is waiting: {label}"


def _normalized_resource_wait_code(code: str, details: dict[str, Any]) -> str:
    if code != "WORKFLOW_RESOURCE_BINDING_REQUIRED":
        return code
    candidates = details.get("candidates")
    if isinstance(candidates, list) and len(candidates) > 1:
        return "RESOURCE_BINDING_AMBIGUOUS"
    return "RESOURCE_BINDING_MISSING"


def _resource_wait_candidates(cfg: RemoteRunnerConfig, spec: dict[str, Any]) -> list[dict[str, str]]:
    if not spec:
        return []
    return [
        _resource_wait_candidate(database)
        for database in list_reference_databases(cfg)
        if _database_matches_resource_spec(database, spec)
    ]


def _resource_wait_candidate(database: dict[str, Any]) -> dict[str, str]:
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    return {
        "id": str(database.get("id") or ""),
        "name": str(database.get("name") or ""),
        "templateId": str(metadata.get("templateId") or ""),
        "version": str(database.get("version") or ""),
        "status": str(database.get("status") or ""),
    }


def _database_resource_specs(tool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    resources = template.get("resources")
    if not isinstance(resources, dict):
        return {}
    specs: dict[str, dict[str, Any]] = {}
    for key, value in resources.items():
        if not isinstance(value, dict):
            continue
        if value.get("acceptedTemplates") or value.get("acceptedCapabilities") or value.get("configKey") or value.get("type") == "database":
            specs[str(key)] = value
    return specs


def _database_matches_resource_spec(database: dict[str, Any], spec: dict[str, Any]) -> bool:
    if str(database.get("status") or "") != "available":
        return False
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    template_id = str(metadata.get("templateId") or "").strip().lower()
    accepted_templates = [str(item).strip().lower() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates and template_id not in accepted_templates:
        return False
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        capabilities = [
            str(item).strip()
            for item in metadata.get("capabilities") or DATABASE_TEMPLATES.get(template_id, {}).get("capabilities") or []
            if str(item).strip()
        ]
        if not any(capability in capabilities for capability in accepted_capabilities):
            return False
    return True
