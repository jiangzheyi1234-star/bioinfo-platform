from __future__ import annotations

from typing import Any


def summarize_smoke_test(template: dict[str, Any]) -> dict[str, Any]:
    inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
    required_inputs = [item for item in inputs if bool(item.get("required", True))]
    input_names = [_string(item.get("name")) for item in required_inputs if _string(item.get("name"))]
    raw_smoke = template.get("smokeTest")
    smoke_specified = isinstance(raw_smoke, dict)
    smoke = raw_smoke if smoke_specified else {}
    smoke_inputs = smoke.get("inputs") if isinstance(smoke.get("inputs"), dict) else {}
    missing_inputs = [name for name in input_names if not _smoke_input_ready(smoke_inputs.get(name))]
    return {
        "specified": smoke_specified and not missing_inputs,
        "inputs": len(smoke_inputs),
        "requiredInputs": len(input_names),
        "missingInputs": missing_inputs,
    }


def _smoke_input_ready(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get("content"), str) or bool(_string(raw.get("contentBase64")))


def _string(raw: Any) -> str:
    return str(raw or "").strip()
