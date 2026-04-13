from __future__ import annotations

import pytest

from core.workflow.compiler import compile_workflow_bundle
from core.workflow.domain import LaunchSpec, ServerProfile, WorkflowEdge, WorkflowNode, WorkflowSpec


class FakePluginRegistry:
    def __init__(self, descriptors: dict[str, dict]):
        self._descriptors = descriptors

    def get_descriptor(self, tool_id: str) -> dict:
        return self._descriptors[tool_id]


def _descriptor(tool_id: str, *, inputs: list[str] | None = None, outputs: list[str] | None = None) -> dict:
    return {
        "id": tool_id,
        "runtime": {"container": "docker.io/example/tool:latest", "conda": "bioconda::example=1.0"},
        "command_template": "echo run {{ sample_id }} > {{ result_file }}",
        "inputs": [{"name": name, "required": True} for name in (inputs or [])],
        "outputs": [{"name": name, "path": f"results/{name}.txt", "pattern": f"results/{name}.txt"} for name in (outputs or ["result_file"])],
        "parameters": [],
        "resources": {"cpus": 1, "memory": "1 GB", "time": "1h"},
    }


def _launch() -> LaunchSpec:
    return LaunchSpec(
        project_id="project-1",
        profile=ServerProfile(
            profile_id="personal_docker",
            server_id="current",
            profile_kind="personal_docker",
            executor="local",
            packaging_mode="container",
            container_runtime="docker",
        ),
        params={},
        data_refs=[],
        resume=True,
    )


def test_compile_workflow_rejects_circular_dependencies() -> None:
    registry = FakePluginRegistry({
        "tool_a": _descriptor("tool_a", inputs=["input_a"], outputs=["output_a"]),
        "tool_b": _descriptor("tool_b", inputs=["input_b"], outputs=["output_b"]),
    })
    spec = WorkflowSpec(
        workflow_id="wf-cycle",
        name="cycle",
        nodes=[
            WorkflowNode(node_id="a", tool_id="tool_a", label="A"),
            WorkflowNode(node_id="b", tool_id="tool_b", label="B"),
        ],
        edges=[
            WorkflowEdge(edge_id="e1", source_node_id="a", target_node_id="b", output_name="output_a", input_name="input_b"),
            WorkflowEdge(edge_id="e2", source_node_id="b", target_node_id="a", output_name="output_b", input_name="input_a"),
        ],
    )

    with pytest.raises(RuntimeError, match="循环依赖"):
        compile_workflow_bundle(spec, _launch(), plugin_registry=registry)


def test_compile_workflow_rejects_duplicate_inputs() -> None:
    registry = FakePluginRegistry({
        "tool_a": _descriptor("tool_a", outputs=["output_a"]),
        "tool_b": _descriptor("tool_b", outputs=["output_b"]),
        "tool_c": _descriptor("tool_c", inputs=["reads"], outputs=["output_c"]),
    })
    spec = WorkflowSpec(
        workflow_id="wf-duplicate",
        name="duplicate",
        nodes=[
            WorkflowNode(node_id="a", tool_id="tool_a", label="A"),
            WorkflowNode(node_id="b", tool_id="tool_b", label="B"),
            WorkflowNode(node_id="c", tool_id="tool_c", label="C"),
        ],
        edges=[
            WorkflowEdge(edge_id="e1", source_node_id="a", target_node_id="c", output_name="output_a", input_name="reads"),
            WorkflowEdge(edge_id="e2", source_node_id="b", target_node_id="c", output_name="output_b", input_name="reads"),
        ],
    )

    with pytest.raises(RuntimeError, match="重复输入连接: c.reads"):
        compile_workflow_bundle(spec, _launch(), plugin_registry=registry)


def test_compile_workflow_rejects_missing_output_name() -> None:
    registry = FakePluginRegistry({
        "tool_a": _descriptor("tool_a", outputs=["output_a"]),
        "tool_b": _descriptor("tool_b", inputs=["reads"], outputs=["output_b"]),
    })
    spec = WorkflowSpec(
        workflow_id="wf-output",
        name="missing-output",
        nodes=[
            WorkflowNode(node_id="a", tool_id="tool_a", label="A"),
            WorkflowNode(node_id="b", tool_id="tool_b", label="B"),
        ],
        edges=[
            WorkflowEdge(edge_id="e1", source_node_id="a", target_node_id="b", output_name="not_real", input_name="reads"),
        ],
    )

    with pytest.raises(RuntimeError, match="不存在的 output"):
        compile_workflow_bundle(spec, _launch(), plugin_registry=registry)
