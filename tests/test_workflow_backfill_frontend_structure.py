from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
BACKFILL_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "results" / "backfills" / "page.tsx"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_backfill_launches_have_read_only_frontend_surface() -> None:
    model = _source("workflow-backfill-model.ts")
    api = _source("workflow-backfill-api.ts")
    page = _source("workflow-backfill-launches-page.tsx")
    panel = _source("workflow-backfill-launch-panel.tsx")
    results = _source("workflow-results-page.tsx")
    route = BACKFILL_ROUTE.read_text(encoding="utf-8")

    assert BACKFILL_ROUTE.exists()
    assert "WorkflowBackfillLaunchesPage" in route
    assert "WorkflowBackfillLaunchList" in model
    assert "WorkflowBackfillLaunchDetail" in model
    assert "WorkflowBackfillPartitionSummary" in model
    assert "WorkflowBackfillConcurrency" in model
    assert "fetchWorkflowBackfillLaunches" in api
    assert "fetchWorkflowBackfillLaunch(" in api
    assert "/api/v1/workflow-backfill-launches" in api
    assert "requestLocalApiJson<WorkflowBackfillLaunchListResponse>" in api
    assert "requestLocalApiJson<WorkflowBackfillLaunchDetailResponse>" in api
    assert "limit: 50" in page
    assert "window.setInterval(() => void loadDetail(true), 5000)" in page
    assert "fetchWorkflowBackfillLaunches().catch" in results
    assert 'href="/workflows/results/backfills"' in results
    assert 'href={`/workflows/results/detail?run=${encodeURIComponent(partition.runId)}`}' in panel
    assert "detail.concurrency?.enforced ? \"强制\" : \"未强制\"" in panel
    assert "幂等命中" in panel
    assert "runSpecHash" in panel
    assert "triggerEventId" in panel

    forbidden_controls = ("cancelBackfill", "replayPartition", "deadLetter", "retry failed partitions", "批量取消")
    for forbidden in forbidden_controls:
        assert forbidden not in page
        assert forbidden not in panel


def test_run_detail_surfaces_trigger_provenance() -> None:
    model = _source("workflows-page-model.ts")
    panel = _source("workflow-run-detail-panel.tsx")

    assert "export type WorkflowRunTrigger" in model
    assert "trigger?: WorkflowRunTrigger | null" in model
    assert "const trigger = run.trigger" in panel
    assert "Trigger" in panel
    assert "trigger.triggerId" in panel
    assert "trigger.triggerEventId" in panel
