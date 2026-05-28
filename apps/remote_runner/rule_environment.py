from __future__ import annotations

import json
from typing import Any


def render_rule_conda_env_yaml(*, rule_template: dict[str, Any], source: str, package_spec: str) -> str:
    conda = rule_template.get("environment", {}).get("conda") if isinstance(rule_template.get("environment"), dict) else None
    conda = conda if isinstance(conda, dict) else {}
    channels = _string_list(conda.get("channels"), error_code="TOOL_RULE_ENVIRONMENT_CHANNELS_INVALID") or _channels_for_source(source)
    dependencies = _string_list(
        conda.get("dependencies"),
        error_code="TOOL_RULE_ENVIRONMENT_DEPENDENCIES_INVALID",
    ) or [package_spec]
    if not dependencies or any(not item for item in dependencies):
        raise ValueError("TOOL_RULE_ENVIRONMENT_DEPENDENCIES_REQUIRED")
    if "nodefaults" not in channels:
        channels = [*channels, "nodefaults"]
    channel_lines = "".join(f"  - {channel}\n" for channel in channels)
    dependency_lines = "".join(f"  - {json.dumps(dependency)}\n" for dependency in dependencies)
    return f"channels:\n{channel_lines}dependencies:\n{dependency_lines}"


def _string_list(raw: Any, *, error_code: str) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError(error_code)
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value:
            raise ValueError(error_code)
        if value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def _channels_for_source(source: str) -> list[str]:
    return ["conda-forge", "bioconda"]
