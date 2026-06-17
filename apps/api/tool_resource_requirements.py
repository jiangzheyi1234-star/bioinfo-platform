from __future__ import annotations

from typing import Any


def required_resource_summary(prepare_payload: dict[str, Any]) -> dict[str, Any]:
    template = prepare_payload.get("ruleTemplate") if isinstance(prepare_payload.get("ruleTemplate"), dict) else {}
    resources = template.get("resources") if isinstance(template.get("resources"), dict) else {}
    required: list[dict[str, Any]] = []
    for key, value in resources.items():
        if not isinstance(value, dict) or not value.get("required"):
            continue
        resource_key = str(key).strip()
        if not resource_key:
            continue
        required.append(
            {
                "resourceKey": resource_key,
                "configKey": str(value.get("configKey") or resource_key).strip(),
                "type": str(value.get("type") or "").strip(),
                "acceptedTemplates": _string_list(value.get("acceptedTemplates")),
                "acceptedCapabilities": _string_list(value.get("acceptedCapabilities")),
                "nextAction": "add-database" if str(value.get("type") or "") == "database" else "bind-resource",
            }
        )
    return {
        "requiredResourceKeys": [item["resourceKey"] for item in required],
        "requiredResources": required,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
