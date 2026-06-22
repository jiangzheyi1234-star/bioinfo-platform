from __future__ import annotations

import re
from typing import Any


HARD_COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format", "resource"]
ADVISORY_COMPATIBILITY_FIELDS = ["operation"]
COMPATIBILITY_FIELDS = [*HARD_COMPATIBILITY_FIELDS, *ADVISORY_COMPATIBILITY_FIELDS]
EDAM_COMPATIBILITY_FIELDS = {"data", "format", "operation"}


def build_output_port_specs(rule_template: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        name: port_spec_from_rule_item(item)
        for item in _rule_io_items(rule_template, "outputs")
        if (name := str(item.get("name") or "").strip())
    }


def validate_input_binding_compatibility(
    *,
    input_name: str,
    binding: Any,
    rule_template: dict[str, Any],
    upstream_output_specs: dict[str, dict[str, dict[str, str]]],
) -> None:
    if not isinstance(binding, dict):
        return
    from_step = str(binding.get("fromStep") or "").strip()
    if not from_step:
        return
    output_name = str(binding.get("output") or "").strip()
    if not output_name:
        raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
    source_specs = upstream_output_specs.get(_safe_identifier(from_step)) or {}
    output_spec = source_specs.get(output_name) or {}
    input_spec = _input_port_spec(rule_template, input_name)
    if not ports_compatible(input_spec, output_spec):
        raise ValueError(f"WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: {from_step}.{output_name} -> {input_name}")


def _input_port_spec(rule_template: dict[str, Any], input_name: str) -> dict[str, str]:
    for item in _rule_io_items(rule_template, "inputs"):
        if str(item.get("name") or "").strip() == input_name:
            return port_spec_from_rule_item(item)
    return {}


def port_spec_from_rule_item(rule_item: dict[str, Any]) -> dict[str, str]:
    spec: dict[str, str] = {}
    for key in COMPATIBILITY_FIELDS:
        value = str(rule_item.get(key) or "").strip()
        if value:
            spec[key] = value
    if "format" not in spec:
        edam_format = str(rule_item.get("edamFormat") or "").strip()
        if edam_format:
            spec["format"] = edam_format
    if "data" not in spec:
        edam_data = str(rule_item.get("edamData") or "").strip()
        if edam_data:
            spec["data"] = edam_data
    if "operation" not in spec:
        edam_operation = str(rule_item.get("edamOperation") or "").strip()
        if edam_operation:
            spec["operation"] = edam_operation
    if "resource" not in spec:
        edam_resource = str(rule_item.get("edamResource") or "").strip()
        if edam_resource:
            spec["resource"] = edam_resource
    return spec


def ports_compatible(input_spec: dict[str, str], output_spec: dict[str, str]) -> bool:
    return port_compatibility_decision(input_spec, output_spec)["compatible"] is True


def port_compatibility_decision(input_spec: dict[str, str], output_spec: dict[str, str]) -> dict[str, Any]:
    mismatch = mismatched_compatibility_field(input_spec, output_spec)
    score = port_compatibility_score(input_spec, output_spec)
    return {
        "compatible": score is not None,
        "score": score,
        "matchedFields": matched_compatibility_fields(input_spec, output_spec),
        "advisoryFields": matched_advisory_compatibility_fields(input_spec, output_spec),
        "mismatchedField": mismatch,
        "hardChecks": ["port-direction:output-to-input", "semantic-fields-compatible" if not mismatch else f"{mismatch}-compatible"],
        "inputSpec": dict(input_spec),
        "outputSpec": dict(output_spec),
    }


def port_compatibility_score(input_spec: dict[str, str], output_spec: dict[str, str]) -> int | None:
    score = 0
    for key in HARD_COMPATIBILITY_FIELDS:
        input_value = normalized_compatibility_value(key, input_spec.get(key))
        output_value = normalized_compatibility_value(key, output_spec.get(key))
        if input_value and output_value and input_value != output_value:
            return None
        if input_value and output_value:
            score += 4
        elif input_value or output_value:
            score += 1
    return score


def matched_compatibility_fields(input_spec: dict[str, str], output_spec: dict[str, str]) -> list[str]:
    return [
        key
        for key in HARD_COMPATIBILITY_FIELDS
        if normalized_compatibility_value(key, input_spec.get(key))
        and normalized_compatibility_value(key, input_spec.get(key)) == normalized_compatibility_value(key, output_spec.get(key))
    ]


def mismatched_compatibility_field(input_spec: dict[str, str], output_spec: dict[str, str]) -> str:
    for key in HARD_COMPATIBILITY_FIELDS:
        input_value = normalized_compatibility_value(key, input_spec.get(key))
        output_value = normalized_compatibility_value(key, output_spec.get(key))
        if input_value and output_value and input_value != output_value:
            return key
    return ""


def matched_advisory_compatibility_fields(input_spec: dict[str, str], output_spec: dict[str, str]) -> list[str]:
    return [
        key
        for key in ADVISORY_COMPATIBILITY_FIELDS
        if normalized_compatibility_value(key, input_spec.get(key))
        and normalized_compatibility_value(key, input_spec.get(key)) == normalized_compatibility_value(key, output_spec.get(key))
    ]


def normalized_compatibility_value(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if field not in EDAM_COMPATIBILITY_FIELDS:
        return text
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return re.sub(r"^EDAM:", "", text, flags=re.IGNORECASE)


def _rule_io_items(rule_template: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in (rule_template.get(key) or []) if isinstance(item, dict)]


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"
