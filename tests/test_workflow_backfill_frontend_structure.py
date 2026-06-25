from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
BACKFILL_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "results" / "backfills" / "page.tsx"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_backfill_launches_have_preview_launch_and_cancel_frontend_surface() -> None:
    model = _source("workflow-backfill-model.ts")
    api = _source("workflow-backfill-api.ts")
    page = _source("workflow-backfill-launches-page.tsx")
    launch_control = _source("workflow-backfill-launch-control.tsx")
    panel = _source("workflow-backfill-launch-panel.tsx")
    results = _source("workflow-results-page.tsx")
    route = BACKFILL_ROUTE.read_text(encoding="utf-8")

    assert BACKFILL_ROUTE.exists()
    assert "WorkflowBackfillLaunchesPage" in route
    assert "WorkflowBackfillPreviewRequest" in model
    assert "WorkflowBackfillPreview" in model
    assert "WorkflowBackfillPreviewPartition" in model
    assert "WorkflowBackfillPreviewResponse" in model
    assert "WorkflowBackfillLaunchResponse" in model
    assert 'reprocessBehavior: "none" | "failed" | "completed"' in model
    assert "WorkflowBackfillLaunchList" in model
    assert "WorkflowBackfillLaunchDetail" in model
    assert "WorkflowBackfillPartitionSummary" in model
    assert "WorkflowBackfillConcurrency" in model
    assert "WorkflowRunAdmissionSummary" in model
    assert "waitReasonCode?: string" in model
    assert "admission?: WorkflowRunAdmissionSummary | null" in model
    assert "activeRunCount" in model
    assert "blockedPartitionCount" in model
    assert "blockedReason" in model
    assert "existingState" in model
    assert "reprocessDecision" in model
    assert "operationCapabilities" in model
    assert "WorkflowBackfillCancelResponse" in model
    assert "previewWorkflowTriggerBackfill" in api
    assert "launchWorkflowTriggerBackfill" in api
    assert "fetchWorkflowBackfillLaunches" in api
    assert "fetchWorkflowBackfillLaunch(" in api
    assert "cancelWorkflowBackfillLaunch" in api
    assert "/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/backfill/preview" in api
    assert "/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/backfill/launch" in api
    assert '"launch-backfill"' in api
    assert "/api/v1/workflow-backfill-launches" in api
    assert "/cancel" in api
    assert '"cancel-backfill"' in api
    assert "requestLocalApiJson<WorkflowBackfillPreviewResponse>" in api
    assert "requestLocalApiJson<WorkflowBackfillLaunchResponse>" in api
    assert "requestLocalApiJson<WorkflowBackfillLaunchListResponse>" in api
    assert "requestLocalApiJson<WorkflowBackfillLaunchDetailResponse>" in api
    assert "requestLocalApiJson<WorkflowBackfillCancelResponse>" in api
    assert "WorkflowBackfillLaunchControl" in page
    assert "fetchWorkflowTriggers({ forceRefresh })" in page
    assert "trigger.sourceType === \"backfill\"" in page
    assert "backfillLaunched" in page
    assert "router.replace(`/workflows/results/backfills?launch=${encodeURIComponent(launch.launchId)}`" in page
    assert 'data-testid="workflow-backfill-launch-control"' in launch_control
    assert 'data-testid="workflow-backfill-preview"' in launch_control
    assert 'data-testid="workflow-backfill-launch"' in launch_control
    assert 'data-testid="workflow-backfill-preview-summary"' in launch_control
    assert "previewWorkflowTriggerBackfill(selectedTrigger.triggerId, payload)" in launch_control
    assert "launchWorkflowTriggerBackfill(selectedTrigger.triggerId, {" in launch_control
    assert 'confirmation: "launch-backfill"' in launch_control
    assert "preview?.launchSupported" in launch_control
    assert "preview.truncated" in launch_control
    assert "preview.concurrency?.estimatedBatches" in launch_control
    assert "parseParamsJson" in launch_control
    assert '<SelectItem value="completed">completed</SelectItem>' in launch_control
    assert 'value="all"' not in launch_control
    assert "limit: 50" in page
    assert "window.setInterval(() => void loadDetail(true), 5000)" in page
    assert "cancelWorkflowBackfillLaunch(launchId)" in page
    assert "window.confirm" in page
    assert "fetchWorkflowBackfillLaunches().catch" in results
    assert 'href="/workflows/results/backfills"' in results
    assert 'href={`/workflows/results/detail?run=${encodeURIComponent(partition.runId)}`}' in panel
    assert "detail.concurrency?.enforced ? \"强制\" : \"未强制\"" in panel
    assert "并发受限" in panel
    assert "待提交" in panel
    assert "partition.blockedReason" in panel
    assert "partition.run?.admission" in panel
    assert "AdmissionSummary" in panel
    assert "admissionWaitLabel" in panel
    assert "admission.availableAt" in panel
    assert "admission.attemptCount" in panel
    assert "admission.maxAttempts" in panel
    assert "ADMISSION_RESOURCES_UNAVAILABLE" in panel
    assert "ADMISSION_WAIT_UNSUPPORTED" not in panel
    assert "partition.reprocessDecision" in panel
    assert "partition.existingState?.runStatus" in panel
    assert "reprocessDecisionLabel" in panel
    assert "setLaunches((current) =>" in page
    assert "幂等命中" in panel
    assert "请求取消" in panel
    assert "detail.operationCapabilities?.cancel === true" in panel
    assert "canceling" in panel
    assert "cancel_requested" in panel
    assert "runSpecHash" in panel
    assert "triggerEventId" in panel

    forbidden_controls = ("replayPartition", "deadLetter", "retry failed partitions", "批量取消")
    for forbidden in forbidden_controls:
        assert forbidden not in page
        assert forbidden not in launch_control
        assert forbidden not in panel


def test_run_detail_surfaces_trigger_provenance() -> None:
    provenance_model = _source("workflow-run-trigger-provenance-model.ts")
    provenance_panel = _source("workflow-run-trigger-provenance.tsx")
    panel = _source("workflow-run-detail-panel.tsx")

    assert "export type WorkflowRunTriggerProvenance" in provenance_model
    assert "backfillPartition?:" in provenance_model
    assert "inboxDelivery?:" in provenance_model
    assert "WorkflowRunTriggerProvenancePanel" in provenance_panel
    assert "WorkflowRunTriggerSummary" in provenance_panel
    assert "provenance.source || trigger.source" in provenance_panel
    assert "event.cursor || provenance.cursor || trigger.cursor" in provenance_panel
    assert "event.idempotencyKey || dispatch.idempotencyKey" in provenance_panel
    assert "Payload hash" in provenance_panel
    assert "Raw body" in provenance_panel
    assert "rawBodySha256" in provenance_panel
    assert "Backfill partition" in provenance_panel
    assert "Webhook inbox" in provenance_panel
    assert "payloadJson" not in provenance_panel
    assert "rawBodyBytes" not in provenance_panel
    assert "rawBodyContent" not in provenance_panel
    assert "replayWorkflowTriggerInboxEvent" not in provenance_panel
    assert "WorkflowRunTriggerSummary trigger={trigger}" in panel
    assert "WorkflowRunTriggerProvenancePanel trigger={trigger}" in panel
