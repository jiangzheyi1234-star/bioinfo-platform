from __future__ import annotations

from pathlib import Path


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


def test_workflow_page_artifact_input_state_and_ui_are_safe() -> None:
    hook = _read("apps/web/app/components/use-workflows-page-state.ts")
    ui = _read("apps/web/app/components/workflows-page-ui.tsx")
    detail_page = _read("apps/web/app/components/workflow-detail-page.tsx")

    assert "const [artifactInputs, setArtifactInputs]" in hook
    assert "const [artifactInputRunId, setArtifactInputRunId]" in hook
    assert "async function loadArtifactInputRun" in hook
    assert "function selectArtifactInput" in hook
    assert "function clearArtifactInputs" in hook
    assert "setSampleUploads([])" in _function_body(hook, "selectArtifactInput")
    assert "setFiles([])" in _function_body(hook, "selectArtifactInput")
    assert "clearArtifactInputs()" in _function_body(hook, "updateFiles")
    assert "clearArtifactInputs()" in _function_body(hook, "loadSampleData")
    assert "role: workflowInputRoleDefault(selectedWorkflow)" in hook

    assert "artifactInputDetail={state.artifactInputDetail}" in detail_page
    assert "artifactInputs={state.artifactInputs}" in detail_page
    assert "runHistory={state.runHistory}" in detail_page
    assert "onArtifactInputRunChange" in detail_page
    assert "onArtifactInputSelect={state.selectArtifactInput}" in detail_page

    picker_body = _function_body(ui, "WorkflowFilePicker")
    assert "历史结果产物" in picker_body
    assert "选择已完成运行的 artifact 作为输入" in picker_body
    assert "completedRuns.map" in picker_body
    assert "artifactCandidates.map" in picker_body
    assert "artifactInputLabel(artifact)" in picker_body
    assert "artifactInputRunLabel(artifact)" in picker_body
    assert "storageUri" not in picker_body
    assert "cacheKey" not in picker_body
    assert ".path" not in picker_body


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
