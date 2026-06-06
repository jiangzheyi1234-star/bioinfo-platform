from __future__ import annotations

import json
from typing import Any


def tool_prepare_job_reservation(payload: dict[str, Any], fallback_tool_id: str) -> dict[str, str]:
    package_spec = normalized_reservation_part(payload.get("packageSpec")) or normalized_reservation_part(
        fallback_tool_id
    )
    validation_target = normalized_reservation_part(payload.get("validationTarget"))
    key = f"{validation_target}\x1f{package_spec}" if package_spec else ""
    return {
        "key": key,
        "packageSpec": package_spec,
        "validationTarget": validation_target,
    }


def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalized_reservation_part(value: Any) -> str:
    return str(value or "").strip().lower()
