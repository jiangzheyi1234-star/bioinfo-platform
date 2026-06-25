from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_converter_insertion_patch_builds_plain_valid_graph() -> None:
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
  blockedOneHopPortConverterReasons,
  buildConverterInsertionPatch,
  findOneHopPortConverters,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-converter-recommendation.ts"));
const {
  converterSuggestionsForConnection,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-port-advice.ts"));
const {
  graphDraftToGeneratedWorkflowDraft,
  validateGeneratedWorkflowDraft,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-model.ts"));

function readyTool({ id, name, inputs, outputs, commandTemplate = "cat {input.reads:q} > {output.report:q}" }) {
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
      commandTemplate,
      inputs,
      outputs,
      params: { min_len: { type: "integer", default: 50 } },
      threads: 1,
      schedulerResources: { mem_mb: 128 },
      environment: { conda: { channels: ["conda-forge", "bioconda"], dependencies: [`${id}=1.0`] } },
      log: `logs/${name}.log`,
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

const sourceTool = readyTool({
  id: "bioconda::source",
  name: "source",
  inputs: [{ name: "reads", required: true, kind: "reads", format: "fastq" }],
  outputs: [{ name: "report", path: "source.fastq", kind: "reads", format: "fastq", type: "file" }],
});
const converterTool = readyTool({
  id: "bioconda::sam-to-bam",
  name: "sam-to-bam",
  inputs: [{ name: "reads", required: true, kind: "reads", format: "fastq", type: "file" }],
  outputs: [{ name: "bam", path: "converted.bam", kind: "alignment_bam", format: "bam", type: "file" }],
  commandTemplate: "cp {input.reads:q} {output.bam:q}",
});
const targetTool = readyTool({
  id: "bioconda::target",
  name: "target",
  inputs: [{ name: "reads", required: true, kind: "alignment_bam", format: "bam", type: "file" }],
  outputs: [{ name: "report", path: "target.txt", kind: "report", format: "txt", type: "file" }],
});

const [converter] = findOneHopPortConverters({
  input: { name: "reads", kind: "alignment_bam", format: "bam", type: "file" },
  output: { name: "report", kind: "reads", format: "fastq", type: "file" },
  tools: [sourceTool, converterTool, targetTool],
  excludeToolRevisionIds: [targetTool.toolRevisionId],
});
assert.equal(converter.converterToolRevisionId, converterTool.toolRevisionId);
assert.equal(converter.confirmationRequired, true);
assert.equal(converter.insertionMode, "explicit-user-confirmed");
assert(converter.autoInsertionBlockedReasons.includes("confirmation-required"));
assert(converter.autoInsertionBlockedReasons.includes("graph-mutation-requires-user-action"));
assert(converter.hardChecks.includes("converter-has-no-database-resource"));
assert(converter.hardChecks.includes("source-output-to-converter-input-strong-evidence"));
assert(converter.hardChecks.includes("converter-output-to-target-input-strong-evidence"));
assert(converter.evidence.includes("上游输出可进入 reads"));
assert(converter.evidence.includes("bam 可满足目标输入"));

const canvasGraphDraft = {
  nodes: [
    { id: "source", toolRevisionId: sourceTool.toolRevisionId, inputs: { reads: { fromUpload: 0 } }, params: {}, runtime: {} },
    { id: "target", toolRevisionId: targetTool.toolRevisionId, inputs: {}, params: {}, runtime: {} },
  ],
  edges: [],
  outputs: [],
};
const [canvasSuggestion] = converterSuggestionsForConnection({
  graphDraft: canvasGraphDraft,
  tools: [sourceTool, converterTool, targetTool],
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "target", port: "reads" },
  },
});
assert.equal(canvasSuggestion.converterToolRevisionId, converterTool.toolRevisionId);
assert.equal(canvasSuggestion.sourceStepId, "source");
assert.equal(canvasSuggestion.sourceOutput, "report");
assert.equal(canvasSuggestion.confirmationRequired, true);
assert.equal(canvasSuggestion.insertionMode, "explicit-user-confirmed");
assert(canvasSuggestion.autoInsertionBlockedReasons.includes("graph-mutation-requires-user-action"));

const compatibleSuggestion = converterSuggestionsForConnection({
  graphDraft: {
    nodes: [
      canvasGraphDraft.nodes[0],
      { id: "converter", toolRevisionId: converterTool.toolRevisionId, inputs: {}, params: {}, runtime: {} },
    ],
    edges: [],
    outputs: [],
  },
  tools: [sourceTool, converterTool],
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "converter", port: "reads" },
  },
});
assert.deepEqual(compatibleSuggestion, []);

const selfSuggestion = converterSuggestionsForConnection({
  graphDraft: canvasGraphDraft,
  tools: [sourceTool, converterTool, targetTool],
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "source", port: "reads" },
  },
});
assert.deepEqual(selfSuggestion, []);

const unknownNodeSuggestion = converterSuggestionsForConnection({
  graphDraft: canvasGraphDraft,
  tools: [sourceTool, converterTool, targetTool],
  connection: {
    from: { nodeId: "missing", port: "report" },
    to: { nodeId: "target", port: "reads" },
  },
});
assert.deepEqual(unknownNodeSuggestion, []);

