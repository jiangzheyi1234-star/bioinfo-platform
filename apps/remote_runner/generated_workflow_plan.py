from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .errors import WorkflowToolNotReadyError
from .generated_workflow_graph import normalize_generated_workflow_run_spec
from .generated_workflow_names import safe_identifier, safe_snakemake_name
from .generated_workflow_outputs import resolve_exposed_outputs
from .generated_workflow_ports import resolve_outputs, resolve_step_inputs, resolve_step_params
from .generated_workflow_steps import (
    resolve_requested_steps,
    step_id_from_request,
    step_tool_revision_id,
    topologically_order_steps,
)
from .rule_ports import build_output_port_specs
from .rule_runtime import RuleRuntimeDirectives, resolve_rule_runtime_directives
from .rule_templates import rule_template_candidate_entries
from .tool_revisions import fetch_tool_revision
from .tools import normalize_rule_template


@dataclass(frozen=True)
class GeneratedWorkflowStepPlan:
    step_id: str
    rule_name: str
    tool_id: str
    tool_revision_id: str
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
    tool_overrides: dict[str, dict[str, Any]] | None = None,
) -> GeneratedWorkflowPlan:
    run_spec = normalize_generated_workflow_run_spec(run_spec)
    requested_steps = topologically_order_steps(resolve_requested_steps(run_spec))
    workflow_spec = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    generated_steps: list[GeneratedWorkflowStepPlan] = []
    outputs_by_step_id: dict[str, dict[str, Path]] = {}
    output_port_specs_by_step_id: dict[str, dict[str, dict[str, str]]] = {}

    for index, requested_step in enumerate(requested_steps):
        tool_revision_id = step_tool_revision_id(requested_step)
        tool = tool_overrides.get(tool_revision_id) if tool_overrides else None
        tool = tool or fetch_tool_revision(cfg, tool_revision_id)
        if tool is None:
            raise ValueError("TOOL_REVISION_NOT_FOUND")
        tool_id = str(tool.get("id") or tool.get("toolId") or "").strip()
        if not tool_id:
            raise ValueError("TOOL_ID_REQUIRED")
        if not bool(tool.get("targetPlatformSupported")):
            raise ValueError("TOOL_PLATFORM_UNSUPPORTED")
        package_spec = str(tool.get("packageSpec") or "").strip()
        if not package_spec:
            raise ValueError("TOOL_PACKAGE_SPEC_REQUIRED")
        if require_workflow_ready:
            validate_tool_workflow_ready(tool)
        tool_request = {"toolRevisionId": tool_revision_id}

        step_id = step_id_from_request(requested_step)
        safe_tool_id = safe_identifier(tool_id)
        safe_step_id = safe_identifier(step_id)
        single_step = len(requested_steps) == 1
        env_path = Path("envs") / (f"{safe_tool_id}.yaml" if single_step else f"{safe_step_id}-{safe_tool_id}.yaml")
        rule_template, rule_spec_draft = resolve_rule_contract(tool=tool, tool_request=tool_request)
        params = resolve_step_params(
            rule_template=rule_template,
            requested_step=requested_step,
        )
        output_prefix = safe_step_id if not single_step else ""
        inputs = resolve_step_inputs(
            step_id=step_id,
            requested_step=requested_step,
            rule_template=rule_template,
            resolved_inputs=resolved_inputs,
            outputs_by_step_id=outputs_by_step_id,
            output_port_specs_by_step_id=output_port_specs_by_step_id,
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
                tool_revision_id=tool_revision_id,
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
    raise WorkflowToolNotReadyError(f"WORKFLOW_TOOL_NOT_READY: {state}")


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
