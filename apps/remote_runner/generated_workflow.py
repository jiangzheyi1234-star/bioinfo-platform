from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capability_bundle_audit import capability_bundle_audit_for_tool
from .config import RemoteRunnerConfig
from .generated_workflow_constants import GENERATED_TOOL_RUN_PIPELINE_ID
from .generated_workflow_graph import workflow_graph_config
from .generated_workflow_outputs import resolve_exposed_outputs
from .generated_workflow_plan import (
    GeneratedWorkflowStepPlan,
    plan_generated_workflow_steps,
)
from .rule_action import materialize_rule_assets
from .rule_environment import render_rule_conda_env_yaml
from .rule_outputs import output_artifact_flags, output_spec_metadata, rule_output_metadata
from .rule_rendering import render_generated_workflow_snakefile
from .rule_runtime import runtime_config
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs

GENERATED_TOOL_RUN_VERSION = "0.1.0"


@dataclass(frozen=True)
class GeneratedWorkflow:
    pipeline_id: str
    pipeline_version: str
    snakefile: Path
    config_path: Path
    outputs: dict[str, str]
    output_schema: dict[str, Any]


def prepare_generated_tool_workflow(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    work_dir: Path,
    result_dir: Path,
    require_workflow_ready: bool = True,
    tool_overrides: dict[str, dict[str, Any]] | None = None,
) -> GeneratedWorkflow:
    if not resolved_inputs:
        raise ValueError("INPUT_REQUIRED")
    graph_config = workflow_graph_config(run_spec.get("workflow"))

    workflow_dir = work_dir / "workflow"
    env_dir = workflow_dir / "envs"
    env_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "run-config.json"
    snakefile = workflow_dir / "Snakefile"
    if "database" in run_spec or "databases" in run_spec:
        raise ValueError("RESOURCE_BINDINGS_REQUIRED")
    resolved_databases: dict[str, dict[str, Any]] = {}
    workflow_resource_config: dict[str, Any] = {"resources": {}, "config": {}}
    plan = plan_generated_workflow_steps(
        cfg,
        run_spec=run_spec,
        resolved_inputs=resolved_inputs,
        result_dir=result_dir,
        require_workflow_ready=require_workflow_ready,
        tool_overrides=tool_overrides,
    )
    run_spec = plan.run_spec
    generated_steps = plan.steps

    for step in generated_steps:
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

    workflow_resource_config = build_workflow_resource_config(
        cfg,
        workflow_resource_spec=collect_workflow_resource_specs([step.rule_template for step in generated_steps]),
        bindings=dict(run_spec.get("resourceBindings") or {}),
    )
    databases_config = workflow_resource_config["config"]

    exposed_outputs = resolve_exposed_outputs(
        workflow_spec=plan.workflow_spec,
        steps=generated_steps,
        outputs_by_step_id=plan.outputs_by_step_id,
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
                    **({"graph": graph_config} if graph_config else {}),
                    "steps": [
                        {
                            "id": step.step_id,
                            "rule": step.rule_name,
                            "tool": _config_tool(step),
                            "inputs": step.inputs,
                            "outputs": {name: str(path) for name, path in step.outputs.items()},
                            "outputSpecs": rule_output_metadata(step.outputs, step.rule_template),
                            "params": step.params,
                            **runtime_config(step.runtime),
                        }
                        for step in generated_steps
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    snakefile.write_text(
        render_generated_workflow_snakefile(
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


def _config_tool(step: GeneratedWorkflowStepPlan) -> dict[str, Any]:
    package_spec = str(step.tool.get("packageSpec") or "")
    capability_audit = capability_bundle_audit_for_tool(step.tool, step_id=step.step_id)
    config = {
        "id": step.tool_id,
        "toolRevisionId": step.tool_revision_id,
        "revision": int(step.tool.get("revision") or 0),
        "name": str(step.tool.get("name") or ""),
        "source": str(step.tool.get("source") or ""),
        "version": str(step.tool.get("version") or ""),
        "packageSpec": package_spec,
        "capabilities": list(step.tool.get("capabilities") or []),
        "ruleTemplate": step.rule_template,
        "capabilityBundle": capability_audit,
    }
    rule_spec_draft = step.rule_spec_draft
    if rule_spec_draft:
        config["ruleSpecDraft"] = rule_spec_draft
        provenance = _config_rule_provenance(rule_spec_draft, step.rule_template, package_spec)
        if provenance:
            config["ruleProvenance"] = provenance
    return config


def _config_rule_provenance(
    rule_spec_draft: dict[str, Any],
    rule_template: dict[str, Any],
    package_spec: str,
) -> dict[str, str]:
    lock = rule_spec_draft.get("lock") if isinstance(rule_spec_draft.get("lock"), dict) else {}
    provenance = {
        "source": str(rule_spec_draft.get("source") or rule_template.get("source") or "").strip(),
        "lockType": str(lock.get("type") or "").strip(),
        "wrapperRef": str(lock.get("wrapperRef") or "").strip(),
        "wrapperPath": str(lock.get("wrapperPath") or "").strip(),
        "wrapperIdentifier": str(lock.get("wrapperIdentifier") or rule_template.get("wrapper") or "").strip(),
        "version": str(lock.get("version") or "").strip(),
    }
    locked_package_spec = str(lock.get("packageSpec") or "").strip()
    if locked_package_spec:
        provenance["packageSpec"] = locked_package_spec
    elif package_spec:
        provenance["declaredPackageSpec"] = package_spec
    return {key: value for key, value in provenance.items() if value}


def _final_output_artifacts(outputs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    artifacts: list[dict[str, Any]] = []
    for key, binding in outputs.items():
        spec = dict(binding.get("spec") or {})
        name = Path(str(binding["path"])).name
        artifacts.append(
            {
                "key": key,
                "name": name,
                "kind": str(spec.get("kind") or "file"),
                "mimeType": str(spec.get("mimeType") or "application/octet-stream"),
                **output_artifact_flags(spec),
            }
        )
    return artifacts
