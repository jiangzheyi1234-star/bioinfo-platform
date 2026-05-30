from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .config import RemoteRunnerConfig
from .generated_workflow_graph import normalize_generated_workflow_run_spec
from .rule_command import command_param_names, validate_command_input_tokens_bound
from .rule_ports import build_output_port_specs, validate_input_binding_compatibility
from .rule_outputs import validate_exposed_output_spec
from .rule_runtime import RuleRuntimeDirectives, resolve_rule_runtime_directives
from .rule_templates import rule_template_candidate_entries
from .storage import fetch_tool
from .tools import normalize_rule_template


@dataclass(frozen=True)
class GeneratedWorkflowStepPlan:
    step_id: str
    rule_name: str
    tool_id: str
    tool: dict[str, Any]
    rule_template: dict[str, Any]
    rule_spec_draft: dict[str, Any]
    env_path: Path
    inputs: dict[str, str]
    outputs: dict[str, Path]
    params: dict[str, Any]
    runtime: RuleRuntimeDirectives
    command_template: str


@dataclass(frozen=True)
class GeneratedWorkflowPlan:
    run_spec: dict[str, Any]
    workflow_spec: dict[str, Any]
    steps: list[GeneratedWorkflowStepPlan]
    outputs_by_step_id: dict[str, dict[str, Path]]


def plan_generated_workflow_steps(
    cfg: RemoteRunnerConfig,
    *,
    run_spec: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    result_dir: Path,
    require_workflow_ready: bool = True,
    resolve_implicit_inputs: bool = True,
) -> GeneratedWorkflowPlan:
    run_spec = normalize_generated_workflow_run_spec(run_spec)
    requested_steps = topologically_order_steps(resolve_requested_steps(run_spec))
    workflow_spec = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    generated_steps: list[GeneratedWorkflowStepPlan] = []
    outputs_by_step_id: dict[str, dict[str, Path]] = {}
    output_port_specs_by_step_id: dict[str, dict[str, dict[str, str]]] = {}

    for index, requested_step in enumerate(requested_steps):
        tool_request = step_tool_request(requested_step)
        tool_id = str(tool_request.get("id") or tool_request.get("toolId") or "").strip()
        if not tool_id:
            raise ValueError("TOOL_ID_REQUIRED")
        tool = fetch_tool(cfg, tool_id)
        if tool is None:
            raise ValueError("TOOL_NOT_FOUND")
        if not bool(tool.get("targetPlatformSupported")):
            raise ValueError("TOOL_PLATFORM_UNSUPPORTED")
        package_spec = str(tool.get("packageSpec") or "").strip()
        if not package_spec:
            raise ValueError("TOOL_PACKAGE_SPEC_REQUIRED")
        if require_workflow_ready:
            validate_tool_workflow_ready(tool)

        step_id = step_id_from_request(requested_step)
        safe_tool_id = safe_identifier(tool_id)
        safe_step_id = safe_identifier(step_id)
        single_step = len(requested_steps) == 1
        env_path = Path("envs") / (f"{safe_tool_id}.yaml" if single_step else f"{safe_step_id}-{safe_tool_id}.yaml")
        rule_template, rule_spec_draft = resolve_rule_contract(tool=tool, tool_request=tool_request)
        params = resolve_step_params(
            rule_template=rule_template,
            requested_step=requested_step,
            tool_request=tool_request,
            run_spec=run_spec,
            single_step=single_step,
        )
        output_prefix = safe_step_id if not single_step else ""
        inputs = resolve_step_inputs(
            step_id=step_id,
            requested_step=requested_step,
            rule_template=rule_template,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
            output_port_specs_by_step_id=output_port_specs_by_step_id,
            previous_outputs=generated_steps[-1].outputs if generated_steps else None,
            resolve_implicit_inputs=resolve_implicit_inputs,
        )
        outputs = resolve_outputs(
            rule_template=rule_template,
            result_dir=result_dir,
            output_prefix=output_prefix,
        )
        runtime = resolve_rule_runtime_directives(
            rule_template=rule_template,
            requested_step=requested_step,
            result_dir=result_dir,
            output_prefix=output_prefix,
        )
        generated_steps.append(
            GeneratedWorkflowStepPlan(
                step_id=step_id,
                rule_name="run_tool" if single_step else safe_snakemake_name(f"step_{index + 1:02d}_{safe_step_id}"),
                tool_id=tool_id,
                tool=tool,
                rule_template=rule_template,
                rule_spec_draft=rule_spec_draft,
                env_path=env_path,
                inputs=inputs,
                outputs=outputs,
                params=params,
                runtime=runtime,
                command_template=str(rule_template.get("commandTemplate") or ""),
            )
        )
        if step_id in outputs_by_step_id:
            raise ValueError(f"WORKFLOW_STEP_DUPLICATE: {step_id}")
        outputs_by_step_id[step_id] = outputs
        output_port_specs_by_step_id[step_id] = build_output_port_specs(rule_template)

    return GeneratedWorkflowPlan(
        run_spec=run_spec,
        workflow_spec=workflow_spec,
        steps=generated_steps,
        outputs_by_step_id=outputs_by_step_id,
    )


