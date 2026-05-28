from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .generated_workflow import (
    _resolve_requested_steps,
    _resolve_rule_template,
    _resolve_step_params,
    _safe_identifier,
    _safe_snakemake_name,
    _step_id,
    _step_tool_request,
    _topologically_order_steps,
)
from .pipeline import PipelineDefinition
from .storage import fetch_tool
from .tools import normalize_rule_template
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs


GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1"


class RunPreflightError(ValueError):
    pass


def preflight_run_spec(cfg: RemoteRunnerConfig, pipeline: PipelineDefinition, run_spec: dict[str, Any]) -> None:
    if pipeline.pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
        _preflight_generated_workflow(cfg, run_spec)
        return
    _preflight_pipeline_resources(cfg, pipeline, run_spec)


def _preflight_pipeline_resources(cfg: RemoteRunnerConfig, pipeline: PipelineDefinition, run_spec: dict[str, Any]) -> None:
    if not pipeline.resource_schema:
        return
    try:
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec=pipeline.resource_schema,
            bindings=dict(run_spec.get("resourceBindings") or {}),
        )
    except ValueError as exc:
        raise RunPreflightError(str(exc)) from exc


def _preflight_generated_workflow(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> None:
    if "database" in run_spec or "databases" in run_spec:
        raise RunPreflightError("RESOURCE_BINDINGS_REQUIRED")
    try:
        requested_steps = _topologically_order_steps(_resolve_requested_steps(run_spec))
    except ValueError as exc:
        raise RunPreflightError(str(exc)) from exc
    rule_templates: list[dict[str, Any]] = []
    seen_steps: set[str] = set()
    known_outputs: dict[str, set[str]] = {}
    for index, step in enumerate(requested_steps):
        step_id = _step_id(step, index)
        if not step_id:
            raise RunPreflightError("WORKFLOW_STEP_ID_REQUIRED")
        if step_id in seen_steps:
            raise RunPreflightError(f"WORKFLOW_STEP_DUPLICATE: {step_id}")
        seen_steps.add(step_id)
        tool_request = _step_tool_request(step)
        tool_id = str(tool_request.get("id") or tool_request.get("toolId") or "").strip()
        if not tool_id:
            raise RunPreflightError("TOOL_ID_REQUIRED")
        tool = fetch_tool(cfg, tool_id)
        if tool is None:
            raise RunPreflightError("TOOL_NOT_FOUND")
        if not bool(tool.get("targetPlatformSupported")):
            raise RunPreflightError("TOOL_PLATFORM_UNSUPPORTED")
        try:
            rule_template = normalize_rule_template(
                _resolve_rule_template(tool=tool, tool_request=tool_request),
                required=True,
            )
        except ValueError as exc:
            raise RunPreflightError(str(exc)) from exc
        try:
            _resolve_step_params(
                rule_template=rule_template,
                requested_step=step,
                tool_request=tool_request,
                run_spec=run_spec,
                single_step=len(requested_steps) == 1,
            )
        except ValueError as exc:
            raise RunPreflightError(str(exc)) from exc
        _preflight_step_inputs(step, known_outputs, list(run_spec.get("inputs") or []))
        _preflight_required_step_inputs(step, rule_template)
        rule_templates.append(rule_template)
        known_outputs[step_id] = {str(item.get("name") or "") for item in rule_template.get("outputs") or []}
    _preflight_exposed_outputs(run_spec, known_outputs)
    try:
        resource_specs = collect_workflow_resource_specs(rule_templates)
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec=resource_specs,
            bindings=dict(run_spec.get("resourceBindings") or {}),
        )
    except ValueError as exc:
        raise RunPreflightError(str(exc)) from exc


def _preflight_step_inputs(
    step: dict[str, Any],
    known_outputs: dict[str, set[str]],
    run_inputs: list[dict[str, Any]],
) -> None:
    raw_inputs = step.get("inputs")
    if raw_inputs is None:
        return
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise RunPreflightError("WORKFLOW_STEP_INPUTS_INVALID")
    for binding in raw_inputs.values():
        if isinstance(binding, str):
            continue
        if not isinstance(binding, dict):
            raise RunPreflightError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        from_step = str(binding.get("fromStep") or binding.get("step") or "").strip()
        if from_step:
            normalized_step = _safe_identifier(from_step)
            if normalized_step not in known_outputs:
                raise RunPreflightError(f"WORKFLOW_STEP_INPUT_STEP_UNKNOWN: {from_step}")
            output_name = str(binding.get("output") or binding.get("fromOutput") or "tool_output").strip()
            if output_name not in known_outputs[normalized_step]:
                raise RunPreflightError(f"WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN: {from_step}.{output_name}")
            continue
        if "fromUpload" in binding:
            raw_index = binding.get("fromUpload")
            try:
                index = int(raw_index or 0)
            except (TypeError, ValueError) as exc:
                raise RunPreflightError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {raw_index}") from exc
            if index < 0 or index >= len(run_inputs):
                raise RunPreflightError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {index}")
            continue
        role = str(binding.get("fromInput") or binding.get("role") or "").strip()
        if role:
            if not any(str(item.get("role") or "").strip() == role for item in run_inputs):
                raise RunPreflightError(f"WORKFLOW_STEP_INPUT_ROLE_UNKNOWN: {role}")
            continue
        raise RunPreflightError("WORKFLOW_STEP_INPUT_BINDING_INVALID")


def _preflight_required_step_inputs(step: dict[str, Any], rule_template: dict[str, Any]) -> None:
    raw_inputs = step.get("inputs")
    if raw_inputs is None:
        return
    provided = {_safe_snakemake_name(str(name or "")) for name in raw_inputs}
    for index, spec in enumerate([item for item in (rule_template.get("inputs") or []) if isinstance(item, dict)]):
        if not bool(spec.get("required", True)):
            continue
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        if name and _safe_snakemake_name(name) not in provided:
            raise RunPreflightError(f"TOOL_INPUT_REQUIRED: {name}")


def _preflight_exposed_outputs(run_spec: dict[str, Any], known_outputs: dict[str, set[str]]) -> None:
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    raw_outputs = workflow.get("outputs") or workflow.get("exposeOutputs")
    if raw_outputs in (None, {}, []):
        return
    if not isinstance(raw_outputs, (dict, list)):
        raise RunPreflightError("WORKFLOW_OUTPUT_BINDING_INVALID")
    items = raw_outputs.items() if isinstance(raw_outputs, dict) else enumerate(raw_outputs)
    for fallback_key, binding in items:
        if isinstance(binding, str):
            if "." not in binding:
                raise RunPreflightError("WORKFLOW_OUTPUT_BINDING_INVALID")
            step_id, output_name = binding.rsplit(".", 1)
        elif isinstance(binding, dict):
            step_id = str(binding.get("fromStep") or binding.get("step") or "").strip()
            output_name = str(binding.get("output") or binding.get("fromOutput") or "").strip()
            alias = str(binding.get("as") or binding.get("name") or fallback_key).strip()
            if not alias:
                raise RunPreflightError("WORKFLOW_OUTPUT_BINDING_INVALID")
        else:
            raise RunPreflightError("WORKFLOW_OUTPUT_BINDING_INVALID")
        normalized_step = _safe_identifier(step_id)
        if normalized_step not in known_outputs:
            raise RunPreflightError(f"WORKFLOW_OUTPUT_STEP_UNKNOWN: {step_id}")
        if output_name not in known_outputs[normalized_step]:
            raise RunPreflightError(f"WORKFLOW_OUTPUT_NAME_UNKNOWN: {step_id}.{output_name}")
