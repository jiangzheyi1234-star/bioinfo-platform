import assert from "node:assert/strict";
import test from "node:test";

import { buildWorkflowDagModel, inferRunState } from "./workflow_graph_model.ts";
import type { WorkflowArtifact, WorkflowRun, WorkflowSpecView } from "./detection_workspace_types.ts";

const workflow: WorkflowSpecView = {
  workflow_id: "wf_demo",
  name: "RNA demo",
  version: "1",
  nodes: [
    {
      node_id: "fetch_reads",
      tool_id: "download_reads",
      label: "Fetch Reads",
      params: {},
      position: { x: 32, y: 64 },
    },
    {
      node_id: "align_reads",
      tool_id: "align_reads",
      label: "Align Reads",
      params: {},
    },
    {
      node_id: "report",
      tool_id: "generate_report",
      label: "Report",
      params: {},
    },
  ],
  edges: [
    {
      edge_id: "edge_fetch_align",
      source_node_id: "fetch_reads",
      target_node_id: "align_reads",
      output_name: "reads",
      input_name: "reads",
    },
    {
      edge_id: "edge_align_report",
      source_node_id: "align_reads",
      target_node_id: "report",
      output_name: "bam",
      input_name: "input_bam",
    },
  ],
  params_schema: {},
};

const artifacts: WorkflowArtifact[] = [
  {
    name: "align_reads-report.html",
    remote_path: "/remote/align_reads/report.html",
    local_path: "/local/align_reads/report.html",
    available: true,
  },
];

const runningRun: WorkflowRun = {
  run_id: "run_1",
  project_id: "project_1",
  workflow_id: "wf_demo",
  profile_id: "local",
  status: "running",
  created_at: 1,
  updated_at: 2,
  bundle_id: "bundle_1",
  message: "",
  artifacts: [],
};

test("inferRunState normalizes workflow run statuses", () => {
  assert.equal(inferRunState(null), "draft");
  assert.equal(inferRunState({ ...runningRun, status: "queued" }), "running");
  assert.equal(inferRunState({ ...runningRun, status: "completed" }), "completed");
  assert.equal(inferRunState({ ...runningRun, status: "cancelled" }), "failed");
  assert.equal(inferRunState({ ...runningRun, status: "unknown_status" }), "compiled");
});

test("buildWorkflowDagModel preserves stored positions and selection metadata", () => {
  const model = buildWorkflowDagModel(workflow, runningRun, artifacts, "align_reads");

  assert.deepEqual(model.roots, ["fetch_reads"]);
  assert.deepEqual(model.leaves, ["report"]);
  assert.equal(model.nodes.length, 3);
  assert.equal(model.edges.length, 2);

  const fetchNode = model.nodes.find((node) => node.node_id === "fetch_reads");
  const alignNode = model.nodes.find((node) => node.node_id === "align_reads");
  const reportNode = model.nodes.find((node) => node.node_id === "report");
  assert.ok(fetchNode);
  assert.ok(alignNode);
  assert.ok(reportNode);

  assert.deepEqual(
    { x: fetchNode.x, y: fetchNode.y },
    { x: 32, y: 64 },
    "stored positions should be preserved instead of replaced by auto layout"
  );
  assert.equal(alignNode.selected, true);
  assert.equal(alignNode.state, "running");
  assert.equal(alignNode.matched_artifacts.length, 1);
  assert.deepEqual(alignNode.upstream, ["fetch_reads"]);
  assert.deepEqual(alignNode.downstream, ["report"]);

  const selectedEdges = model.edges.filter((edge) => edge.selected).map((edge) => edge.edge_id).sort();
  assert.deepEqual(selectedEdges, ["edge_align_report", "edge_fetch_align"]);
  assert.ok(reportNode.x > fetchNode.x, "auto layout should move downstream nodes to the right");
  assert.ok(model.width > reportNode.x);
  assert.ok(model.height >= reportNode.y + reportNode.height);
});
