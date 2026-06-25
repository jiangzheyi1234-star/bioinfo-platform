from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_react_flow_adapter_projects_edges_connections_and_search() -> None:
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
  buildFlowEdges,
  matchedGraphNodeIds,
  matchedGraphNodeSearchMatches,
  reactFlowConnectionToGraphConnection,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-react-flow-adapter.ts"));

const graphEdges = [
  {
    id: "source.report->target.reads:0",
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "target", port: "reads" },
    audit: { source: "manual", reason: "exact match" },
  },
];
const flowEdges = buildFlowEdges(graphEdges);
assert.equal(flowEdges[0].source, "source");
assert.equal(flowEdges[0].sourceHandle, "report");
assert.equal(flowEdges[0].target, "target");
assert.equal(flowEdges[0].targetHandle, "reads");
assert.equal(flowEdges[0].type, "smoothstep");
assert.deepEqual(flowEdges[0].data, { auditSource: "manual", auditReason: "exact match" });

assert.deepEqual(
  reactFlowConnectionToGraphConnection({
    source: "source",
    sourceHandle: "report",
    target: "target",
    targetHandle: "reads",
  }),
  { from: { nodeId: "source", port: "report" }, to: { nodeId: "target", port: "reads" } }
);
assert.equal(reactFlowConnectionToGraphConnection({ source: "source", target: "target" }), null);

const nodes = [
  { id: "source", toolRevisionId: "tool/source#1", inputs: {}, params: {}, runtime: {} },
  { id: "target", toolRevisionId: "tool/target#1", inputs: {}, params: {}, runtime: {} },
];
const tools = new Map([
  ["tool/source#1", { name: "FASTQ source", packageSpec: "fastq-source=1.0" }],
  ["tool/target#1", { name: "BAM target", packageSpec: "bam-target=1.0" }],
]);
assert.deepEqual([...matchedGraphNodeIds({ nodes, query: "fastq", toolByRevisionId: tools })], ["source"]);
assert.deepEqual([...matchedGraphNodeIds({ nodes, query: "target#1", toolByRevisionId: tools })], ["target"]);
assert.deepEqual(
  matchedGraphNodeSearchMatches({ nodes, query: "bam", toolByRevisionId: tools }),
  [{ label: "BAM target", matchedField: "tool", nodeId: "target" }]
);
assert.equal(matchedGraphNodeIds({ nodes, query: " ", toolByRevisionId: tools }).size, 0);
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout


def test_canvas_uses_react_flow_adapter_and_fails_loudly_for_invalid_drops() -> None:
    canvas = (COMPONENTS / "generated-workflow-graph-canvas.tsx").read_text(encoding="utf-8")
    adapter = (COMPONENTS / "generated-workflow-react-flow-adapter.ts").read_text(encoding="utf-8")

    assert 'from "./generated-workflow-react-flow-adapter"' in canvas
    assert "buildFlowEdges(edges)" in canvas
    assert "matchedGraphNodeIds({ nodes, query: searchQuery, toolByRevisionId })" in canvas
    assert "activeSearchNodeId" in canvas
    assert "flowInstanceRef.current?.fitView({" in canvas
    assert "nodes: [{ id: activeSearchNodeId }]" in canvas
    assert "reactFlowConnectionToGraphConnection(connection)" in canvas
    assert "无法添加工具：拖拽数据缺少工具修订 ID。" in canvas
    assert "无法添加工具：画布尚未初始化。" in canvas
    assert "sourceHandle" in adapter
    assert "targetHandle" in adapter
