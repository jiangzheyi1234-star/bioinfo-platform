"""Plan-only validation and preview for WorkflowDesignDraft."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .generated_workflow import GENERATED_TOOL_RUN_VERSION
from .generated_workflow_plan import plan_generated_workflow_steps, resolve_exposed_outputs
from .rule_outputs import output_spec_metadata, rule_output_metadata
from .rule_rendering import render_generated_workflow_snakefile
from .rule_runtime import runtime_config
from .workflow_design_contract import (
    WorkflowDesignDraftV1,
    workflow_design_graph,
    workflow_design_resolved_inputs,
    workflow_design_to_generated_run_spec,
)
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs


def plan_workflow_design_draft(
    cfg: RemoteRunnerConfig,
    draft: dict[str, Any] | WorkflowDesignDraftV1,
    *,
    preview_root: Path,
    draft_id: str | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    design = WorkflowDesignDraftV1.model_validate(draft)
    resolved_inputs = workflow_design_resolved_inputs(design)
    if not resolved_inputs:
        return _invalid_plan(design, "INPUT_REQUIRED")
    result_dir = preview_root / "results"
    run_spec = workflow_design_to_generated_run_spec(design, draft_id=draft_id, revision=revision)
    try:
        plan = plan_generated_workflow_steps(
            cfg,
            run_spec=run_spec,
            resolved_inputs=resolved_inputs,
            result_dir=result_dir,
            require_workflow_ready=True,
        )
    except ValueError as exc:
        return _invalid_plan(design, str(exc))

    try:
        resource_specs = collect_workflow_resource_specs([step.rule_template for step in plan.steps])
    except ValueError as exc:
        return _invalid_plan(design, str(exc))

    try:
        resource_config = build_workflow_resource_config(
            cfg,
            workflow_resource_spec=resource_specs,
            bindings=design.resources.bindings,
        )
    except ValueError as exc:
        return _invalid_plan(design, str(exc), required_resources=resource_specs)

    try:
        exposed_outputs = resolve_exposed_outputs(
            workflow_spec=plan.workflow_spec,
            steps=plan.steps,
            outputs_by_step_id=plan.outputs_by_step_id,
        )
        final_outputs = {name: str(binding["path"]) for name, binding in exposed_outputs.items()}
        snakefile = render_generated_workflow_snakefile(
            steps=plan.steps,
            final_outputs=final_outputs,
            output_dir=str(result_dir),
            databases={},
            resources=resource_config["resources"],
            resource_config=resource_config["config"],
        )
        config = _preview_config(
            design=design,
            plan=plan,
            resolved_inputs=resolved_inputs,
            exposed_outputs=exposed_outputs,
            final_outputs=final_outputs,
            resource_config=resource_config,
            draft_id=draft_id,
            revision=revision,
        )
    except ValueError as exc:
        return _invalid_plan(
            design,
            str(exc),
            required_resources=resource_specs,
            required_databases=resource_config["resources"],
        )
    return {
        "valid": True,
        "normalizedGraph": workflow_design_graph(design),
        "orderedSteps": [_step_summary(step) for step in plan.steps],
        "resolvedPorts": {
            step.step_id: {
                "inputs": dict(step.inputs),
                "outputs": {name: str(path) for name, path in step.outputs.items()},
            }
            for step in plan.steps
        },
        "requiredResources": resource_specs,
        "requiredDatabases": resource_config["resources"],
        "exposedOutputs": {
            name: {
                "step": str(binding["step"].step_id),
                "output": str(binding["output"]),
                "path": str(binding["path"]),
                **output_spec_metadata(dict(binding.get("spec") or {})),
            }
            for name, binding in exposed_outputs.items()
        },
        "validationIssues": [],
        "previews": {
            "snakefile": snakefile,
            "config": json.dumps(config, indent=2),
        },
        "runSpec": run_spec,
    }


def _invalid_plan(
    design: WorkflowDesignDraftV1,
    detail: str,
    *,
    required_resources: dict[str, Any] | None = None,
    required_databases: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "valid": False,
        "normalizedGraph": workflow_design_graph(design),
        "orderedSteps": [],
        "resolvedPorts": {},
        "requiredResources": required_resources or {},
        "requiredDatabases": required_databases or {},
        "exposedOutputs": {},
        "validationIssues": [{"code": _issue_code(detail), "message": detail}],
        "previews": {"snakefile": "", "config": ""},
        "runSpec": {},
    }


def _preview_config(
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
        "run_id": "plan_preview",
        "request_id": "plan_preview",
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
                        "name": str(step.tool.get("name") or ""),
                        "source": str(step.tool.get("source") or ""),
                        "version": str(step.tool.get("version") or ""),
                        "packageSpec": str(step.tool.get("packageSpec") or ""),
                        "ruleTemplate": step.rule_template,
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


def _step_summary(step: Any) -> dict[str, Any]:
    return {
        "id": step.step_id,
        "rule": step.rule_name,
        "toolId": step.tool_id,
        "toolRevisionId": step.tool_revision_id,
        "toolName": str(step.tool.get("name") or ""),
        "params": dict(step.params),
        "runtime": runtime_config(step.runtime),
    }


def _issue_code(detail: str) -> str:
    return detail.split(":", 1)[0].strip() or "WORKFLOW_DESIGN_PLAN_FAILED"


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
