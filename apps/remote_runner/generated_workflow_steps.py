from __future__ import annotations

from typing import Any

from .generated_workflow_names import safe_identifier


def resolve_requested_steps(run_spec: dict[str, Any]) -> list[dict[str, Any]]:
    workflow = run_spec.get("workflow")
    steps = workflow.get("steps") if isinstance(workflow, dict) else None
    if not isinstance(steps, list) or not steps:
        raise ValueError("WORKFLOW_GRAPH_NODES_REQUIRED")
    if any(not isinstance(step, dict) for step in steps):
        raise ValueError("WORKFLOW_STEP_INVALID")
    return steps


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


def step_tool_revision_id(step: dict[str, Any]) -> str:
    tool_revision_id = str(step.get("toolRevisionId") or "").strip()
    if not tool_revision_id:
        raise ValueError("TOOL_REVISION_ID_REQUIRED")
    return tool_revision_id


def step_id_from_request(step: dict[str, Any]) -> str:
    raw_id = str(step.get("id") or "").strip()
    if not raw_id:
        raise ValueError("WORKFLOW_STEP_ID_REQUIRED")
    return safe_identifier(raw_id)
