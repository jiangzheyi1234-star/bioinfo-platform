from __future__ import annotations

import re
from typing import Any

from .tools_errors import ToolRegistryError


CAPABILITY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
CAPABILITY_SLOT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EDAM_ID_RE = re.compile(r"^EDAM:[A-Za-z_]+_[0-9]{4,}$")


def normalize_tool_capabilities(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError("TOOL_CAPABILITIES_INVALID")
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError("TOOL_CAPABILITY_INVALID")
        capability_id = str(item.get("id") or item.get("capabilityId") or "").strip()
        if not capability_id or not CAPABILITY_ID_RE.match(capability_id):
            raise ToolRegistryError("TOOL_CAPABILITY_ID_INVALID")
        if capability_id in seen:
            raise ToolRegistryError(f"TOOL_CAPABILITY_DUPLICATE: {capability_id}")
        seen.add(capability_id)
        normalized = {
            **item,
            "id": capability_id,
            "label": str(item.get("label") or item.get("name") or capability_id),
            "operation": _normalize_edam_ref(item.get("operation"), field="operation"),
            "topics": _normalize_edam_refs(item.get("topics"), field="topics"),
            "inputs": _normalize_capability_slots(item.get("inputs"), direction="input"),
            "outputs": _normalize_capability_slots(item.get("outputs"), direction="output"),
        }
        if "capabilityId" in normalized:
            del normalized["capabilityId"]
        capabilities.append(normalized)
    return capabilities


def _normalize_capability_slots(raw: Any, *, direction: str) -> list[dict[str, Any]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(f"TOOL_CAPABILITY_{direction.upper()}S_INVALID")
    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ToolRegistryError(f"TOOL_CAPABILITY_{direction.upper()}_INVALID")
        name = _normalize_slot_name(item.get("name") or item.get("slot"))
        if name in seen:
            raise ToolRegistryError(f"TOOL_CAPABILITY_SLOT_DUPLICATE: {name}")
        seen.add(name)
        slots.append(
            {
                **item,
                "name": name,
                "data": _normalize_edam_ref(item.get("data"), field="data"),
                "format": _normalize_edam_ref(item.get("format"), field="format"),
                "required": bool(item.get("required", True)),
                "primary": bool(item.get("primary", len(slots) == 0)),
            }
        )
    return slots


def _normalize_edam_refs(raw: Any, *, field: str) -> list[str]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ToolRegistryError(f"TOOL_CAPABILITY_EDAM_{field.upper()}_INVALID")
    return [_normalize_edam_ref(item, field=field) for item in raw]


def _normalize_edam_ref(raw: Any, *, field: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if not EDAM_ID_RE.match(value):
        raise ToolRegistryError(f"TOOL_CAPABILITY_EDAM_{field.upper()}_INVALID: {value}")
    return value


def _normalize_slot_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not name:
        raise ToolRegistryError("TOOL_RULE_IO_NAME_REQUIRED")
    if not CAPABILITY_SLOT_NAME_RE.match(name):
        raise ToolRegistryError(f"TOOL_RULE_IO_NAME_INVALID: {name}")
    return name
