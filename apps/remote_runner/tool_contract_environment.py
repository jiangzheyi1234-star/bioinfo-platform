from __future__ import annotations

from typing import Any


def summarize_contract_environment(template: dict[str, Any]) -> dict[str, Any]:
    conda = template.get("environment", {}).get("conda") if isinstance(template.get("environment"), dict) else {}
    conda = conda if isinstance(conda, dict) else {}
    channels = _string_list(conda.get("channels"))
    dependencies = _string_list(conda.get("dependencies"))
    declared = bool(channels or dependencies)
    locked = bool(dependencies) and all(_dependency_locked(item) for item in dependencies)
    channel_priority = _channel_priority_strict(channels)
    return {
        "specified": bool(channels and dependencies and locked and channel_priority),
        "declared": declared,
        "locked": locked,
        "channelPriorityStrict": channel_priority,
        "channels": channels,
        "dependencies": dependencies,
    }


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


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [value for value in (str(item or "").strip() for item in raw) if value]
