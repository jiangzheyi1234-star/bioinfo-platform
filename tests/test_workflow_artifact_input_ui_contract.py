from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_artifact_input_submit_contract_is_fail_closed() -> None:
    model = _read("apps/web/app/components/workflows-page-model.ts")
    run_spec = _read("apps/web/app/components/workflow-pipeline-run-spec.ts")
    api = _read("apps/web/app/components/workflows-page-api.ts")

    assert "export type WorkflowArtifactRunInput" in run_spec
    assert "artifactInputs?: WorkflowArtifactRunInput[]" in run_spec
    assert "PIPELINE_INPUT_SOURCE_AMBIGUOUS" in run_spec
    assert "PIPELINE_INPUT_SOURCE_REQUIRED" in run_spec
    assert "artifactId: artifact.artifactId" in run_spec
    assert "upstreamRunId: artifact.upstreamRunId" in run_spec
    assert "uploadId: upload.uploadId" in run_spec
    assert "sampleDataPrepProofFromUploads(uploads)" in run_spec
    assert "runSpec.sampleDataPrepProof = samplePrepProof" in run_spec
    assert "buildPipelineRunSpec" not in model

    submit_body = _function_body(api, "submitPipelineWorkflowRun")
    assert "artifactInputs?: WorkflowArtifactRunInput[]" in api
    assert "const selectedArtifactInputs = artifactInputs || []" in submit_body
    assert "const sourceCount = [files.length, selectedSampleUploads.length, selectedArtifactInputs.length]" in submit_body
    assert "PIPELINE_INPUT_SOURCE_AMBIGUOUS" in submit_body
    assert "PIPELINE_INPUT_SOURCE_REQUIRED" in submit_body
    assert submit_body.index("const sourceCount") < submit_body.index("uploadWorkflowFile(file, server.serverId)")
    assert "artifactInputs: selectedArtifactInputs" in submit_body
    assert "storageUri" not in _function_body(run_spec, "buildPipelineRunSpec")
    assert "cacheKey" not in _function_body(run_spec, "buildPipelineRunSpec")
    assert "artifactKey" not in _function_body(run_spec, "buildPipelineRunSpec")


def test_workflow_page_artifact_input_state_and_ui_are_safe() -> None:
    hook = _read("apps/web/app/components/use-workflows-page-state.ts")
    ui = _read("apps/web/app/components/workflows-page-ui.tsx")
    detail_page = _read("apps/web/app/components/workflow-detail-page.tsx")

    assert "const [artifactInputs, setArtifactInputs]" in hook
    assert "const [artifactInputRunId, setArtifactInputRunId]" in hook
    assert "async function loadArtifactInputRun" in hook
    assert "function selectArtifactInput" in hook
    assert "function removeArtifactInput" in hook
    assert "function clearArtifactInputs" in hook
    assert "setArtifactInputs([])" not in _function_body(hook, "loadArtifactInputRun")
    assert 'from "./workflow-artifact-input-recommendation"' in hook
    assert "setSampleUploads([])" in _function_body(hook, "selectArtifactInput")
    assert "setFiles([])" in _function_body(hook, "selectArtifactInput")
    assert "setArtifactInputs((current) =>" in _function_body(hook, "selectArtifactInput")
    assert "current.some((item) => item.artifactId === artifact.artifactId)" in _function_body(hook, "selectArtifactInput")
    assert "clearArtifactInputs()" in _function_body(hook, "updateFiles")
    assert "clearArtifactInputs()" in _function_body(hook, "loadSampleData")
    assert "applyWorkflowInputRoles(selectedWorkflow" in _function_body(hook, "selectArtifactInput")
    assert "applyWorkflowInputRoles(" in _function_body(hook, "removeArtifactInput")

    assert "artifactInputDetail={state.artifactInputDetail}" in detail_page
    assert "artifactInputs={state.artifactInputs}" in detail_page
    assert "runHistory={state.runHistory}" in detail_page
    assert "onArtifactInputRunChange" in detail_page
    assert "onArtifactInputSelect={state.selectArtifactInput}" in detail_page
    assert "onArtifactInputRemove={state.removeArtifactInput}" in detail_page

    picker_body = _function_body(ui, "WorkflowFilePicker")
    assert "历史结果产物篮" in picker_body
    assert "已完成运行 artifact" in picker_body
    assert "completedRuns.map" in picker_body
    assert "rankedArtifactCandidates.map" in picker_body
    assert "selectedArtifactIds" in picker_body
    assert "rankArtifactInputCandidates(selectedWorkflow, artifactInputs.length" in picker_body
    assert 'value="__none__"' in picker_body
    assert "onValueChange={(value) => onArtifactInputSelect(value === \"__none__\" ? \"\" : value)}" in picker_body
    assert "artifactSelectDisabled = !artifactInputRunId || artifactInputLoading || availableArtifactCandidates.length === 0" in picker_body
    assert "artifactInputLabel(artifact)" in picker_body
    assert "artifactInputRunLabel(artifact)" in picker_body
    assert "const outputLabel = safeArtifactOutputLabel(artifact.artifactKey)" in ui
    assert 'outputLabel ? `output ${outputLabel}` : ""' in ui
    assert '推荐 ${recommendation.targetRole}' in picker_body
    assert '手动确认 ${recommendation.targetRole}' in picker_body
    assert 'artifact.upstreamRunId ? `from ${shortId(artifact.upstreamRunId)}` : ""' in ui
    assert "onArtifactInputRemove(artifact.artifactId)" in picker_body
    assert "storageUri" not in picker_body
    assert "cacheKey" not in picker_body
    assert ".path" not in picker_body


