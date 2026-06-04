from __future__ import annotations

from typing import Any

from .tools_errors import ToolRegistryError


def normalize_rule_environment(raw: Any) -> dict[str, Any]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ToolRegistryError("TOOL_RULE_ENVIRONMENT_INVALID")
    conda = raw.get("conda")
    if conda in (None, {}):
        return {}
    if not isinstance(conda, dict):
        raise ToolRegistryError("TOOL_RULE_ENVIRONMENT_CONDA_INVALID")
    channels = _normalize_string_list(conda.get("channels"), error_code="TOOL_RULE_ENVIRONMENT_CHANNELS_INVALID")
    dependencies = _normalize_string_list(
        conda.get("dependencies"),
        error_code="TOOL_RULE_ENVIRONMENT_DEPENDENCIES_INVALID",
    )
    normalized_conda: dict[str, Any] = {}
    if channels:
        normalized_conda["channels"] = channels
    if dependencies:
        normalized_conda["dependencies"] = dependencies
    return {"conda": normalized_conda} if normalized_conda else {}


def _normalize_string_list(raw: Any, *, error_code: str) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(error_code)
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value:
            raise ToolRegistryError(error_code)
        if value not in seen:
            values.append(value)
            seen.add(value)
    return values
