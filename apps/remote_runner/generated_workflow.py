from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .config import RemoteRunnerConfig
from .storage import fetch_tool
from .tools import normalize_rule_template
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs


GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1"
GENERATED_TOOL_RUN_VERSION = "0.1.0"


@dataclass(frozen=True)
class GeneratedWorkflow:
    pipeline_id: str
    pipeline_version: str
    snakefile: Path
    config_path: Path
    outputs: dict[str, str]
    output_schema: dict[str, Any]


@dataclass(frozen=True)
class GeneratedWorkflowStep:
    step_id: str
    rule_name: str
    tool_id: str
    tool: dict[str, Any]
    rule_template: dict[str, Any]
    env_path: Path
    inputs: dict[str, str]
    outputs: dict[str, Path]
    command_template: str


def prepare_generated_tool_workflow(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    work_dir: Path,
    result_dir: Path,
) -> GeneratedWorkflow:
    if not resolved_inputs:
        raise ValueError("INPUT_REQUIRED")

    workflow_dir = work_dir / "workflow"
    env_dir = workflow_dir / "envs"
    env_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "run-config.json"
    snakefile = workflow_dir / "Snakefile"
    requested_steps = _resolve_requested_steps(run_spec)
    workflow_spec = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    if "database" in run_spec or "databases" in run_spec:
        raise ValueError("RESOURCE_BINDINGS_REQUIRED")
    resolved_databases: dict[str, dict[str, Any]] = {}
    workflow_resource_config: dict[str, Any] = {"resources": {}, "config": {}}
    generated_steps: list[GeneratedWorkflowStep] = []
    outputs_by_step_id: dict[str, dict[str, Path]] = {}

    for index, requested_step in enumerate(requested_steps):
        tool_request = _step_tool_request(requested_step)
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

        step_id = _step_id(requested_step, index)
        safe_tool_id = _safe_identifier(tool_id)
        safe_step_id = _safe_identifier(step_id)
        env_path = env_dir / (f"{safe_tool_id}.yaml" if len(requested_steps) == 1 else f"{safe_step_id}-{safe_tool_id}.yaml")
        rule_template = _resolve_rule_template(tool=tool, tool_request=tool_request)
        inputs = _resolve_step_inputs(
            requested_step=requested_step,
            rule_template=rule_template,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
            previous_outputs=generated_steps[-1].outputs if generated_steps else None,
        )
        outputs = _resolve_outputs(
            rule_template=rule_template,
            result_dir=result_dir,
            output_prefix=safe_step_id if len(requested_steps) > 1 else "",
        )
        env_path.write_text(
            _render_env_yaml(source=str(tool.get("source") or ""), package_spec=package_spec),
            encoding="utf-8",
        )
        generated_steps.append(
            GeneratedWorkflowStep(
                step_id=step_id,
                rule_name="run_tool" if len(requested_steps) == 1 else _safe_snakemake_name(f"step_{index + 1:02d}_{safe_step_id}"),
                tool_id=tool_id,
                tool=tool,
                rule_template=rule_template,
                env_path=Path("envs") / env_path.name,
                inputs=inputs,
                outputs=outputs,
                command_template=str(rule_template["commandTemplate"]),
            )
        )
        if step_id in outputs_by_step_id:
            raise ValueError(f"WORKFLOW_STEP_DUPLICATE: {step_id}")
        outputs_by_step_id[step_id] = outputs

    workflow_resource_config = build_workflow_resource_config(
        cfg,
        workflow_resource_spec=collect_workflow_resource_specs([step.rule_template for step in generated_steps]),
        bindings=dict(run_spec.get("resourceBindings") or {}),
    )
    databases_config = workflow_resource_config["config"]

    exposed_outputs = _resolve_exposed_outputs(
        workflow_spec=workflow_spec,
        steps=generated_steps,
        outputs_by_step_id=outputs_by_step_id,
    )
    final_outputs = {name: str(binding["path"]) for name, binding in exposed_outputs.items()}
    final_artifacts = _final_output_artifacts(exposed_outputs)

    config_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "request_id": request_id,
                "project_id": str(run_spec.get("projectId") or "proj_default"),
                "pipeline_id": GENERATED_TOOL_RUN_PIPELINE_ID,
                "pipeline_version": GENERATED_TOOL_RUN_VERSION,
                "params": dict(run_spec.get("params") or {}),
                "databases": databases_config,
                "resources": workflow_resource_config["resources"],
                "resourceConfig": workflow_resource_config["config"],
                "inputs": resolved_inputs,
                "tool": _config_tool(generated_steps[0]),
                "workflow": {
                    "steps": [
                        {
                            "id": step.step_id,
                            "rule": step.rule_name,
                            "tool": _config_tool(step),
                            "inputs": step.inputs,
                            "outputs": {name: str(path) for name, path in step.outputs.items()},
                        }
                        for step in generated_steps
                    ],
                    "outputs": {
                        name: {
                            "step": str(binding["step"].step_id),
                            "output": str(binding["output"]),
                            "path": str(binding["path"]),
                        }
                        for name, binding in exposed_outputs.items()
                    },
                },
                "outputs": final_outputs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    snakefile.write_text(
        _render_snakefile(
            steps=generated_steps,
            final_outputs=final_outputs,
            output_dir=str(result_dir),
            databases=resolved_databases,
            resources=workflow_resource_config["resources"],
            resource_config=workflow_resource_config["config"],
        ),
        encoding="utf-8",
    )
    return GeneratedWorkflow(
        pipeline_id=GENERATED_TOOL_RUN_PIPELINE_ID,
        pipeline_version=GENERATED_TOOL_RUN_VERSION,
        snakefile=snakefile,
        config_path=config_path,
        outputs=final_outputs,
        output_schema={"type": "object", "artifacts": final_artifacts},
    )


