from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_graph_node_positions_are_ui_metadata_and_history_backed() -> None:
    model = (COMPONENTS / "generated-workflow-model.ts").read_text(encoding="utf-8")
    builder_hook = (COMPONENTS / "use-generated-workflow-builder.ts").read_text(encoding="utf-8")
    builder_ui = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    graph_canvas = (COMPONENTS / "generated-workflow-graph-canvas.tsx").read_text(encoding="utf-8")
    design_model = (COMPONENTS / "workflow-design-draft-model.ts").read_text(encoding="utf-8")

    assert 'WORKFLOW_NODE_POSITION_X_METADATA_KEY = "uiPositionX"' in model
    assert 'WORKFLOW_NODE_POSITION_Y_METADATA_KEY = "uiPositionY"' in model
    assert "export function graphNodePosition" in model
    assert "export function graphNodeMetadataWithPosition" in model
    assert "stablePositionCoordinate" in model
    assert "metadata: { ...(existingNode?.metadata || {}), ...(node.metadata || {}) }" in design_model
    assert "metadata: node.metadata || {}" in design_model

    assert "graphNodeMetadataWithPosition" in builder_hook
    assert "graphNodePositionMatches" in builder_hook
    assert "commitGraphDraftIfChanged" in builder_hook
    assert "graphDraftWithNodePositions" in builder_hook
    assert 'type: "set_node_position"' in builder_hook
    assert 'type: "set_node_positions"' in builder_hook
    assert "setNodePosition" in builder_hook
    assert "setNodePositions" in builder_hook
    assert "commitWorkflowEditorHistory(state.graphHistory" in builder_hook
    assert "onNodePositionChange={builder.setNodePosition}" in builder_ui
    assert "onNodePositionsChange={builder.setNodePositions}" in builder_ui

    assert "graphNodePosition" in graph_canvas
    assert "layoutRequested = layoutRevisionRef.current !== layoutRevision" in graph_canvas
    assert "forceLayout: layoutRequested" in graph_canvas
    assert "onNodeDragStop" in graph_canvas
    assert "onNodePositionChange(node.id, node.position)" in graph_canvas
    assert "onNodePositionsChange(flowNodePositions(flowNodeDrafts))" in graph_canvas
    assert "flowPositionForNode" in graph_canvas
    assert "forceLayout ? null : graphNodePosition(node)" in graph_canvas
    assert "if (graphNodePosition(node.data.graphNode)) return node" in graph_canvas


def test_graph_position_helpers_round_trip_through_design_metadata() -> None:
    script = r"""
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const root = process.cwd();
const ts = require(path.join(root, "apps", "web", "node_modules", "typescript"));

require.extensions[".ts"] = function compileTypescript(module, filename) {
  const source = fs.readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  module._compile(output, filename);
};

const {
  graphNodeMetadataWithPosition,
  graphNodePosition,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-model.ts"));
const {
  buildWorkflowDesignDraft,
  workflowDesignDraftToGraphDraft,
} = require(path.join(root, "apps", "web", "app", "components", "workflow-design-draft-model.ts"));

const metadata = graphNodeMetadataWithPosition({ label: "qc" }, { x: 112.6, y: 248.2 });
assert.deepEqual(metadata, { label: "qc", uiPositionX: 113, uiPositionY: 248 });
assert.deepEqual(graphNodePosition({ metadata }), { x: 113, y: 248 });
assert.equal(graphNodePosition({ metadata: { uiPositionX: "bad", uiPositionY: 1 } }), null);
assert.equal(graphNodePosition({ metadata: { uiPositionX: true, uiPositionY: 1 } }), null);

const graphDraft = {
  nodes: [
    {
      id: "qc",
      toolRevisionId: "tool_qc#1",
      inputs: { reads: { fromUpload: 0 } },
      metadata,
      params: {},
      runtime: {},
    },
  ],
  edges: [],
  outputs: [],
};
const file = { name: "reads.fastq", type: "application/gzip" };
const draft = buildWorkflowDesignDraft({
  graphDraft,
  files: [file],
  projectId: "proj_position",
  resourceBindings: {},
  name: "Positioned workflow",
});
assert.equal(draft.nodes[0].metadata.uiPositionX, 113);
assert.equal(draft.nodes[0].metadata.uiPositionY, 248);
const reopened = workflowDesignDraftToGraphDraft(draft);
assert.deepEqual(graphNodePosition(reopened.nodes[0]), { x: 113, y: 248 });
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