def test_artifact_input_role_recommendation_is_advisory_and_safe() -> None:
    recommendation = _read("apps/web/app/components/workflow-artifact-input-recommendation.ts")

    assert "rankArtifactInputCandidates" in recommendation
    assert "recommendArtifactForRole" in recommendation
    assert "safeArtifactOutputLabel" in recommendation
    assert 'decision: "recommended" | "manual"' in recommendation
    assert "workflowInputRoleForIndex" in recommendation
    assert 'record.group === "input" || record.kind === "input"' in recommendation
    assert 'score >= 3 ? "recommended" : "manual"' in recommendation
    assert "artifact.artifactKey" in recommendation
    assert "output port evidence" in recommendation
    assert "right.recommendation.score - left.recommendation.score ||\n        left.index - right.index" in recommendation
    assert 'roleTokens: ["reads", "read", "sequence", "sequences"],' in recommendation
    assert "storageUri" not in recommendation
    assert "cacheKey" not in recommendation
    assert "path" not in recommendation


def test_artifact_input_role_recommendation_behavior() -> None:
    result = _run_recommendation_helper()

    assert result["metadata"][0]["artifact"]["artifactId"] == "art_metadata"
    assert result["metadata"][0]["recommendation"]["decision"] == "recommended"
    assert result["portLabel"][0]["artifact"]["artifactId"] == "art_report"
    assert result["portLabel"][0]["recommendation"]["decision"] == "recommended"
    assert "output port evidence" in result["portLabel"][0]["recommendation"]["reasons"]
    assert result["reads"][0]["artifact"]["artifactId"] == "art_fastq"
    assert result["reads"][0]["recommendation"]["decision"] == "recommended"
    assert result["unsafeLabel"][0]["recommendation"]["decision"] == "manual"
    assert [item["artifact"]["artifactId"] for item in result["manual"]] == ["art_z", "art_a"]
    assert all(item["recommendation"]["decision"] == "manual" for item in result["manual"])


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    if start == -1:
        marker = f"async function {name}"
        start = source.find(marker)
    if start == -1:
        marker = f"export function {name}"
        start = source.find(marker)
    if start == -1:
        marker = f"export async function {name}"
        start = source.find(marker)
    if start == -1:
        raise AssertionError(f"missing function {name}")
    params_start = source.find("(", start)
    if params_start == -1:
        raise AssertionError(f"missing parameters for {name}")
    param_depth = 0
    params_end = -1
    for index in range(params_start, len(source)):
        char = source[index]
        if char == "(":
            param_depth += 1
        elif char == ")":
            param_depth -= 1
            if param_depth == 0:
                params_end = index
                break
    if params_end == -1:
        raise AssertionError(f"unterminated parameters for {name}")
    brace = source.find("{", params_end)
    if brace == -1:
        raise AssertionError(f"missing body for {name}")
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"unterminated body for {name}")


def _run_recommendation_helper() -> dict[str, object]:
    helper_path = (ROOT / "apps/web/app/components/workflow-artifact-input-recommendation.ts").as_posix()
    script = f"""
const fs = require("fs");
const ts = require("typescript");
const source = fs.readFileSync("{helper_path}", "utf8");
const compiled = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }}
}}).outputText;
const moduleObj = {{ exports: {{}} }};
new Function("exports", "module", compiled)(moduleObj.exports, moduleObj);
const rank = moduleObj.exports.rankArtifactInputCandidates;
const workflow = (roles) => ({{ uiSchema: {{ graph: {{ nodes: roles.map((role) => ({{ kind: "input", role }})) }} }} }});
const result = {{
  metadata: rank(workflow(["metadata"]), 0, [
    {{ artifactId: "art_fastq", kind: "reads", mimeType: "application/gzip", sizeBytes: 1 }},
    {{ artifactId: "art_metadata", kind: "table", mimeType: "text/tab-separated-values", sizeBytes: 1 }},
  ]),
  portLabel: rank(workflow(["metadata"]), 0, [
    {{ artifactId: "art_report", artifactKey: "metadata", kind: "report", mimeType: "text/html", sizeBytes: 1 }},
    {{ artifactId: "art_plain", kind: "report", mimeType: "text/html", sizeBytes: 1 }},
  ]),
  reads: rank(workflow(["reads"]), 0, [
    {{ artifactId: "art_table", kind: "table", mimeType: "text/tab-separated-values", sizeBytes: 1 }},
    {{ artifactId: "art_fastq", kind: "reads", mimeType: "application/gzip", sizeBytes: 1 }},
  ]),
  unsafeLabel: rank(workflow(["metadata"]), 0, [
    {{ artifactId: "art_secret", artifactKey: "metadata/secret", kind: "report", mimeType: "text/html", sizeBytes: 1 }},
  ]),
  manual: rank(workflow(["input"]), 0, [
    {{ artifactId: "art_z", kind: "report", mimeType: "text/html", sizeBytes: 1 }},
    {{ artifactId: "art_a", kind: "table", mimeType: "text/tab-separated-values", sizeBytes: 1 }},
  ]),
}};
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT / "apps/web",
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)
