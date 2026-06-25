from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_generated_workflow_graph_search_can_cycle_and_focus_results() -> None:
    builder = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    canvas = (COMPONENTS / "generated-workflow-graph-canvas.tsx").read_text(encoding="utf-8")
    adapter = (COMPONENTS / "generated-workflow-react-flow-adapter.ts").read_text(encoding="utf-8")

    assert "matchedGraphNodeSearchMatches" in adapter
    assert "matchedGraphNodeSearchMatches({ nodes, query: graphSearchQuery, toolByRevisionId })" in builder
    assert "activeGraphSearchIndex" in builder
    assert "cycleGraphSearch" in builder
    assert 'aria-label="上一个搜索结果"' in builder
    assert 'aria-label="下一个搜索结果"' in builder
    assert 'activeSearchNodeId={activeGraphSearchMatch?.nodeId || ""}' in builder
    assert "setSelectedNodeId(activeGraphSearchMatch.nodeId)" in builder

    assert "activeSearchNodeId?: string" in canvas
    assert "activeSearchResult" in canvas
    assert "ring-blue-400" in canvas
    assert "nodes: [{ id: activeSearchNodeId }]" in canvas
    assert "maxZoom: 1.15" in canvas