def _resolve_requested_steps(run_spec: dict[str, Any]) -> list[dict[str, Any]]:
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


def _step_tool_request(step: dict[str, Any]) -> dict[str, Any]:
    tool_request = step.get("tool")
    if isinstance(tool_request, dict):
        return tool_request
    return step


def _step_id(step: dict[str, Any], index: int) -> str:
    return _safe_identifier(str(step.get("id") or step.get("name") or f"step_{index + 1}"))


def _config_tool(step: GeneratedWorkflowStep) -> dict[str, Any]:
    package_spec = str(step.tool.get("packageSpec") or "")
    return {
        "id": step.tool_id,
        "name": str(step.tool.get("name") or ""),
        "source": str(step.tool.get("source") or ""),
        "version": str(step.tool.get("version") or ""),
        "packageSpec": package_spec,
        "capabilities": list(step.tool.get("capabilities") or []),
        "ruleTemplate": step.rule_template,
    }


def _resolve_rule_template(*, tool: dict[str, Any], tool_request: dict[str, Any]) -> dict[str, Any]:
    manifest_template = tool.get("ruleTemplate")
    if isinstance(manifest_template, dict) and manifest_template.get("commandTemplate"):
        return normalize_rule_template(manifest_template, required=True)
    request_template = tool_request.get("ruleTemplate")
    if isinstance(request_template, dict) and request_template.get("commandTemplate"):
        return normalize_rule_template(request_template, required=True)
    raise ValueError("TOOL_RULE_TEMPLATE_REQUIRED")


def _resolve_step_inputs(
    *,
    requested_step: dict[str, Any],
    rule_template: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
    previous_outputs: dict[str, Path] | None,
) -> dict[str, str]:
    explicit_inputs = requested_step.get("inputs")
    if explicit_inputs is not None:
        return _resolve_explicit_step_inputs(
            explicit_inputs,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
        )
    if previous_outputs is None:
        return _resolve_inputs(rule_template=rule_template, resolved_inputs=resolved_inputs)
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
    return mapped


def _resolve_explicit_step_inputs(
    raw: Any,
    *,
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("WORKFLOW_STEP_INPUTS_INVALID")
    mapped: dict[str, str] = {}
    for name, binding in raw.items():
        input_name = _safe_snakemake_name(str(name or ""))
        if not input_name:
            raise ValueError("WORKFLOW_STEP_INPUT_NAME_REQUIRED")
        mapped[input_name] = _resolve_input_binding(
            binding,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
        )
    return mapped


def _resolve_input_binding(
    binding: Any,
    *,
    resolved_inputs: list[dict[str, Any]],
    outputs_by_step_id: dict[str, dict[str, Path]],
) -> str:
    if isinstance(binding, str):
        return binding
    if not isinstance(binding, dict):
        raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")
    from_step = str(binding.get("fromStep") or binding.get("step") or "").strip()
    if from_step:
        step_outputs = outputs_by_step_id.get(_safe_identifier(from_step))
        if step_outputs is None:
            raise ValueError(f"WORKFLOW_STEP_INPUT_STEP_UNKNOWN: {from_step}")
        output_name = str(binding.get("output") or binding.get("fromOutput") or "tool_output").strip()
        if output_name not in step_outputs:
            raise ValueError(f"WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN: {from_step}.{output_name}")
        return str(step_outputs[output_name])
    if "fromUpload" in binding:
        index = int(binding.get("fromUpload") or 0)
        if index < 0 or index >= len(resolved_inputs):
            raise ValueError(f"WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: {index}")
        return str(resolved_inputs[index]["path"])
    role = str(binding.get("fromInput") or binding.get("role") or "").strip()
    if role:
        for item in resolved_inputs:
            if str(item.get("role") or "").strip() == role:
                return str(item["path"])
        raise ValueError(f"WORKFLOW_STEP_INPUT_ROLE_UNKNOWN: {role}")
    raise ValueError("WORKFLOW_STEP_INPUT_BINDING_INVALID")


def _resolve_inputs(*, rule_template: dict[str, Any], resolved_inputs: list[dict[str, Any]]) -> dict[str, str]:
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
    return mapped


def _resolve_outputs(*, rule_template: dict[str, Any], result_dir: Path, output_prefix: str = "") -> dict[str, Path]:
    specs = [item for item in (rule_template.get("outputs") or []) if isinstance(item, dict)]
    if not specs:
        raise ValueError("TOOL_OUTPUTS_REQUIRED")
    outputs: dict[str, Path] = {}
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("tool_output" if index == 0 else f"output_{index + 1}")).strip()
        requested_path = str(spec.get("path") or "").strip()
        if not requested_path:
            raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
        path = _safe_relative_output_path(requested_path)
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


