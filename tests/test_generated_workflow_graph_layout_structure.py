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
    assert "layout.positions.get(edge.from.nodeId)" in canvas
    assert "layout.positions.get(edge.to.nodeId)" in canvas
    assert "nodePositions" not in canvas
