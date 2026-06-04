from __future__ import annotations

from pathlib import Path
from typing import Any

from .generated_workflow_names import safe_identifier
from .rule_outputs import validate_exposed_output_spec


def resolve_exposed_outputs(
    *,
    workflow_spec: dict[str, Any],
    steps: list[Any],
    outputs_by_step_id: dict[str, dict[str, Path]],
) -> dict[str, dict[str, Any]]:
    raw = workflow_spec.get("outputs")
    if raw in (None, {}, []):
        last_step = steps[-1]
        for name in last_step.outputs:
            validate_exposed_output_spec(last_step.step_id, name, output_spec(last_step, name))
        return {
            name: {"step": last_step, "output": name, "path": path, "spec": output_spec(last_step, name)}
            for name, path in last_step.outputs.items()
        }
    output_bindings = normalize_exposed_output_bindings(raw)
    exposed: dict[str, dict[str, Any]] = {}
    for binding in output_bindings:
        step_id = str(binding.get("fromStep") or "").strip()
        output_name = str(binding.get("output") or "").strip()
        alias = str(binding.get("as") or "").strip()
        if not step_id or not output_name or not alias:
            raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
        step = next((item for item in steps if item.step_id == safe_identifier(step_id)), None)
        step_outputs = outputs_by_step_id.get(safe_identifier(step_id))
        if step is None or step_outputs is None:
            raise ValueError(f"WORKFLOW_OUTPUT_STEP_UNKNOWN: {step_id}")
        if output_name not in step_outputs:
            raise ValueError(f"WORKFLOW_OUTPUT_NAME_UNKNOWN: {step_id}.{output_name}")
        spec = output_spec(step, output_name)
        validate_exposed_output_spec(step_id, output_name, spec)
        exposed[alias] = {
            "step": step,
            "output": output_name,
            "path": step_outputs[output_name],
            "spec": spec,
        }
    if not exposed:
        raise ValueError("WORKFLOW_OUTPUTS_REQUIRED")
    return exposed


def normalize_exposed_output_bindings(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        if any(not isinstance(binding, dict) for binding in raw):
            raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
        return [
            {
                "fromStep": str(binding.get("fromStep") or "").strip(),
                "output": str(binding.get("output") or "").strip(),
                "as": str(binding.get("as") or "").strip(),
            }
            for binding in raw
        ]
    raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")


def output_spec(step: Any, output_name: str) -> dict[str, Any]:
    for spec in [item for item in (step.rule_template.get("outputs") or []) if isinstance(item, dict)]:
        if str(spec.get("name") or "") == output_name:
            return spec
    return {}