def validate_tool_workflow_ready(tool: dict[str, Any]) -> None:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    if bool(contract.get("workflowReady")):
        return
    state = str(contract.get("state") or "AddedDependency")
    raise ValueError(f"WORKFLOW_TOOL_NOT_READY: {state}")


def resolve_requested_steps(run_spec: dict[str, Any]) -> list[dict[str, Any]]:
    run_spec = normalize_generated_workflow_run_spec(run_spec)
    workflow = run_spec.get("workflow")
    if isinstance(workflow, dict):
        steps = workflow.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("WORKFLOW_STEPS_REQUIRED")
        if any(not isinstance(step, dict) for step in steps):
            raise ValueError("WORKFLOW_STEP_INVALID")
        return steps
    tool_request = run_spec.get("tool")
    if not isinstance(tool_request, dict):
        raise ValueError("TOOL_REQUIRED")
    return [{"id": "run_tool", "tool": tool_request}]


def topologically_order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(steps) <= 1:
        return steps
    step_ids = [step_id_from_request(step) for step in steps]
    step_by_id: dict[str, dict[str, Any]] = {}
    index_by_id: dict[str, int] = {}
    for index, (step_id, step) in enumerate(zip(step_ids, steps, strict=True)):
        if step_id in step_by_id:
            raise ValueError(f"WORKFLOW_STEP_DUPLICATE: {step_id}")
        step_by_id[step_id] = step
        index_by_id[step_id] = index

    dependencies: dict[str, set[str]] = {step_id: set() for step_id in step_ids}
    dependents: dict[str, set[str]] = {step_id: set() for step_id in step_ids}
    for step_id, step in zip(step_ids, steps, strict=True):
        for raw_step_id, dependency_id in step_input_dependencies(step):
            if dependency_id not in step_by_id:
                raise ValueError(f"WORKFLOW_STEP_INPUT_STEP_UNKNOWN: {raw_step_id}")
            dependencies[step_id].add(dependency_id)
            dependents[dependency_id].add(step_id)

    ready = sorted((step_id for step_id, deps in dependencies.items() if not deps), key=index_by_id.__getitem__)
    ordered_ids: list[str] = []
    while ready:
        step_id = ready.pop(0)
        ordered_ids.append(step_id)
        for dependent_id in sorted(dependents[step_id], key=index_by_id.__getitem__):
            dependencies[dependent_id].discard(step_id)
            if not dependencies[dependent_id] and dependent_id not in ordered_ids and dependent_id not in ready:
                ready.append(dependent_id)
        ready.sort(key=index_by_id.__getitem__)

    if len(ordered_ids) != len(steps):
        cycle_ids = [step_id for step_id in step_ids if dependencies[step_id]]
        raise ValueError(f"WORKFLOW_STEP_CYCLE: {', '.join(cycle_ids)}")
    return [step_by_id[step_id] for step_id in ordered_ids]


def step_input_dependencies(step: dict[str, Any]) -> list[tuple[str, str]]:
    raw_inputs = step.get("inputs")
    if not isinstance(raw_inputs, dict):
        return []
    dependencies: list[tuple[str, str]] = []
    for binding in raw_inputs.values():
        if not isinstance(binding, dict):
            continue
        from_step = str(binding.get("fromStep") or "").strip()
        if from_step:
            dependencies.append((from_step, safe_identifier(from_step)))
    return dependencies


def step_tool_request(step: dict[str, Any]) -> dict[str, Any]:
    tool_request = step.get("tool")
    if isinstance(tool_request, dict):
        return tool_request
    raise ValueError("TOOL_REQUIRED")


def step_id_from_request(step: dict[str, Any]) -> str:
    raw_id = str(step.get("id") or "").strip()
    if not raw_id:
        raise ValueError("WORKFLOW_STEP_ID_REQUIRED")
    return safe_identifier(raw_id)


def resolve_rule_template(*, tool: dict[str, Any], tool_request: dict[str, Any]) -> dict[str, Any]:
    return resolve_rule_contract(tool=tool, tool_request=tool_request)[0]


