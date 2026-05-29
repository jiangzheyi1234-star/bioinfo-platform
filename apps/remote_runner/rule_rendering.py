from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from .rule_action import render_rule_action_lines, rule_action_kind
from .rule_outputs import render_rule_output_lines
from .rule_params import render_rule_param_lines
from .rule_runtime import RuleRuntimeDirectives, render_runtime_directives, runtime_command_replacements


def render_generated_workflow_snakefile(
    *,
    steps: list[Any],
    final_outputs: dict[str, str],
    output_dir: str,
    databases: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    resource_config: dict[str, str],
) -> str:
    workflow_targets = "".join(f"        {str(path)!r},\n" for path in final_outputs.values())
    rule_blocks = [
        _render_step_rule_block(
            step,
            output_dir=output_dir,
            databases=databases,
            resources=resources,
            resource_config=resource_config,
        )
        for step in steps
    ]
    return (
        'configfile: "run-config.json"\n\n'
        "rule all:\n"
        "    input:\n"
        f"{workflow_targets}\n"
        + "\n\n".join(rule_blocks)
    )


def _render_step_rule_block(
    step: Any,
    *,
    output_dir: str,
    databases: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    resource_config: dict[str, str],
) -> str:
    input_lines = "".join(f"        {_safe_snakemake_name(name)}={path!r},\n" for name, path in step.inputs.items())
    output_lines = render_rule_output_lines(step.outputs, step.rule_template)
    param_lines = render_rule_param_lines(step.params)
    runtime_lines = render_runtime_directives(step.runtime)
    if rule_action_kind(step.rule_template) == "module":
        return _render_module_use_rule_block(
            step=step,
            input_lines=input_lines,
            output_lines=output_lines,
            param_lines=param_lines,
            runtime_lines=runtime_lines,
        )
    command = (
        ""
        if rule_action_kind(step.rule_template) in {"wrapper", "script"}
        else _render_command(
            step.command_template,
            inputs=step.inputs,
            outputs=step.outputs,
            params=step.params,
            runtime=step.runtime,
            output_dir=output_dir,
            databases=databases,
            resources=resources,
            resource_config=resource_config,
        )
    )
    action_lines = render_rule_action_lines(
        rule_template=step.rule_template,
        env_path=step.env_path,
        output_dir=output_dir,
        runtime=step.runtime,
        shell_command=command,
    )
    return (
        f"rule {step.rule_name}:\n"
        "    input:\n"
        f"{input_lines}"
        "    output:\n"
        f"{output_lines}"
        f"{param_lines}"
        f"{runtime_lines}"
        f"{action_lines}"
    )


def _render_module_use_rule_block(
    *,
    step: Any,
    input_lines: str,
    output_lines: str,
    param_lines: str,
    runtime_lines: str,
) -> str:
    module = step.rule_template.get("module")
    if not isinstance(module, dict):
        raise ValueError("TOOL_RULE_MODULE_INVALID")
    module_name = _safe_snakemake_name(f"{step.rule_name}_module")
    module_rule = str(module.get("rule") or "").strip()
    snakefile = str(module.get("snakefile") or "").strip()
    if not module_rule or not snakefile:
        raise ValueError("TOOL_RULE_MODULE_INVALID")
    return (
        f"module {module_name}:\n"
        "    snakefile:\n"
        f"        {snakefile!r}\n\n"
        f"use rule {module_rule} from {module_name} as {step.rule_name} with:\n"
        "    input:\n"
        f"{input_lines}"
        "    output:\n"
        f"{output_lines}"
        f"{param_lines}"
        f"{runtime_lines}"
    )


def _render_command(
    command_template: str,
    *,
    inputs: dict[str, str],
    outputs: dict[str, Path],
    params: dict[str, Any],
    runtime: RuleRuntimeDirectives,
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
    for name, value in params.items():
        rendered = shlex.quote(str(value))
        replacements[f"{{params.{name}}}"] = rendered
        replacements[f"{{params.{name}:q}}"] = rendered
    replacements.update(runtime_command_replacements(runtime))
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


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "tool"


def _safe_snakemake_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name
