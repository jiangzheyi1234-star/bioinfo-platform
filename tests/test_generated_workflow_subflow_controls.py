from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_subflow_controls_commit_labels_without_per_keystroke_history() -> None:
    builder = _source("generated-workflow-builder.tsx")
    controls = _source("generated-workflow-subflow-controls.tsx")

    assert "GeneratedWorkflowSubflowControls" in builder
    assert "node={selectedNode}" in builder
    assert "onChange={builder.setNodeSubflow}" in builder
    assert "builder.setNodeSubflow(selectedNode.id, event.target.value)" not in builder

    assert "export function GeneratedWorkflowSubflowControls" in controls
    assert "graphNodeSubflowLabel(node)" in controls
    assert "const [draftLabel, setDraftLabel]" in controls
    assert 'if (event.key === "Enter")' in controls
    assert 'if (event.key === "Escape")' in controls
    assert "onBlur={commit}" in controls
    assert "onChange={(event) => setDraftLabel(event.target.value)}" in controls
    assert "onChange(node.id, nextLabel)" in controls
    assert "onChange(node.id, \"\")" in controls
    assert 'aria-label="应用子流程标签"' in controls
    assert 'aria-label="清除子流程标签"' in controls
    assert 'data-testid="workflow-subflow-controls"' in controls


def test_subflow_controls_preserve_flat_graph_contract() -> None:
    controls = _source("generated-workflow-subflow-controls.tsx")
    hook = _source("use-generated-workflow-builder.ts")
    model = _source("generated-workflow-model.ts")
    canvas = _source("generated-workflow-graph-canvas.tsx")

    assert "uiSubflowId" in model
    assert "uiSubflowLabel" in model
    assert "graphNodeMetadataWithSubflow" in model
    assert "graphNodeSubflowId" in canvas
    assert "subflowGroup" in canvas
    assert "type: \"set_node_subflow\"" in hook
    assert "graphDraftWithNodeSubflow" in hook
    assert "commitGraphDraftIfChanged(" in hook
    assert "graphNodeMetadataWithSubflow(node.metadata, label)" in hook
    assert "graphNodeMetadataMatches(node.metadata, metadata)" in hook

    forbidden_persistence = ("parentId", "parentNode", "extent: 'parent'", 'extent: "parent"', "children:")
    for forbidden in forbidden_persistence:
        assert forbidden not in controls
        assert forbidden not in hook
        assert forbidden not in model