def _resolve_exposed_outputs(
    *,
    workflow_spec: dict[str, Any],
    steps: list[GeneratedWorkflowStep],
    outputs_by_step_id: dict[str, dict[str, Path]],
) -> dict[str, dict[str, Any]]:
    raw = workflow_spec.get("outputs") or workflow_spec.get("exposeOutputs")
    if raw in (None, {}, []):
        last_step = steps[-1]
        return {
            name: {"step": last_step, "output": name, "path": path, "spec": _output_spec(last_step, name)}
            for name, path in last_step.outputs.items()
        }
    items = raw.items() if isinstance(raw, dict) else enumerate(raw)
    exposed: dict[str, dict[str, Any]] = {}
    for fallback_key, binding in items:
        if isinstance(binding, str):
            step_id, output_name = _split_output_ref(binding)
            alias = str(fallback_key)
        elif isinstance(binding, dict):
            step_id = str(binding.get("fromStep") or binding.get("step") or "").strip()
            output_name = str(binding.get("output") or binding.get("fromOutput") or "").strip()
            alias = str(binding.get("as") or binding.get("name") or fallback_key).strip()
        else:
            raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
        if not step_id or not output_name or not alias:
            raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
        step = next((item for item in steps if item.step_id == _safe_identifier(step_id)), None)
        step_outputs = outputs_by_step_id.get(_safe_identifier(step_id))
        if step is None or step_outputs is None:
            raise ValueError(f"WORKFLOW_OUTPUT_STEP_UNKNOWN: {step_id}")
        if output_name not in step_outputs:
            raise ValueError(f"WORKFLOW_OUTPUT_NAME_UNKNOWN: {step_id}.{output_name}")
        exposed[alias] = {
            "step": step,
            "output": output_name,
            "path": step_outputs[output_name],
            "spec": _output_spec(step, output_name),
        }
    if not exposed:
        raise ValueError("WORKFLOW_OUTPUTS_REQUIRED")
    return exposed


def _split_output_ref(value: str) -> tuple[str, str]:
    if "." not in value:
        raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
    step_id, output_name = value.rsplit(".", 1)
    return step_id, output_name


def _output_spec(step: GeneratedWorkflowStep, output_name: str) -> dict[str, Any]:
    for spec in [item for item in (step.rule_template.get("outputs") or []) if isinstance(item, dict)]:
        if str(spec.get("name") or "") == output_name:
            return spec
    return {}


