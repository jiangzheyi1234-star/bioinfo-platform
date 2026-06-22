from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_editor_history_commits_undoes_and_replaces() -> None:
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
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: filename,
  }).outputText;
  module._compile(output, filename);
};

const {
  commitWorkflowEditorHistory,
  createWorkflowEditorHistory,
  redoWorkflowEditorHistory,
  replaceWorkflowEditorHistory,
  undoWorkflowEditorHistory,
} = require(path.join(root, "apps", "web", "app", "components", "generated-workflow-history.ts"));

const initial = { nodes: ["a"] };
const next = { nodes: ["a", "b"] };
const latest = { nodes: ["a", "b", "c"] };
let history = createWorkflowEditorHistory(initial);
history = commitWorkflowEditorHistory(history, next);
history = commitWorkflowEditorHistory(history, latest);
assert.deepEqual(history.past, [initial, next]);
assert.equal(history.present, latest);
assert.deepEqual(history.future, []);

history = undoWorkflowEditorHistory(history);
assert.equal(history.present, next);
assert.deepEqual(history.future, [latest]);
history = redoWorkflowEditorHistory(history);
assert.equal(history.present, latest);
assert.deepEqual(history.future, []);
assert.equal(redoWorkflowEditorHistory(history), history);

history = undoWorkflowEditorHistory(history);
const branched = { nodes: ["branch"] };
history = commitWorkflowEditorHistory(history, branched);
assert.equal(history.present, branched);
assert.deepEqual(history.future, []);

let limited = createWorkflowEditorHistory({ nodes: ["0"] });
limited = commitWorkflowEditorHistory(limited, { nodes: ["1"] }, 2);
limited = commitWorkflowEditorHistory(limited, { nodes: ["2"] }, 2);
limited = commitWorkflowEditorHistory(limited, { nodes: ["3"] }, 2);
assert.deepEqual(limited.past.map((item) => item.nodes[0]), ["1", "2"]);

const replacement = { nodes: ["fresh"] };
history = replaceWorkflowEditorHistory(history, replacement);
assert.deepEqual(history, { past: [], present: replacement, future: [] });
assert.equal(undoWorkflowEditorHistory(history), history);
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