def resolve_rule_contract(
    *,
    tool: dict[str, Any],
    tool_request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    for candidate in rule_template_candidate_entries(tool, tool_request):
        rule_template = normalize_rule_template(candidate["template"], required=True)
        draft = candidate.get("ruleSpecDraft")
        return rule_template, dict(draft) if isinstance(draft, dict) and draft else {}
    raise ValueError("TOOL_RULE_TEMPLATE_REQUIRED")


_MISSING = object()


def resolve_step_params(
    *,
    rule_template: dict[str, Any],
    requested_step: dict[str, Any],
    tool_request: dict[str, Any],
    run_spec: dict[str, Any],
    single_step: bool,
) -> dict[str, Any]:
    declared = declared_rule_params(rule_template)
    resolved = {name: value for name, value in declared.items() if value is not _MISSING}
    if single_step and "params" in run_spec:
        resolved.update(validate_step_params(run_spec.get("params"), declared))
    if "params" in tool_request:
        resolved.update(validate_step_params(tool_request.get("params"), declared))
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
    previous_outputs: dict[str, Path] | None,
    resolve_implicit_inputs: bool,
) -> dict[str, str]:
    explicit_inputs = requested_step.get("inputs")
    if explicit_inputs is not None:
        mapped = resolve_explicit_step_inputs(
            explicit_inputs,
            step_id=step_id,
            rule_template=rule_template,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
            output_port_specs_by_step_id=output_port_specs_by_step_id,
        )
        validate_required_step_inputs(rule_template=rule_template, inputs=mapped)
        validate_command_input_tokens_bound(rule_template=rule_template, inputs=mapped)
        return mapped
    if not resolve_implicit_inputs:
        return {}
    if previous_outputs is None:
        return resolve_inputs(rule_template=rule_template, resolved_inputs=resolved_inputs)
    specs = [item for item in (rule_template.get("inputs") or []) if isinstance(item, dict)]
    if not specs:
        specs = [{"name": "primary"}]
    primary_upstream = previous_outputs.get("tool_output") or next(iter(previous_outputs.values()))
    mapped: dict[str, str] = {}
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        source_output = str(spec.get("sourceOutput") or "").strip()
        if source_output and source_output in previous_outputs:
            mapped[name] = str(previous_outputs[source_output])
            continue
        if name in previous_outputs:
            mapped[name] = str(previous_outputs[name])
            continue
        if index == 0 or name == "primary":
            mapped[name] = str(primary_upstream)
            continue
        if bool(spec.get("required", True)):
            raise ValueError("TOOL_INPUT_REQUIRED")
    if "primary" not in mapped and primary_upstream:
        mapped["primary"] = str(primary_upstream)
    if not mapped:
        raise ValueError("TOOL_INPUT_REQUIRED")
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
    if not isinstance(raw, dict) or not raw:
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
        raw_index = binding.get("fromUpload")
        try:
            index = int(raw_index or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {raw_index}") from exc
        if index < 0 or index >= len(resolved_inputs):
            raise ValueError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {index}")
        return str(resolved_inputs[index].get("path") or f"input_{index + 1}")
    if "fromInput" in binding:
        role = str(binding.get("fromInput") or "").strip()
        if not role:
            raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
        for index, item in enumerate(resolved_inputs):
            item_role = str(item.get("role") or ("input" if index == 0 else f"input_{index + 1}")).strip()
            if item_role == role:
                return str(item.get("path") or f"input_{index + 1}")
        raise ValueError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {role}")
    raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")


def resolve_inputs(*, rule_template: dict[str, Any], resolved_inputs: list[dict[str, Any]]) -> dict[str, str]:
    specs = [item for item in (rule_template.get("inputs") or []) if isinstance(item, dict)]
    if not specs:
        specs = [{"name": "primary"}]
    mapped: dict[str, str] = {}
    for index, spec in enumerate(specs):
        if index >= len(resolved_inputs):
            if bool(spec.get("required", True)):
                raise ValueError("TOOL_INPUT_REQUIRED")
            continue
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        mapped[name] = str(resolved_inputs[index]["path"])
    if "primary" not in mapped and resolved_inputs:
        mapped["primary"] = str(resolved_inputs[0]["path"])
    if not mapped:
        raise ValueError("TOOL_INPUT_REQUIRED")
    validate_command_input_tokens_bound(rule_template=rule_template, inputs=mapped)
    return mapped


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


def resolve_exposed_outputs(
    *,
    workflow_spec: dict[str, Any],
    steps: list[GeneratedWorkflowStepPlan],
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
        step_id = str(binding.get("fromStep") or binding.get("step") or "").strip()
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
        return [dict(binding) for binding in raw]
    if isinstance(raw, dict):
        bindings: list[dict[str, Any]] = []
        for alias, binding in raw.items():
            if not isinstance(binding, dict):
                raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
            bindings.append(
                {
                    "fromStep": str(binding.get("fromStep") or binding.get("step") or "").strip(),
                    "output": str(binding.get("output") or "").strip(),
                    "as": str(binding.get("as") or alias or "").strip(),
                }
            )
        return bindings
    raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")


def output_spec(step: GeneratedWorkflowStepPlan, output_name: str) -> dict[str, Any]:
    for spec in [item for item in (step.rule_template.get("outputs") or []) if isinstance(item, dict)]:
        if str(spec.get("name") or "") == output_name:
            return spec
    return {}


def safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"


def safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name


def safe_relative_output_path(value: str) -> Path:
    posix_path = PurePosixPath(value.replace("\\", "/"))
    parts = list(posix_path.parts)
    if Path(value).is_absolute() or posix_path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("TOOL_OUTPUT_PATH_INVALID")
    if not parts:
        raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
    return Path(*parts)
