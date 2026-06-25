from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.contracts.rule_ports import port_compatibility_decision


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_PORT_CASES = ROOT / "tests" / "fixtures" / "semantic_port_cases.json"


def test_frontend_and_backend_port_compatibility_match_golden_cases() -> None:
    cases = json.loads(SEMANTIC_PORT_CASES.read_text(encoding="utf-8"))

    backend = [_public_decision(port_compatibility_decision(case["input"], case["output"])) for case in cases]
    frontend = _frontend_decisions()

    assert backend == [case["expected"] for case in cases]
    assert frontend == backend


def _frontend_decisions() -> list[dict]:
    script = r"""
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

const { portCompatibilityDecision } = require(path.join(
  root,
  "apps",
  "web",
  "app",
  "components",
  "generated-workflow-port-contract.ts"
));
const cases = JSON.parse(fs.readFileSync(path.join(root, "tests", "fixtures", "semantic_port_cases.json"), "utf8"));
const decisions = cases.map((item) => {
  const decision = portCompatibilityDecision(item.input, item.output);
  return {
    compatible: decision.compatible,
    score: decision.score,
    matchedFields: decision.matchedFields,
    genericFields: decision.genericFields,
    advisoryFields: decision.advisoryFields,
    mismatchedField: decision.mismatchedField || "",
    hardChecks: decision.hardChecks,
    advisoryChecks: decision.advisoryChecks,
  };
});
process.stdout.write(JSON.stringify(decisions));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    return json.loads(completed.stdout)


def _public_decision(decision: dict) -> dict:
    return {
        "compatible": decision["compatible"],
        "score": decision["score"],
        "matchedFields": decision["matchedFields"],
        "genericFields": decision["genericFields"],
        "advisoryFields": decision["advisoryFields"],
        "mismatchedField": decision["mismatchedField"],
        "hardChecks": decision["hardChecks"],
        "advisoryChecks": decision["advisoryChecks"],
    }
