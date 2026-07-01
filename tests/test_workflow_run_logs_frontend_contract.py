from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_run_detail_logs_use_cursor_aware_load_more() -> None:
    api = _source("workflow-run-logs-api.ts")
    log_block = _source("workflow-run-log-block.tsx")
    detail_panel = _source("workflow-run-detail-panel.tsx")
    page_api = _source("workflows-page-api.ts")

    assert "export type WorkflowRunLogStream = \"stdout\" | \"stderr\"" in api
    assert "export async function fetchWorkflowRunLogs" in api
    assert "params.set(\"stream\", stream)" in api
    assert "if (cursor) params.set(\"cursor\", cursor)" in api
    assert "`/api/v1/runs/${encodeURIComponent(normalizedRunId)}/logs?${params.toString()}`" in api
    assert "WORKFLOW_RUN_ID_REQUIRED" in api
    assert "fetchWorkflowRunLogs" not in page_api

    assert "export function WorkflowRunLogBlock" in log_block
    assert "initialLog?.nextCursor" in log_block
    assert "fetchWorkflowRunLogs(runId, stream, nextCursor || undefined)" in log_block
    assert "setLines((current) => [...current, ...nextLines])" in log_block
    assert "setNextCursor(page.nextCursor || nextCursor)" in log_block
    assert "RUN_LOG_CURSOR_REQUIRED" in log_block
    assert 'data-testid="workflow-run-log-load-more"' in log_block
    assert "加载新日志" in log_block

    assert 'import { WorkflowRunLogBlock } from "./workflow-run-log-block"' in detail_panel
    assert '<WorkflowRunLogBlock runId={run.runId} stream="stdout" initialLog={detail.logs.stdout} />' in detail_panel
    assert '<WorkflowRunLogBlock runId={run.runId} stream="stderr" initialLog={detail.logs.stderr} />' in detail_panel
    assert "function LogBlock(" not in detail_panel