const unknownPortSuggestion = converterSuggestionsForConnection({
  graphDraft: canvasGraphDraft,
  tools: [sourceTool, converterTool, targetTool],
  connection: {
    from: { nodeId: "source", port: "missing" },
    to: { nodeId: "target", port: "reads" },
  },
});
assert.deepEqual(unknownPortSuggestion, []);

const cyclicSuggestion = converterSuggestionsForConnection({
  graphDraft: {
    ...canvasGraphDraft,
    edges: [
      { id: "target.report->source.reads:0", from: { nodeId: "target", port: "report" }, to: { nodeId: "source", port: "reads" } },
    ],
  },
  tools: [sourceTool, converterTool, targetTool],
  connection: {
    from: { nodeId: "source", port: "report" },
    to: { nodeId: "target", port: "reads" },
  },
});
assert.deepEqual(cyclicSuggestion, []);

const typeOnlyConverterTool = readyTool({
  id: "bioconda::type-only-converter",
  name: "type-only-converter",
  inputs: [{ name: "input", required: true, type: "file" }],
  outputs: [{ name: "output", path: "output.txt", type: "file" }],
});
const typeOnlySuggestions = findOneHopPortConverters({
  input: { name: "reads", type: "file" },
  output: { name: "report", type: "file" },
  tools: [typeOnlyConverterTool],
});
assert.deepEqual(typeOnlySuggestions, []);

const databaseConverterTool = readyTool({
  id: "bioconda::db-converter",
  name: "db-converter",
  inputs: [{ name: "reads", required: true, kind: "reads", format: "fastq", type: "file" }],
  outputs: [{ name: "bam", path: "converted.bam", kind: "alignment_bam", format: "bam", type: "file" }],
});
databaseConverterTool.ruleTemplate.resources = { reference: { type: "database", capabilities: ["alignment_index"] } };
const databaseSuggestions = findOneHopPortConverters({
  input: { name: "reads", kind: "alignment_bam", format: "bam", type: "file" },
  output: { name: "report", kind: "reads", format: "fastq", type: "file" },
  tools: [databaseConverterTool],
});
assert.deepEqual(databaseSuggestions, []);
assert(blockedOneHopPortConverterReasons({
  input: { name: "reads", kind: "alignment_bam", format: "bam", type: "file" },
  output: { name: "report", kind: "reads", format: "fastq", type: "file" },
  tool: databaseConverterTool,
}).includes("database-resource-required"));

const graphDraft = {
  nodes: [
    { id: "source", toolRevisionId: sourceTool.toolRevisionId, inputs: { reads: { fromUpload: 0 } }, params: { min_len: 50 }, runtime: {} },
    { id: "target", toolRevisionId: targetTool.toolRevisionId, inputs: {}, params: { min_len: 50 }, runtime: {} },
  ],
  edges: [
    { id: "source.report->target.reads:0", from: { nodeId: "source", port: "report" }, to: { nodeId: "target", port: "reads" } },
  ],
  outputs: [{ fromStep: "target", output: "report", as: "target_report" }],
};

const patched = buildConverterInsertionPatch({
  converterTool,
  graphDraft,
  request: {
    sourceStepId: "source",
    sourceOutput: "report",
    targetStepId: "target",
    targetInput: "reads",
    converter,
  },
});

assert.equal(patched.nodes.length, 3);
const converterNode = patched.nodes.find((node) => node.toolRevisionId === converterTool.toolRevisionId);
assert(converterNode);
assert.equal(converterNode.id, "sam_to_bam_converter");
assert.deepEqual(converterNode.metadata, {});
assert.deepEqual(converterNode.params, { min_len: 50 });
assert.deepEqual(converterNode.runtime, {});
assert.equal(patched.edges.length, 2);
assert(!patched.edges.some((edge) => edge.from.nodeId === "source" && edge.to.nodeId === "target"));
assert(patched.edges.some((edge) => edge.from.nodeId === "source" && edge.to.nodeId === converterNode.id));
assert(patched.edges.some((edge) => edge.from.nodeId === converterNode.id && edge.to.nodeId === "target"));
assert(patched.edges.every((edge) => edge.audit && edge.audit.source === "auto"));

const generated = graphDraftToGeneratedWorkflowDraft(patched);
const generatedConverter = generated.steps.find((step) => step.id === converterNode.id);
const generatedTarget = generated.steps.find((step) => step.id === "target");
assert.equal(generatedConverter.inputs.reads.fromStep, "source");
assert.equal(generatedConverter.inputs.reads.output, "report");
assert.equal(generatedTarget.inputs.reads.fromStep, converterNode.id);
assert.equal(generatedTarget.inputs.reads.output, "bam");

const validation = validateGeneratedWorkflowDraft(patched, [sourceTool, converterTool, targetTool], { inputCount: 1 });
assert.deepEqual(validation.errors, []);
assert.deepEqual(validation.orderedStepIds, ["source", converterNode.id, "target"]);
assert(!JSON.stringify(patched).includes("converterPath"));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
