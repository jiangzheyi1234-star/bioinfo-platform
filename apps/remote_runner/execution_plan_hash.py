from __future__ import annotations

import hashlib
import json
from typing import Any


def attach_plan_hash(plan: dict[str, Any]) -> dict[str, Any]:
    public = dict(plan)
    public["planHash"] = stable_plan_hash(public)
    return public


def stable_plan_hash(plan: dict[str, Any]) -> str:
    payload = json.dumps(
        _without_plan_hash(plan),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _without_plan_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_plan_hash(item) for key, item in value.items() if key != "planHash"}
    if isinstance(value, list):
        return [_without_plan_hash(item) for item in value]
    return value
