from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_generated_workflow_graph_canvas_uses_deterministic_layout_helper() -> None:
    layout_path = COMPONENTS / "generated-workflow-graph-layout.ts"
    canvas_path = COMPONENTS / "generated-workflow-graph-canvas.tsx"

    assert layout_path.exists()
    layout = layout_path.read_text(encoding="utf-8")
    canvas = canvas_path.read_text(encoding="utf-8")

    assert "export function layoutGeneratedWorkflowGraph" in layout
    assert "GeneratedWorkflowGraphNode" in layout
    assert "GeneratedWorkflowGraphEdge" in layout
    assert "orderedNodeIds" in layout
    assert "cycleBreakNodeIds" in layout
    assert "missingEdgeIds" in layout
    assert "incomingCount" in layout
    assert "outgoing" in layout

    assert 'from "./generated-workflow-graph-layout"' in canvas
    assert "layoutGeneratedWorkflowGraph({ edges, nodes })" in canvas
    assert "buildFlowNodes" in canvas
    assert "buildSubflowGroupNodes" in canvas
    assert "WorkflowSubflowGroupNode" in canvas
    assert "graphNodeSubflowId" in canvas
    assert "graphNodeSubflowLabel" in canvas
    assert "SUBFLOW_GROUP_NODE_PREFIX" in canvas
    assert "flowPositionForNode" in canvas
    assert "mergeFlowNodes" in canvas
    assert "visibleFlowNodes" in canvas
    assert "nodes={[...subflowGroupNodes, ...visibleFlowNodes]}" in canvas
    assert "isSubflowGroupNodeId" in canvas
    assert "layoutRevision" in canvas
    assert "nodePositions" not in canvas
