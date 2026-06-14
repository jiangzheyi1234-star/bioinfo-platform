"""Compiler/export boundary for WorkflowDesignDraft projects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
from typing import Any
import uuid

import yaml

from .capability_bundle_audit import capability_bundle_audit_for_tool
from .config import RemoteRunnerConfig
from .generated_workflow import GENERATED_TOOL_RUN_VERSION
from .generated_workflow_outputs import resolve_exposed_outputs
from .generated_workflow_plan import plan_generated_workflow_steps
from .rule_action import materialize_rule_assets
from .rule_environment import render_rule_conda_env_yaml
from .rule_outputs import SnakemakeExpression, output_spec_metadata, rule_output_metadata
from .rule_rendering import render_generated_workflow_snakefile
from .rule_runtime import runtime_config
from core.contracts.workflow_design import (
    WorkflowDesignDraftV1,
    workflow_design_graph,
    workflow_design_resolved_inputs,
    workflow_design_to_generated_run_spec,
)
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs


def compile_workflow_design_project(
    cfg: RemoteRunnerConfig,
    draft: dict[str, Any] | WorkflowDesignDraftV1,
    *,
    export_dir: Path,
    draft_id: str | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    design = WorkflowDesignDraftV1.model_validate(draft)
    resolved_inputs = workflow_design_resolved_inputs(design)
    if not resolved_inputs:
        raise ValueError("INPUT_REQUIRED")
    plan = plan_generated_workflow_steps(
        cfg,
        run_spec=workflow_design_to_generated_run_spec(design, draft_id=draft_id, revision=revision),
        resolved_inputs=resolved_inputs,
        result_dir=Path("results"),
        require_workflow_ready=True,
    )
    resource_config = build_workflow_resource_config(
        cfg,
        workflow_resource_spec=collect_workflow_resource_specs([step.rule_template for step in plan.steps]),
        bindings=design.resources.bindings,
    )
    exposed_outputs = resolve_exposed_outputs(
        workflow_spec=plan.workflow_spec,
        steps=plan.steps,
        outputs_by_step_id=plan.outputs_by_step_id,
    )
    final_outputs = {name: str(binding["path"]) for name, binding in exposed_outputs.items()}
    render_steps = [_step_for_rules_dir(step, exposed_outputs) for step in plan.steps]
    full_snakefile = render_generated_workflow_snakefile(
        steps=render_steps,
        final_outputs=final_outputs,
        output_dir="results",
        databases={},
        resources=resource_config["resources"],
        resource_config=resource_config["config"],
    )
    generated_rules = _extract_generated_rules(full_snakefile)
    config = _run_config(
        design=design,
        plan=plan,
        resolved_inputs=resolved_inputs,
        exposed_outputs=exposed_outputs,
        final_outputs=final_outputs,
        resource_config=resource_config,
        draft_id=draft_id,
        revision=revision,
    )

    staging_dir = export_dir.parent / f".{export_dir.name}.staging-{uuid.uuid4().hex}"
    workflow_dir = staging_dir / "workflow"
    rules_dir = workflow_dir / "rules"
    env_dir = workflow_dir / "envs"
    config_dir = staging_dir / "config"
    schema_dir = workflow_dir / "schemas"
    test_dir = staging_dir / ".test"
    try:
        for directory in (rules_dir, env_dir, schema_dir, config_dir, test_dir):
            directory.mkdir(parents=True, exist_ok=True)

        for step in plan.steps:
            package_spec = str(step.tool.get("packageSpec") or "").strip()
            (workflow_dir / step.env_path).write_text(
                render_rule_conda_env_yaml(
                    rule_template=step.rule_template,
                    source=str(step.tool.get("source") or ""),
                    package_spec=package_spec,
                ),
                encoding="utf-8",
            )
            materialize_rule_assets(rule_template=step.rule_template, workflow_dir=workflow_dir)

        (workflow_dir / "Snakefile").write_text(_snakefile_entry(final_outputs), encoding="utf-8")
        (rules_dir / "generated.smk").write_text(generated_rules, encoding="utf-8")
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        (schema_dir / "config.schema.yaml").write_text(yaml.safe_dump(_config_schema(), sort_keys=False), encoding="utf-8")
        (test_dir / "run-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        (staging_dir / "README.md").write_text(_readme(design, plan.steps, final_outputs), encoding="utf-8")
        _replace_generated_export_paths(staging_dir, export_dir)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

    return {
        "layout": {
            "snakefile": "workflow/Snakefile",
            "rules": "workflow/rules/generated.smk",
            "envs": [f"workflow/{step.env_path.as_posix()}" for step in plan.steps],
            "config": "config/config.yaml",
            "schema": "workflow/schemas/config.schema.yaml",
            "readme": "README.md",
            "testConfig": ".test/run-config.json",
        },
        "capabilityBundleAudit": [
            capability_bundle_audit_for_tool(step.tool, step_id=step.step_id)
            for step in plan.steps
        ],
        "runSpec": workflow_design_to_generated_run_spec(design, draft_id=draft_id, revision=revision),
    }


def _clear_generated_export_paths(export_dir: Path) -> None:
    for relative_path in ("workflow", "config", ".test", "README.md"):
        path = export_dir / relative_path
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _replace_generated_export_paths(staging_dir: Path, export_dir: Path) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated_export_paths(export_dir)
    for relative_path in ("workflow", "config", ".test", "README.md"):
        shutil.move(str(staging_dir / relative_path), str(export_dir / relative_path))


def _run_config(
    *,
    design: WorkflowDesignDraftV1,
    plan: Any,
    resolved_inputs: list[dict[str, str]],
    exposed_outputs: dict[str, dict[str, Any]],
    final_outputs: dict[str, str],
    resource_config: dict[str, dict[str, Any]],
    draft_id: str | None,
    revision: int | None,
) -> dict[str, Any]:
    return {
        "run_id": "compiled_workflow_design",
        "request_id": "compiled_workflow_design",
        "project_id": design.metadata.projectId,
        "pipeline_id": str(plan.run_spec.get("pipelineId") or ""),
        "pipeline_version": GENERATED_TOOL_RUN_VERSION,
        "params": {},
        "databases": resource_config["config"],
        "resources": resource_config["resources"],
        "resourceConfig": resource_config["config"],
        "inputs": resolved_inputs,
        "workflowDesign": _workflow_design_metadata(design, draft_id=draft_id, revision=revision),
        "workflow": {
            "graph": workflow_design_graph(design),
            "steps": [
                {
                    "id": step.step_id,
                    "rule": step.rule_name,
                    "tool": {
                        "id": step.tool_id,
                        "toolRevisionId": step.tool_revision_id,
                        "name": str(step.tool.get("name") or ""),
                        "source": str(step.tool.get("source") or ""),
                        "version": str(step.tool.get("version") or ""),
                        "packageSpec": str(step.tool.get("packageSpec") or ""),
                        "ruleTemplate": step.rule_template,
                        "capabilityBundle": capability_bundle_audit_for_tool(step.tool, step_id=step.step_id),
                    },
                    "inputs": step.inputs,
                    "outputs": {name: str(path) for name, path in step.outputs.items()},
                    "outputSpecs": rule_output_metadata(step.outputs, step.rule_template),
                    "params": step.params,
                    **runtime_config(step.runtime),
                }
                for step in plan.steps
            ],
            "outputs": {
                name: {
                    "step": str(binding["step"].step_id),
                    "output": str(binding["output"]),
                    "path": str(binding["path"]),
                    **output_spec_metadata(dict(binding.get("spec") or {})),
                }
                for name, binding in exposed_outputs.items()
            },
        },
        "outputs": final_outputs,
    }


def _snakefile_entry(final_outputs: dict[str, str]) -> str:
    targets = "".join(f"        {_safe_snakemake_name(name)}={_config_output_expression(name)},\n" for name in final_outputs)
    return (
        "from snakemake.utils import validate\n\n"
        'configfile: "run-config.json"\n\n'
        'validate(config, workflow.source_path("schemas/config.schema.yaml"))\n\n'
        'include: "rules/generated.smk"\n\n'
        "rule all:\n"
        "    input:\n"
        f"{targets}"
    )


def _step_for_rules_dir(step: Any, exposed_outputs: dict[str, dict[str, Any]]) -> Any:
    template = deepcopy(step.rule_template)
    script = str(template.get("script") or "").strip()
    if script:
        template["script"] = _parent_relative_path(script)
    module = template.get("module")
    if isinstance(module, dict) and str(module.get("snakefile") or "").strip():
        template["module"] = {
            **module,
            "snakefile": _parent_relative_path(str(module["snakefile"])),
        }
    output_aliases = {
        str(binding["output"]): alias
        for alias, binding in exposed_outputs.items()
        if str(binding["step"].step_id) == str(step.step_id)
    }
    outputs = {
        name: SnakemakeExpression(_config_output_expression(output_aliases[name]))
        if name in output_aliases
        else path
        for name, path in step.outputs.items()
    }
    return replace(step, rule_template=template, env_path=Path("..") / step.env_path, outputs=outputs)


def _parent_relative_path(value: str) -> str:
    path = value.replace("\\", "/")
    if Path(path).is_absolute() or path.startswith("../") or "://" in path:
        return path
    return f"../{path}"


def _extract_generated_rules(full_snakefile: str) -> str:
    rule_all = full_snakefile.find("\n\nrule all:")
    search_start = rule_all + len("\n\nrule all:") if rule_all >= 0 else 0
    markers = [
        position
        for marker in ("\n\nrule ", "\n\nmodule ", "\n\nuse rule ")
        for position in [full_snakefile.find(marker, search_start)]
        if position >= 0
    ]
    if not markers:
        raise ValueError("WORKFLOW_DESIGN_RULES_NOT_RENDERED")
    return full_snakefile[min(markers) + 2 :]


def _config_output_expression(alias: str) -> str:
    return f'config["outputs"][{json.dumps(alias)}]'


def _safe_snakemake_name(value: str) -> str:
    import re

    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if name in {"count", "index", "sort"}:
        return f"tool_{name}"
    if name[0].isdigit():
        return f"tool_{name}"
    return name


def _config_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["workflow", "outputs", "inputs"],
        "additionalProperties": True,
        "properties": {
            "workflow": {"type": "object"},
            "outputs": {"type": "object"},
            "inputs": {"type": "array"},
            "resources": {"type": "object"},
            "databases": {"type": "object"},
        },
    }


def _readme(
    design: WorkflowDesignDraftV1,
    steps: list[Any],
    final_outputs: dict[str, str],
) -> str:
    step_lines = "\n".join(f"- `{step.step_id}` uses `{step.tool_id}`" for step in steps)
    output_lines = "\n".join(f"- `{name}`: `{path}`" for name, path in final_outputs.items())
    return (
        f"# {design.metadata.name}\n\n"
        f"{design.metadata.description}\n\n"
        "## Steps\n\n"
        f"{step_lines}\n\n"
        "## Outputs\n\n"
        f"{output_lines}\n"
    )


def _workflow_design_metadata(
    design: WorkflowDesignDraftV1,
    *,
    draft_id: str | None,
    revision: int | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "contractVersion": design.contractVersion,
        "name": design.metadata.name,
    }
    if draft_id:
        metadata["draftId"] = draft_id
    if revision is not None:
        metadata["revision"] = revision
    return metadata
