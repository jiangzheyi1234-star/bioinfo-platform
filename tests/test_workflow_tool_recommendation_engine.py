from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operation_match_boosts_recommendation_without_becoming_hard_requirement() -> None:
    recommendations = _engine_recommendations()

    assert [item["candidate"]["profileId"] for item in recommendations] == [
        "matching-operation",
        "different-operation",
    ]
    assert recommendations[0]["confidence"] > recommendations[1]["confidence"]
    assert recommendations[0]["advisoryFields"] == ["operation"]
    assert "operation:advisory-compatible" in recommendations[0]["advisoryChecks"]
    assert any("advisory operation:advisory-compatible" in item for item in recommendations[0]["evidence"])
    assert recommendations[1]["advisoryFields"] == []
    assert recommendations[1]["matchedFields"] == ["data", "format", "resource"]


def test_resource_conflict_blocks_even_when_operation_matches() -> None:
    recommendations = _engine_recommendations(include_resource_conflict=True)
    profile_ids = [item["candidate"]["profileId"] for item in recommendations]

    assert "resource-conflict" not in profile_ids
    assert profile_ids[0] == "matching-operation"


def _engine_recommendations(include_resource_conflict: bool = False) -> list[dict]:
    script = f"""
const path = require("path");
const ts = require(path.join(process.cwd(), "apps", "web", "node_modules", "typescript"));

require.extensions[".ts"] = function(module, filename) {{
  const source = require("fs").readFileSync(filename, "utf8");
  const output = ts.transpileModule(source, {{
    compilerOptions: {{
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    }},
    fileName: filename,
  }}).outputText;
  module._compile(output, filename);
}};

const {{ workflowRecommendationsFromCapabilityGraph }} = require(path.join(
  process.cwd(),
  "apps",
  "web",
  "app",
  "components",
  "workflow-tool-recommendation-engine.ts"
));

const outputPort = {{
  type: "file",
  data: "EDAM:data_2044",
  format: "EDAM:format_1930",
  operation: "EDAM:operation_0335",
  resource: "sample_reads",
}};

function profile(id) {{
  return {{
    id,
    kind: "ToolProfile",
    profileId: id,
    toolRevisionId: `${{id}}@1`,
    agentSelectable: true,
    capabilityBundle: {{
      capabilityBundleVersion: "capability-bundle-v1",
      capabilityId: `cap_${{id}}`,
      toolRevisionId: `${{id}}@1`,
      validationEvidence: {{ status: "passed" }},
    }},
  }};
}}

function input(id, operation, resource = "sample_reads") {{
  return {{
    id: `input_${{id}}`,
    kind: "InputPort",
    name: "reads",
    type: "file",
    data: "data_2044",
    format: "fastq",
    operation,
    resource,
    required: true,
  }};
}}

const nodes = [
  profile("different-operation"),
  input("different-operation", "operation_2421"),
  profile("matching-operation"),
  input("matching-operation", "operation_0335"),
];
const edges = [
  {{ from: "different-operation", to: "input_different-operation", kind: "consumes" }},
  {{ from: "matching-operation", to: "input_matching-operation", kind: "consumes" }},
];

if ({str(include_resource_conflict).lower()}) {{
  nodes.push(profile("resource-conflict"), input("resource-conflict", "operation_0335", "taxonomy_database"));
  edges.push({{ from: "resource-conflict", to: "input_resource-conflict", kind: "consumes" }});
}}

const result = workflowRecommendationsFromCapabilityGraph({{
  graphEdges: edges,
  outputPort,
  page: 1,
  pageSize: 10,
  profileNodes: nodes,
  query: "",
}});
process.stdout.write(JSON.stringify(result.items));
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
