from __future__ import annotations

from typing import Any

from .tool_rule_names import RULE_IO_NAME_RE
from .tools_errors import ToolRegistryError


SCHEDULER_RESOURCE_KEYS = {"mem_mb", "disk_mb", "runtime", "tmpdir"}


def normalize_rule_resources(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {"workflowResources": {}, "schedulerResources": {}, "threads": None}
    if not isinstance(raw, dict):
        raise ToolRegistryError("WORKFLOW_RESOURCE_SPEC_INVALID")
    workflow_resources: dict[str, dict[str, Any]] = {}
    scheduler_resources: dict[str, str | int | float] = {}
    threads: int | None = None
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key or not RULE_IO_NAME_RE.match(resource_key):
            raise ToolRegistryError("WORKFLOW_RESOURCE_KEY_REQUIRED")
        if resource_key == "threads":
            threads = normalize_rule_threads(value)
            continue
        if _is_scheduler_resource(resource_key, value):
            scheduler_resources[resource_key] = _normalize_scheduler_resource_value(resource_key, value)
            continue
        if not isinstance(value, dict):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_SPEC_INVALID: {resource_key}")
        config_key = str(value.get("configKey") or resource_key).strip()
        if not config_key or not RULE_IO_NAME_RE.match(config_key):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_CONFIG_KEY_REQUIRED: {resource_key}")
        accepted_templates = value.get("acceptedTemplates") or []
        if accepted_templates and (
            not isinstance(accepted_templates, list)
            or any(not str(item).strip() for item in accepted_templates)
        ):
            raise ToolRegistryError(f"WORKFLOW_RESOURCE_ACCEPTED_TEMPLATES_INVALID: {resource_key}")
        workflow_resources[resource_key] = {**value, "configKey": config_key}
    return {"workflowResources": workflow_resources, "schedulerResources": scheduler_resources, "threads": threads}


def normalize_rule_threads(raw: Any, *, fallback: int | None = None) -> int | None:
    if raw in (None, ""):
        return fallback
    value = _rule_default_value(raw)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolRegistryError("TOOL_RULE_THREADS_INVALID")
    return value


def normalize_scheduler_resources(raw: Any) -> dict[str, str | int | float]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_SCHEDULER_RESOURCES_INVALID")
    resources: dict[str, str | int | float] = {}
    for key, value in raw.items():
        resource_key = str(key or "").strip()
        if not resource_key or not RULE_IO_NAME_RE.match(resource_key):
            raise ToolRegistryError("TOOL_RULE_SCHEDULER_RESOURCE_KEY_REQUIRED")
        resources[resource_key] = _normalize_scheduler_resource_value(resource_key, value)
    return resources


def _is_scheduler_resource(key: str, value: Any) -> bool:
    if key in SCHEDULER_RESOURCE_KEYS:
        return True
    if not isinstance(value, dict):
        return False
    resource_type = str(value.get("type") or "").strip()
    if resource_type in {"compute", "scheduler"}:
        return True
    has_database_markers = any(marker in value for marker in ["acceptedTemplates", "acceptedCapabilities", "configKey"])
    return "default" in value and not has_database_markers


def _normalize_scheduler_resource_value(key: str, raw: Any) -> str | int | float:
    value = _rule_default_value(raw)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value == "":
        raise ToolRegistryError(f"TOOL_RULE_SCHEDULER_RESOURCE_VALUE_INVALID: {key}")
    return value


def _rule_default_value(raw: Any) -> Any:
    if isinstance(raw, dict):
        if "default" in raw:
            return raw["default"]
        if "value" in raw:
            return raw["value"]
        raise ToolRegistryError("TOOL_RULE_RUNTIME_DEFAULT_REQUIRED")
    return raw
