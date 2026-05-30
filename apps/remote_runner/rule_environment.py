from __future__ import annotations

import json
from typing import Any


def render_rule_conda_env_yaml(*, rule_template: dict[str, Any], source: str, package_spec: str) -> str:
    conda = rule_template.get("environment", {}).get("conda") if isinstance(rule_template.get("environment"), dict) else None
    conda = conda if isinstance(conda, dict) else {}
    channels = _string_list(conda.get("channels"), error_code="TOOL_RULE_ENVIRONMENT_CHANNELS_INVALID")
    dependencies = _string_list(
        conda.get("dependencies"),
        error_code="TOOL_RULE_ENVIRONMENT_DEPENDENCIES_INVALID",
    )
    if not channels:
        raise ValueError("TOOL_RULE_ENVIRONMENT_CHANNELS_REQUIRED")
    if not dependencies:
        raise ValueError("TOOL_RULE_ENVIRONMENT_DEPENDENCIES_REQUIRED")
    for dependency in dependencies:
        if not _dependency_locked(dependency):
            raise ValueError(f"TOOL_RULE_ENVIRONMENT_DEPENDENCY_LOCK_REQUIRED: {dependency}")
    if not _channel_priority_strict(channels):
        raise ValueError("TOOL_RULE_ENVIRONMENT_CHANNEL_PRIORITY_REQUIRED")
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


def _dependency_locked(value: str) -> bool:
    spec = value.strip()
    if not spec or any(operator in spec for operator in (">", "<", "*")):
        return False
    package = spec.rsplit("::", 1)[-1]
    if "==" in package:
        name, version = package.split("==", 1)
    elif "=" in package:
        name, version = package.split("=", 1)
    else:
        return False
    return bool(name.strip() and version.strip())


def _channel_priority_strict(channels: list[str]) -> bool:
    if not channels:
        return False
    try:
        conda_forge_index = channels.index("conda-forge")
    except ValueError:
        return False
    if "bioconda" not in channels:
        return True
    return conda_forge_index < channels.index("bioconda")
