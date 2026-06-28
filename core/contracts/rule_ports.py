from __future__ import annotations

import re
from typing import Any


HARD_COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format", "resource"]
ADVISORY_COMPATIBILITY_FIELDS = ["operation"]
COMPATIBILITY_FIELDS = [*HARD_COMPATIBILITY_FIELDS, *ADVISORY_COMPATIBILITY_FIELDS]
EDAM_COMPATIBILITY_FIELDS = {"data", "format", "operation"}
EDAM_FIELD_PREFIXES = {
    "data": "data",
    "format": "format",
    "operation": "operation",
}
UNSUPPORTED_GENERIC_EDAM_VALUES = {
    "data": {"data_0006"},
    "format": {"format_1915"},
}


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
    resolved_inputs: list[dict[str, Any]],
    upstream_output_specs: dict[str, dict[str, dict[str, str]]],
) -> None:
    if not isinstance(binding, dict):
        return
    input_spec = _input_port_spec(rule_template, input_name)
    from_step = str(binding.get("fromStep") or "").strip()
    if from_step:
        output_name = str(binding.get("output") or "").strip()
        if not output_name:
            raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        source_specs = upstream_output_specs.get(_safe_identifier(from_step)) or {}
        source_spec = source_specs.get(output_name) or {}
        source_label = f"{from_step}.{output_name}"
    else:
        from_input = str(binding.get("fromInput") or "").strip()
        if not from_input:
            return
        source_spec = _workflow_input_port_spec(resolved_inputs, from_input)
        source_label = f"input.{from_input}"
    if not ports_compatible(input_spec, source_spec):
        raise ValueError(f"WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: {source_label} -> {input_name}")


def _workflow_input_port_spec(resolved_inputs: list[dict[str, Any]], role: str) -> dict[str, str]:
    for item in resolved_inputs:
        if str(item.get("role") or "").strip() == role:
            return port_spec_from_rule_item(item)
    return {}


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
    return spec


def ports_compatible(input_spec: dict[str, str], output_spec: dict[str, str]) -> bool:
    return port_compatibility_decision(input_spec, output_spec)["compatible"] is True


def port_compatibility_decision(input_spec: dict[str, str], output_spec: dict[str, str]) -> dict[str, Any]:
    mismatch = mismatched_compatibility_field(input_spec, output_spec)
    score = port_compatibility_score(input_spec, output_spec)
    generic_fields = generic_compatibility_fields(input_spec, output_spec)
    advisory_fields = matched_advisory_compatibility_fields(input_spec, output_spec)
    return {
        "compatible": score is not None,
        "score": score,
        "matchedFields": matched_compatibility_fields(input_spec, output_spec),
        "genericFields": generic_fields,
        "advisoryFields": advisory_fields,
        "mismatchedField": mismatch,
        "hardChecks": _hard_checks(mismatch=mismatch, generic_fields=generic_fields),
        "advisoryChecks": _advisory_checks(advisory_fields),
        "inputSpec": dict(input_spec),
        "outputSpec": dict(output_spec),
    }


def port_compatibility_score(input_spec: dict[str, str], output_spec: dict[str, str]) -> int | None:
    score = 0
    for key in HARD_COMPATIBILITY_FIELDS:
        input_value = normalized_compatibility_value(key, input_spec.get(key))
        output_value = normalized_compatibility_value(key, output_spec.get(key))
        relation = _compatibility_relation(key, input_value, output_value)
        if relation in {"conflict", "generic"}:
            return None
        if relation == "exact":
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


def generic_compatibility_fields(input_spec: dict[str, str], output_spec: dict[str, str]) -> list[str]:
    return [
        key
        for key in HARD_COMPATIBILITY_FIELDS
        if _compatibility_relation(
            key,
            normalized_compatibility_value(key, input_spec.get(key)),
            normalized_compatibility_value(key, output_spec.get(key)),
        )
        == "generic"
    ]


def mismatched_compatibility_field(input_spec: dict[str, str], output_spec: dict[str, str]) -> str:
    for key in HARD_COMPATIBILITY_FIELDS:
        input_value = normalized_compatibility_value(key, input_spec.get(key))
        output_value = normalized_compatibility_value(key, output_spec.get(key))
        if _compatibility_relation(key, input_value, output_value) == "conflict":
            return key
    return ""


def matched_advisory_compatibility_fields(input_spec: dict[str, str], output_spec: dict[str, str]) -> list[str]:
    return [
        key
        for key in ADVISORY_COMPATIBILITY_FIELDS
        if (input_value := normalized_compatibility_value(key, input_spec.get(key)))
        and input_value == normalized_compatibility_value(key, output_spec.get(key))
        and not _is_invalid_edam_value(key, input_value)
    ]


def normalized_compatibility_value(field: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if field not in EDAM_COMPATIBILITY_FIELDS:
        return text
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    normalized = re.sub(r"^EDAM:", "", text, flags=re.IGNORECASE)
    return normalized


def _compatibility_relation(field: str, input_value: str, output_value: str) -> str:
    if input_value and output_value and _is_generic_edam_value(field, input_value, output_value):
        return "generic"
    if (input_value and _is_invalid_edam_value(field, input_value)) or (
        output_value and _is_invalid_edam_value(field, output_value)
    ):
        return "conflict"
    if input_value and output_value and input_value == output_value:
        return "exact"
    if input_value and output_value:
        return "conflict"
    return "missing"


def _is_generic_edam_value(field: str, left: str, right: str) -> bool:
    return left in UNSUPPORTED_GENERIC_EDAM_VALUES.get(field, set()) or right in UNSUPPORTED_GENERIC_EDAM_VALUES.get(field, set())


def _is_invalid_edam_value(field: str, value: str) -> bool:
    prefix = EDAM_FIELD_PREFIXES.get(field)
    if prefix is None or not value:
        return False
    return re.fullmatch(rf"{re.escape(prefix)}_\d+", value) is None


def _hard_checks(*, mismatch: str, generic_fields: list[str]) -> list[str]:
    if mismatch:
        return ["port-direction:output-to-input", f"{mismatch}:conflict"]
    if generic_fields:
        return ["port-direction:output-to-input", *[f"{field}:generic-root-unsupported" for field in generic_fields]]
    checks = ["port-direction:output-to-input", "semantic-fields-compatible"]
    return checks


def _advisory_checks(fields: list[str]) -> list[str]:
    return [f"{field}:advisory-compatible" for field in fields]


def _rule_io_items(rule_template: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [item for item in (rule_template.get(key) or []) if isinstance(item, dict)]


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"
