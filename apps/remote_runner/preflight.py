from __future__ import annotations

from pathlib import Path
from typing import Any

from .capability_bundle_audit import validate_capability_bundle_gate
from .config import RemoteRunnerConfig
from .errors import WorkflowToolNotReadyError
from .generated_workflow_constants import GENERATED_TOOL_RUN_PIPELINE_ID
from .generated_workflow_outputs import resolve_exposed_outputs
from .generated_workflow_plan import plan_generated_workflow_steps
from .pipeline import PipelineDefinition
from .workflow_design_submission import validate_workflow_design_run_spec
from .workflow_resources import build_workflow_resource_config, collect_workflow_resource_specs


class RunPreflightError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code

    @classmethod
    def from_value_error(cls, exc: ValueError) -> "RunPreflightError":
        if isinstance(exc, WorkflowToolNotReadyError):
            return cls(str(exc), status_code=exc.status_code)
        if str(exc).startswith("CAPABILITY_BUNDLE_NOT_SELECTABLE"):
            return cls(str(exc), status_code=409)
        return cls(str(exc))


def preflight_run_spec(cfg: RemoteRunnerConfig, pipeline: PipelineDefinition, run_spec: dict[str, Any]) -> None:
    if pipeline.pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
        _preflight_generated_workflow(cfg, run_spec)
        return
    _preflight_pipeline_resources(cfg, pipeline, run_spec)


def _preflight_pipeline_resources(
    cfg: RemoteRunnerConfig,
    pipeline: PipelineDefinition,
    run_spec: dict[str, Any],
) -> None:
    if not pipeline.resource_schema:
        return
    try:
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec=pipeline.resource_schema,
            bindings=dict(run_spec.get("resourceBindings") or {}),
        )
    except ValueError as exc:
        raise RunPreflightError.from_value_error(exc) from exc


def _preflight_generated_workflow(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> None:
    if "database" in run_spec or "databases" in run_spec:
        raise RunPreflightError("RESOURCE_BINDINGS_REQUIRED")
    try:
        validate_workflow_design_run_spec(cfg, run_spec)
        plan = plan_generated_workflow_steps(
            cfg,
            run_spec=run_spec,
            resolved_inputs=_preflight_resolved_inputs(run_spec),
            result_dir=Path("."),
        )
        resolve_exposed_outputs(
            workflow_spec=plan.workflow_spec,
            steps=plan.steps,
            outputs_by_step_id=plan.outputs_by_step_id,
        )
        resource_specs = collect_workflow_resource_specs([step.rule_template for step in plan.steps])
        resource_config = build_workflow_resource_config(
            cfg,
            workflow_resource_spec=resource_specs,
            bindings=dict(plan.run_spec.get("resourceBindings") or {}),
        )
        for step in plan.steps:
            validate_capability_bundle_gate(
                step.tool,
                step_id=step.step_id,
                resource_context=resource_config["resources"],
            )
    except ValueError as exc:
        raise RunPreflightError.from_value_error(exc) from exc


def _preflight_resolved_inputs(run_spec: dict[str, Any]) -> list[dict[str, str]]:
    raw_inputs = run_spec.get("inputs") or []
    if not isinstance(raw_inputs, list):
        return []
    resolved: list[dict[str, str]] = []
    for index, item in enumerate(raw_inputs):
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("filename") or item.get("uploadId") or f"input_{index + 1}")
            role = str(item.get("role") or ("input" if index == 0 else f"input_{index + 1}"))
        else:
            path = f"input_{index + 1}"
            role = "input" if index == 0 else f"input_{index + 1}"
        resolved.append({"path": path, "role": role})
    return resolved
