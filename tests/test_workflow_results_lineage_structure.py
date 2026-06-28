from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflow_results_page_surfaces_input_lineage_counts_without_payload_leak() -> None:
    model = _source("workflows-page-model.ts")
    api = _source("workflows-page-api.ts")
    page = _source("workflow-results-page.tsx")

    assert "export type WorkflowResultSummary" in model
    assert "inputArtifactCount?: number" in model
    assert "export type WorkflowResultLineageSummary" in model
    assert "lineageSummary?: WorkflowResultLineageSummary" in model
    assert "const WORKFLOW_RESULTS_CACHE_KEY = \"workflow:results\"" in api
    assert "export async function fetchWorkflowResultsList" in api
    assert "`/api/v1/results${refreshQuery(options)}`" in api
    assert "invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY)" in api

    assert "fetchWorkflowResultsList" in page
    assert "const [results, setResults]" in page
    assert "const [summaryError, setSummaryError]" in page
    assert "fetchRunsList({ forceRefresh })" in page
    assert "fetchWorkflowResultsList({ forceRefresh })" in page
    assert "setSummaryError(workflowErrorMessage(summaryErr, \"读取产物摘要失败\"))" in page
    assert "Promise.all([" not in page
    assert "Promise.allSettled([fetchArtifactLifecycleUsage(), fetchArtifactLifecycleControllerTicks()])" in page
    assert "const resultByRunId = useMemo(() =>" in page
    assert "resultByRunId.get(run.runId)" in page
    assert "function ResultLineageSummary" in page
    assert "输出 {result.artifactCount ?? 0}" in page
    assert "输入 {result.inputArtifactCount ?? 0}" in page
    assert "lineage {result.lineageSummary?.edgeCount ?? 0}" in page

    summary_body = page[page.index("function ResultLineageSummary") :]
    assert "storageUri" not in summary_body
    assert "localPath" not in summary_body
    assert ".path" not in summary_body
    assert "lineageEdges" not in summary_body
    assert "payload" not in summary_body


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")