def _final_output_artifacts(outputs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for key, binding in outputs.items():
        spec = dict(binding.get("spec") or {})
        name = Path(str(binding["path"])).name
        artifacts.append(
            {
                "key": key,
                "name": name,
                "kind": str(spec.get("kind") or ""),
                "mimeType": str(spec.get("mimeType") or ""),
            }
        )
    return artifacts


def _render_snakefile(
    *,
    steps: list[GeneratedWorkflowStep],
    final_outputs: dict[str, str],
    output_dir: str,
    databases: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    resource_config: dict[str, str],
) -> str:
    workflow_targets = "".join(f"        {str(path)!r},\n" for path in final_outputs.values())
    rule_blocks = []
    for step in steps:
        command = _render_command(
            step.command_template,
            inputs=step.inputs,
            outputs=step.outputs,
            output_dir=output_dir,
            databases=databases,
            resources=resources,
            resource_config=resource_config,
        )
        input_lines = "".join(f"        {_safe_snakemake_name(name)}={path!r},\n" for name, path in step.inputs.items())
        output_lines = "".join(f"        {_safe_snakemake_name(name)}={str(path)!r},\n" for name, path in step.outputs.items())
        rule_blocks.append(
            f"rule {step.rule_name}:\n"
            "    input:\n"
            f"{input_lines}"
            "    output:\n"
            f"{output_lines}"
            "    conda:\n"
            f"        {step.env_path.as_posix()!r}\n"
            "    shell:\n"
            "        r\"\"\"\n"
            "        set -euo pipefail\n"
            f"        mkdir -p {shlex.quote(output_dir)}\n"
            f"        {command}\n"
            "        \"\"\"\n"
        )
    return (
        'configfile: "run-config.json"\n\n'
        "rule all:\n"
        "    input:\n"
        f"{workflow_targets}\n"
        + "\n\n".join(rule_blocks)
    )


def _render_command(
    command_template: str,
    *,
    inputs: dict[str, str],
    outputs: dict[str, Path],
    output_dir: str,
    databases: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    resource_config: dict[str, str],
) -> str:
    if "{resource." in command_template:
        raise ValueError("WORKFLOW_RESOURCE_DIRECT_TOKEN_UNSUPPORTED")
    primary_input = inputs.get("primary") or next(iter(inputs.values()))
    primary_output = outputs.get("tool_output") or next(iter(outputs.values()))
    replacements = {
        "{input}": shlex.quote(primary_input),
        "{input:q}": shlex.quote(primary_input),
        "{output}": shlex.quote(str(primary_output)),
        "{output:q}": shlex.quote(str(primary_output)),
        "{output_dir}": shlex.quote(output_dir),
        "{output_dir:q}": shlex.quote(output_dir),
    }
    for name, path in inputs.items():
        replacements[f"{{input.{name}}}"] = shlex.quote(path)
        replacements[f"{{input.{name}:q}}"] = shlex.quote(path)
    for name, path in outputs.items():
        replacements[f"{{output.{name}}}"] = shlex.quote(str(path))
        replacements[f"{{output.{name}:q}}"] = shlex.quote(str(path))
    for role, database in databases.items():
        safe_role = _safe_identifier(role)
        for key in ["id", "name", "type", "templateId", "version", "path", "manifestPath", "checksum"]:
            value = str(database.get(key) or "")
            replacements[f"{{database.{role}.{key}}}"] = shlex.quote(value)
            replacements[f"{{database.{role}.{key}:q}}"] = shlex.quote(value)
            replacements[f"{{database.{safe_role}.{key}}}"] = shlex.quote(value)
            replacements[f"{{database.{safe_role}.{key}:q}}"] = shlex.quote(value)
    for resource_key, resource in resources.items():
        safe_key = _safe_identifier(resource_key)
        for key in ["resourceKey", "databaseId", "name", "type", "templateId", "templateLabel", "version", "path", "configKey"]:
            value = str(resource.get(key) or "")
            replacements[f"{{resource.{resource_key}.{key}}}"] = shlex.quote(value)
            replacements[f"{{resource.{resource_key}.{key}:q}}"] = shlex.quote(value)
            replacements[f"{{resource.{safe_key}.{key}}}"] = shlex.quote(value)
            replacements[f"{{resource.{safe_key}.{key}:q}}"] = shlex.quote(value)
    for key, value in resource_config.items():
        safe_key = _safe_identifier(key)
        replacements[f"{{config.{key}}}"] = f"{{config[databases][{key}]}}"
        replacements[f"{{config.{key}:q}}"] = f"{{config[databases][{key}]:q}}"
        replacements[f"{{config.{safe_key}}}"] = f"{{config[databases][{key}]}}"
        replacements[f"{{config.{safe_key}:q}}"] = f"{{config[databases][{key}]:q}}"
    command = command_template
    for token, value in replacements.items():
        command = command.replace(token, value)
    return command


def _render_env_yaml(*, source: str, package_spec: str) -> str:
    channels = _channels_for_source(source)
    channel_lines = "".join(f"  - {channel}\n" for channel in [*channels, "nodefaults"])
    return (
        "channels:\n"
        f"{channel_lines}"
        "dependencies:\n"
        f"  - {json.dumps(package_spec)}\n"
    )


def _channels_for_source(source: str) -> list[str]:
    if source == "bioconda":
        return ["conda-forge", "bioconda"]
    if source == "conda-forge":
        return ["conda-forge", "bioconda"]
    return ["conda-forge", "bioconda"]


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name


def _safe_output_name(value: str) -> str:
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
    return name


def _safe_relative_output_path(value: str) -> Path:
    posix_path = PurePosixPath(value.replace("\\", "/"))
    if (
        Path(value).is_absolute()
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise ValueError("TOOL_OUTPUT_PATH_INVALID")
    parts = [_safe_output_name(part) for part in posix_path.parts]
    if not parts:
        raise ValueError("TOOL_OUTPUT_PATH_REQUIRED")
    return Path(*parts)
