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
  semanticEdgeStatusForGraphEdge,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-react-flow-adapter.ts"));

const graphEdges = [
  {
    id: "source.report->target.reads:0",
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "target", port: "reads" },
    audit: { source: "manual", reason: "exact match" },
  },
  {
    id: "source.report->needs_converter.reads:0",
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "needs_converter", port: "reads" },
  },
  {
    id: "source.report->blocked.reads:0",
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "blocked", port: "reads" },
  },
  {
    id: "source.report->pending.reads:0",
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "pending", port: "reads" },
  },
];
const semanticPortPlan = {
  schemaVersion: "h2ometa.workflow-design-semantic-port-plan.v1",
  edgeCount: 3,
  compatibleEdgeCount: 1,
  blockedEdgeCount: 2,
  converterCandidateCount: 1,
  edges: [
    {
      edgeId: graphEdges[0].id,
      from: graphEdges[0].from,
      to: graphEdges[0].to,
      decision: { compatible: true },
      recommendation: { action: "connect", reasonCode: "SEMANTIC_PORTS_COMPATIBLE" },
      converterCandidates: [],
    },
    {
      from: graphEdges[1].from,
      to: graphEdges[1].to,
      decision: { compatible: false },
      recommendation: { action: "insert-converter", reasonCode: "CONVERTER_AVAILABLE" },
      converterCandidates: [{ converterToolRevisionId: "converter#1" }],
    },
    {
      edgeId: graphEdges[2].id,
      from: graphEdges[2].from,
      to: graphEdges[2].to,
      decision: { compatible: false },
      recommendation: { action: "block", reasonCode: "SEMANTIC_PORTS_INCOMPATIBLE" },
      converterCandidates: [],
    },
  ],
};
const flowEdges = buildFlowEdges(graphEdges, semanticPortPlan);
assert.equal(flowEdges[0].source, "source");
assert.equal(flowEdges[0].sourceHandle, "report");
assert.equal(flowEdges[0].target, "target");
assert.equal(flowEdges[0].targetHandle, "reads");
assert.equal(flowEdges[0].type, "smoothstep");
assert.deepEqual(flowEdges[0].data, {
  auditSource: "manual",
  auditReason: "exact match",
  semanticReasonCode: "SEMANTIC_PORTS_COMPATIBLE",
  semanticStatus: "compatible",
});
assert.equal(flowEdges[0].label, "compatible");
assert.equal(flowEdges[1].data.semanticStatus, "converter-needed");
assert.equal(flowEdges[1].label, "converter needed");
assert.equal(flowEdges[1].style.strokeDasharray, "6 4");
assert.equal(flowEdges[2].data.semanticStatus, "blocked");
assert.equal(flowEdges[2].label, "blocked");
assert.equal(flowEdges[3].data.semanticStatus, "unknown");
assert.equal(flowEdges[3].label, "semantic pending");
assert.equal(semanticEdgeStatusForGraphEdge(graphEdges[0], semanticPortPlan), "compatible");
assert.equal(semanticEdgeStatusForGraphEdge(graphEdges[1], semanticPortPlan), "converter-needed");
assert.equal(semanticEdgeStatusForGraphEdge(graphEdges[2], semanticPortPlan), "blocked");
assert.equal(semanticEdgeStatusForGraphEdge(graphEdges[3], semanticPortPlan), "unknown");

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
    assert "buildFlowEdges(edges, semanticPortPlan)" in canvas
    assert "matchedGraphNodeIds({ nodes, query: searchQuery, toolByRevisionId })" in canvas
    assert "activeSearchNodeId" in canvas
    assert "flowInstanceRef.current?.fitView({" in canvas
    assert "nodes: [{ id: activeSearchNodeId }]" in canvas
    assert "reactFlowConnectionToGraphConnection(connection)" in canvas
    assert "无法添加工具：拖拽数据缺少工具修订 ID。" in canvas
    assert "无法添加工具：画布尚未初始化。" in canvas
    assert "sourceHandle" in adapter
    assert "targetHandle" in adapter
