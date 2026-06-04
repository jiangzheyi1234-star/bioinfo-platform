from __future__ import annotations

from typing import Any

from config import get_config, save_config


def get_runtime_config() -> dict[str, Any]:
    return get_config()


def save_runtime_config(config: dict[str, Any]) -> None:
    save_config(config)


def merge_runtime_config_patch(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(config)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged
