from __future__ import annotations

import json
from typing import Any


GENERATED_WORKFLOW_RULE_CONTRACT_VERSION = "rule-contract-v1"


def normalize_generated_workflow_run_spec(run_spec: dict[str, Any]) -> dict[str, Any]:
    workflow = run_spec.get("workflow")
    if not isinstance(workflow, dict) or "nodes" not in workflow:
        return run_spec
    normalized = dict(run_spec)
    normalized["workflow"] = normalize_generated_workflow_graph(workflow)
    return normalized


def workflow_graph_config(workflow: Any) -> dict[str, Any] | None:
    if not isinstance(workflow, dict) or "nodes" not in workflow:
        return None
    graph: dict[str, Any] = {
        "contractVersion": str(workflow.get("contractVersion") or ""),
        "nodes": _json_safe(workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []),
        "edges": _json_safe(workflow.get("edges") if isinstance(workflow.get("edges"), list) else []),
    }
    outputs = workflow.get("outputs")
    if outputs not in (None, {}, []):
        graph["outputs"] = _json_safe(outputs)
    return graph


def normalize_generated_workflow_graph(workflow: dict[str, Any]) -> dict[str, Any]:
    if "steps" in workflow:
        raise ValueError("WORKFLOW_GRAPH_STEPS_CONFLICT")
    _validate_graph_contract_version(workflow)
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("WORKFLOW_GRAPH_NODES_REQUIRED")
    edges = workflow.get("edges")
    if not isinstance(edges, list):
        raise ValueError("WORKFLOW_GRAPH_EDGES_REQUIRED")

    steps = [_step_from_node(node) for node in nodes]
    step_by_id = {str(step["id"]): step for step in steps}
    if len(step_by_id) != len(steps):
        raise ValueError("WORKFLOW_STEP_DUPLICATE")

    for edge in edges:
        source_node, source_port, target_node, target_port = _edge_ports(edge)
        if source_node not in step_by_id:
            raise ValueError(f"WORKFLOW_GRAPH_EDGE_NODE_UNKNOWN: {source_node}")
        if target_node not in step_by_id:
            raise ValueError(f"WORKFLOW_GRAPH_EDGE_NODE_UNKNOWN: {target_node}")
        target_inputs = step_by_id[target_node].setdefault("inputs", {})
        if target_port in target_inputs:
            raise ValueError(f"WORKFLOW_GRAPH_INPUT_EDGE_CONFLICT: {target_node}.{target_port}")
        target_inputs[target_port] = {"fromStep": source_node, "output": source_port}

    normalized = {key: value for key, value in workflow.items() if key not in {"nodes", "edges", "outputs"}}
    normalized["steps"] = steps
    outputs = _normalize_graph_outputs(workflow.get("outputs"))
    if outputs is not None:
        normalized["outputs"] = outputs
    return normalized


def _validate_graph_contract_version(workflow: dict[str, Any]) -> None:
    raw_version = workflow.get("contractVersion")
    version = str(raw_version or "").strip()
    if not version:
        raise ValueError("WORKFLOW_GRAPH_CONTRACT_VERSION_REQUIRED")
    if version != GENERATED_WORKFLOW_RULE_CONTRACT_VERSION:
        raise ValueError(f"WORKFLOW_GRAPH_CONTRACT_VERSION_UNSUPPORTED: {version}")


def _step_from_node(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise ValueError("WORKFLOW_GRAPH_NODE_INVALID")
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        raise ValueError("WORKFLOW_GRAPH_NODE_ID_REQUIRED")
    tool = node.get("tool")
    if isinstance(tool, dict):
        tool_request = dict(tool)
    else:
        tool_id = str(node.get("toolId") or "").strip()
        if not tool_id:
            raise ValueError(f"WORKFLOW_GRAPH_NODE_TOOL_REQUIRED: {node_id}")
        tool_request = {"id": tool_id}
    inputs = node.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"WORKFLOW_GRAPH_NODE_INPUTS_INVALID: {node_id}")
    step = {
        "id": node_id,
        "tool": tool_request,
        "inputs": dict(inputs),
    }
    if isinstance(node.get("params"), dict):
        step["params"] = dict(node["params"])
    if isinstance(node.get("runtime"), dict):
        step["runtime"] = dict(node["runtime"])
    return step


def _edge_ports(edge: Any) -> tuple[str, str, str, str]:
    if not isinstance(edge, dict):
        raise ValueError("WORKFLOW_GRAPH_EDGE_INVALID")
    source = edge.get("from")
    target = edge.get("to")
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError("WORKFLOW_GRAPH_EDGE_INVALID")
    source_node = str(source.get("nodeId") or "").strip()
    source_port = str(source.get("port") or "").strip()
    target_node = str(target.get("nodeId") or "").strip()
    target_port = str(target.get("port") or "").strip()
    if not source_node or not source_port or not target_node or not target_port:
        raise ValueError("WORKFLOW_GRAPH_EDGE_INVALID")
    return source_node, source_port, target_node, target_port


def _normalize_graph_outputs(raw: Any) -> list[dict[str, str]] | None:
    if raw in (None, {}, []):
        return None
    if isinstance(raw, list):
        return [_normalize_graph_output_binding(binding) for binding in raw]
    raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")


def _normalize_graph_output_binding(binding: Any) -> dict[str, str]:
    if not isinstance(binding, dict):
        raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
    source = binding.get("from")
    if not isinstance(source, dict):
        raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
    node_id = str(source.get("nodeId") or "").strip()
    port = str(source.get("port") or "").strip()
    alias = str(binding.get("as") or "").strip()
    if not node_id or not port or not alias:
        raise ValueError("WORKFLOW_OUTPUT_BINDING_INVALID")
    return {"fromStep": node_id, "output": port, "as": alias}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value))
