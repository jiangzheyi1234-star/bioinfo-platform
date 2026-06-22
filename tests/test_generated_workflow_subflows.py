from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_subflow_metadata_round_trips_through_generated_and_design_drafts() -> None:
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
  generatedWorkflowDraftToGraphDraft,
  graphDraftToGeneratedWorkflowDraft,
  graphNodeMetadataWithSubflow,
  graphNodeSubflowId,
  graphNodeSubflowLabel,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-model.ts"));
const {
  buildWorkflowDesignDraft,
  workflowDesignDraftToGraphDraft,
} = require(path.join(root, "apps", "web", "app", "components", "workflow-design-draft-model.ts"));

const subflowMetadata = graphNodeMetadataWithSubflow({ owner: "ops" }, "QC Stage");
assert.deepEqual(subflowMetadata, { owner: "ops", uiSubflowId: "qc_stage", uiSubflowLabel: "QC Stage" });
assert.equal(graphNodeSubflowId({ metadata: subflowMetadata }), "qc_stage");
assert.equal(graphNodeSubflowLabel({ metadata: subflowMetadata }), "QC Stage");
assert.deepEqual(graphNodeMetadataWithSubflow(subflowMetadata, " "), { owner: "ops" });

const graphDraft = {
  nodes: [
    { id: "qc", toolRevisionId: "tool#qc", inputs: {}, metadata: subflowMetadata, params: {}, runtime: {} },
  ],
  edges: [],
  outputs: [],
};
const generatedDraft = graphDraftToGeneratedWorkflowDraft(graphDraft);
assert.deepEqual(generatedDraft.steps[0].metadata, subflowMetadata);
assert.deepEqual(generatedWorkflowDraftToGraphDraft(generatedDraft).nodes[0].metadata, subflowMetadata);

const existingDesignDraft = {
  contractVersion: "workflow-design-draft-v1",
  engine: "snakemake",
  metadata: { name: "Existing", description: "", projectId: "proj_subflow", tags: [] },
  inputs: [],
  nodes: [
    {
      id: "qc",
      toolRevisionId: "tool#qc",
      inputs: {},
      params: {},
      runtime: {},
      resources: {},
      outputs: {},
      metadata: { reviewer: "alice" },
      provenance: { source: "test" },
    },
  ],
  edges: [],
  resources: { bindings: {}, metadata: {} },
  outputs: [],
  provenance: { createdBy: "test" },
};
const designDraft = buildWorkflowDesignDraft({
  graphDraft,
  files: [],
  projectId: "proj_subflow",
  resourceBindings: {},
  name: "Subflow draft",
  existingDraft: existingDesignDraft,
});
assert.deepEqual(designDraft.nodes[0].metadata, {
  reviewer: "alice",
  owner: "ops",
  uiSubflowId: "qc_stage",
  uiSubflowLabel: "QC Stage",
});
assert.deepEqual(workflowDesignDraftToGraphDraft(designDraft).nodes[0].metadata, designDraft.nodes[0].metadata);
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
