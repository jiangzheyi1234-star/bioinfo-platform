from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_design_draft_preserves_external_input_semantics() -> None:
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

const { buildWorkflowDesignDraft } = require(path.join(
  root,
  "apps",
  "web",
  "app",
  "components",
  "workflow-design-draft-model.ts"
));

const graphDraft = {
  nodes: [
    {
      id: "qc",
      toolRevisionId: "tool_qc#1",
      inputs: { reads: { fromUpload: 0 } },
      metadata: {},
      params: {},
      runtime: {},
    },
  ],
  edges: [],
  outputs: [],
};
const existingDraft = {
  contractVersion: "workflow-design-draft-v1",
  engine: "snakemake",
  metadata: { name: "Existing", description: "", projectId: "proj_semantics", tags: [] },
  inputs: [
    {
      id: "input",
      role: "input",
      type: "file",
      kind: "reads",
      path: "inputs/reads.fastq",
      filename: "reads.fastq",
      mimeType: "text/x-fastq",
      data: "EDAM:data_2044",
      format: "EDAM:format_1930",
      operation: "EDAM:operation_0335",
      resource: "reference_sequence",
      metadata: { reviewer: "alice" },
    },
  ],
  nodes: [],
  edges: [],
  resources: { bindings: {}, metadata: {} },
  outputs: [],
  provenance: { createdBy: "test" },
};

const draft = buildWorkflowDesignDraft({
  graphDraft,
  files: [{ name: "reads-renamed.fastq", type: "" }],
  projectId: "proj_semantics",
  resourceBindings: {},
  name: "Semantic input draft",
  existingDraft,
});

assert.deepEqual(draft.inputs[0], {
  id: "input",
  role: "input",
  type: "file",
  kind: "reads",
  path: "inputs/reads-renamed.fastq",
  filename: "reads-renamed.fastq",
  mimeType: "text/x-fastq",
  data: "EDAM:data_2044",
  format: "EDAM:format_1930",
  operation: "EDAM:operation_0335",
  resource: "reference_sequence",
  metadata: { reviewer: "alice" },
});
assert.deepEqual(draft.nodes[0].inputs.reads, { fromInput: "input" });
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
