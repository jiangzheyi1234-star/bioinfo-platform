"""Shared parsing for local tool registry payloads."""

from __future__ import annotations

from typing import Any


def registered_tools_from_runtime_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        items = data.get("items") if isinstance(data, dict) else payload.get("items")
    else:
        items = None
    if not isinstance(items, list):
        raise ValueError("Invalid tools registry payload: expected an items list")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid tools registry payload: tool items must be objects")
    return items
