from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_react_flow_port_connection_decision_blocks_invalid_edges() -> None:
    script = r"""
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const root = process.cwd();
const ts = require(path.join(root, "apps", "web", "node_modules", "typescript"));

function compileTypescript(module, filename) {
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
}

require.extensions[".ts"] = compileTypescript;
require.extensions[".tsx"] = compileTypescript;

const {
  evaluateGeneratedWorkflowPortConnection,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-port-connection.ts"));

function readyTool({ id, name, inputs, outputs }) {
  return {
    id,
    name,
    source: "bioconda",
    sourceLabel: "Bioconda",
    packageSpec: `${id}=1.0`,
    selectedPackageSpec: `${id}=1.0`,
    selectedVersion: "1.0",
    targetPlatformSupported: true,
    toolRevisionId: `${id}#1`,
    toolContract: { state: "WorkflowReady", workflowReady: true },
    ruleTemplate: {
      commandTemplate: "cat {input.reads:q} > {output.report:q}",
      inputs,
      outputs,
      params: {},
      threads: 1,
      schedulerResources: { mem_mb: 128 },
      log: `logs/${name}.log`,
      environment: { conda: { channels: ["conda-forge", "bioconda"], dependencies: [`${id}=1.0`] } },
      smokeTest: {
        inputs: Object.fromEntries(inputs.map((input) => [input.name, {
          filename: `${input.name}.txt`,
          content: "fixture\n",
          mimeType: input.mimeType || "text/plain",
        }])),
      },
    },
  };
}

const FASTQ_FORMAT = "format_1930";
const BAM_FORMAT = "format_2572";

const sourceTool = readyTool({
  id: "bioconda::source",
  name: "source",
  inputs: [{ name: "reads", required: true, type: "file", kind: "reads", format: FASTQ_FORMAT }],
  outputs: [{ name: "report", path: "source.fastq", type: "file", kind: "reads", format: FASTQ_FORMAT }],
});
const targetTool = readyTool({
  id: "bioconda::target",
  name: "target",
  inputs: [{ name: "reads", required: true, type: "file", kind: "reads", format: FASTQ_FORMAT }],
  outputs: [{ name: "report", path: "target.fastq", type: "file", kind: "reads", format: FASTQ_FORMAT }],
});
const incompatibleTool = readyTool({
  id: "bioconda::bam-target",
  name: "bam-target",
  inputs: [{ name: "reads", required: true, type: "file", kind: "alignment", format: BAM_FORMAT }],
  outputs: [{ name: "report", path: "target.bam", type: "file", kind: "alignment", format: BAM_FORMAT }],
});
const tools = [sourceTool, targetTool, incompatibleTool];
const baseGraph = {
  nodes: [
    { id: "source", toolRevisionId: sourceTool.toolRevisionId, inputs: { reads: { fromUpload: 0 } }, params: {}, runtime: {} },
    { id: "target", toolRevisionId: targetTool.toolRevisionId, inputs: {}, params: {}, runtime: {} },
    { id: "bam_target", toolRevisionId: incompatibleTool.toolRevisionId, inputs: {}, params: {}, runtime: {} },
  ],
  edges: [],
  outputs: [],
};

const allowed = evaluateGeneratedWorkflowPortConnection({
  graphDraft: baseGraph,
  tools,
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "target", port: "reads" },
  },
});
assert.equal(allowed.ok, true);
assert.equal(allowed.binding.fromStep, "source");
assert.equal(allowed.binding.output, "report");
assert.equal(allowed.binding.audit.source, "manual");
assert(allowed.binding.audit.evidence.includes("画布手动连线"));

const incompatible = evaluateGeneratedWorkflowPortConnection({
  graphDraft: baseGraph,
  tools,
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "bam_target", port: "reads" },
  },
});
assert.equal(incompatible.ok, false);
assert.equal(incompatible.code, "WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE");

const cyclicGraph = {
  ...baseGraph,
  edges: [
    {
      id: "source.report->target.reads:0",
      from: { nodeId: "source", port: "report" },
      to: { nodeId: "target", port: "reads" },
    },
  ],
};
const cyclic = evaluateGeneratedWorkflowPortConnection({
  graphDraft: cyclicGraph,
  tools,
  connection: {
    from: { nodeId: "target", port: "report" },
    to: { nodeId: "source", port: "reads" },
  },
});
assert.equal(cyclic.ok, false);
assert.equal(cyclic.code, "WORKFLOW_GRAPH_CONNECTION_CYCLE");
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
