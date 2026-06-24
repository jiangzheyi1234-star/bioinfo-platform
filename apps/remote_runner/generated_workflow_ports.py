from __future__ import annotations

from pathlib import Path
from typing import Any

from .generated_workflow_names import safe_identifier, safe_relative_output_path, safe_snakemake_name
from .rule_command import command_param_names, validate_command_input_tokens_bound
from core.contracts.rule_ports import validate_input_binding_compatibility


_MISSING = object()


def resolve_step_params(
    *,
    rule_template: dict[str, Any],
    requested_step: dict[str, Any],
) -> dict[str, Any]:
    declared = declared_rule_params(rule_template)
    resolved = {name: value for name, value in declared.items() if value is not _MISSING}
    if "params" in requested_step:
        resolved.update(validate_step_params(requested_step.get("params"), declared))
    for name in command_param_names(str(rule_template.get("commandTemplate") or "")):
        if name not in resolved:
            raise ValueError(f"WORKFLOW_STEP_PARAM_REQUIRED: {name}")
    return resolved


def declared_rule_params(rule_template: dict[str, Any]) -> dict[str, Any]:
    raw = rule_template.get("params") or {}
    if not isinstance(raw, dict):
        raise ValueError("TOOL_RULE_PARAMS_INVALID")
    declared: dict[str, Any] = {}
    for key, value in raw.items():
        name = safe_snakemake_name(str(key or ""))
        if isinstance(value, dict):
            declared[name] = normalize_param_value(value["default"]) if "default" in value else _MISSING
        else:
            declared[name] = normalize_param_value(value)
    return declared


def validate_step_params(raw: Any, declared: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("WORKFLOW_STEP_PARAMS_INVALID")
    resolved: dict[str, Any] = {}
    for key, value in raw.items():
        name = safe_snakemake_name(str(key or ""))
        if name not in declared:
            raise ValueError(f"WORKFLOW_STEP_PARAM_UNKNOWN: {name}")
        resolved[name] = normalize_param_value(value)
    return resolved


def normalize_param_value(value: Any) -> str | int | float | bool:
    if isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("WORKFLOW_STEP_PARAM_VALUE_INVALID")


def resolve_step_inputs(
    *,
    step_id: str,
    requested_step: dict[str, Any],
    rule_template: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
    output_port_specs_by_step_id: dict[str, dict[str, dict[str, str]]],
) -> dict[str, str]:
    explicit_inputs = requested_step.get("inputs")
    mapped = resolve_explicit_step_inputs(
        explicit_inputs if explicit_inputs is not None else {},
        step_id=step_id,
        rule_template=rule_template,
        resolved_inputs=resolved_inputs,
        outputs_by_step_id=outputs_by_step_id,
        output_port_specs_by_step_id=output_port_specs_by_step_id,
    )
    validate_required_step_inputs(rule_template=rule_template, inputs=mapped)
    validate_command_input_tokens_bound(rule_template=rule_template, inputs=mapped)
    return mapped


def validate_required_step_inputs(*, rule_template: dict[str, Any], inputs: dict[str, str]) -> None:
    provided = {safe_snakemake_name(name) for name in inputs}
    for index, spec in enumerate([item for item in (rule_template.get("inputs") or []) if isinstance(item, dict)]):
        if not bool(spec.get("required", True)):
            continue
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        if name and safe_snakemake_name(name) not in provided:
            raise ValueError(f"TOOL_INPUT_REQUIRED: {name}")


def resolve_explicit_step_inputs(
    raw: Any,
    *,
    step_id: str,
    rule_template: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
    output_port_specs_by_step_id: dict[str, dict[str, dict[str, str]]],
) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("WORKFLOW_STEP_INPUTS_INVALID")
    mapped: dict[str, str] = {}
    declared_inputs = declared_rule_input_names(rule_template)
    for name, binding in raw.items():
        input_name = safe_snakemake_name(str(name or ""))
        if not input_name:
            raise ValueError("WORKFLOW_STEP_INPUT_NAME_REQUIRED")
        if input_name not in declared_inputs:
            raise ValueError(f"WORKFLOW_STEP_INPUT_PORT_UNKNOWN: {step_id}.{input_name}")
        if not isinstance(binding, dict):
            raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        validate_input_binding_compatibility(
            input_name=input_name,
            binding=binding,
            rule_template=rule_template,
            resolved_inputs=resolved_inputs,
            upstream_output_specs=output_port_specs_by_step_id,
        )
        mapped[input_name] = resolve_input_binding(
            binding,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
        )
    return mapped


def declared_rule_input_names(rule_template: dict[str, Any]) -> set[str]:
    specs = [item for item in (rule_template.get("inputs") or []) if isinstance(item, dict)]
    if not specs:
        return {"primary"}
    return {
        safe_snakemake_name(str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")))
        for index, spec in enumerate(specs)
    }


def resolve_input_binding(
    binding: Any,
    *,
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
) -> str:
    if not isinstance(binding, dict):
        raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
    from_step = str(binding.get("fromStep") or "").strip()
    if from_step:
        step_outputs = outputs_by_step_id.get(safe_identifier(from_step))
        if step_outputs is None:
            raise ValueError(f"WORKFLOW_STEP_INPUT_STEP_UNKNOWN: {from_step}")
        output_name = str(binding.get("output") or "").strip()
        if not output_name:
            raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        if output_name not in step_outputs:
            raise ValueError(f"WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN: {from_step}.{output_name}")
        return str(step_outputs[output_name])
    if "fromUpload" in binding:
        raise ValueError("WORKFLOW_STEP_INPUT_BINDING_UNSUPPORTED: fromUpload")
    if "fromInput" in binding:
        role = str(binding.get("fromInput") or "").strip()
        if not role:
            raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        for index, item in enumerate(resolved_inputs):
            item_role = str(item.get("role") or ("input" if index == 0 else f"input_{index + 1}")).strip()
            if item_role == role:
                return str(item.get("path") or f"input_{index + 1}")
        raise ValueError(f"WORKFLOW_STEP_INPUT_ROLE_UNKNOWN: {role}")
    raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")


def resolve_outputs(*, rule_template: dict[str, Any], result_dir: Path, output_prefix: str = "") -> dict[str, Path]:
    specs = [item for item in (rule_template.get("outputs") or []) if isinstance(item, dict)]
    if not specs:
        raise ValueError("TOOL_OUTPUTS_REQUIRED")
    outputs: dict[str, Path] = {}
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("tool_output" if index == 0 else f"output_{index + 1}")).strip()
        requested_path = str(spec.get("path") or "").strip()
        if not requested_path:
            raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
        path = safe_relative_output_path(requested_path)
        if output_prefix:
            path = (
                Path(path.parent, f"{output_prefix}-{path.name}")
                if path.parent != Path(".")
                else Path(f"{output_prefix}-{path.name}")
            )
        outputs[name] = result_dir / path
    if not outputs:
        raise ValueError("TOOL_OUTPUT_REQUIRED")
    return outputs
