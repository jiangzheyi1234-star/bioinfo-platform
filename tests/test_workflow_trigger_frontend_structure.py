from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
TRIGGER_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "results" / "triggers" / "page.tsx"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_trigger_events_have_read_only_frontend_surface() -> None:
    model = _source("workflow-trigger-model.ts")
    api = _source("workflow-trigger-api.ts")
    page = _source("workflow-trigger-observability-page.tsx")
    panel = _source("workflow-trigger-observability-panel.tsx")
    inbox_panel = _source("workflow-trigger-inbox-panel.tsx")
    results = _source("workflow-results-page.tsx")
    route = TRIGGER_ROUTE.read_text(encoding="utf-8")

    assert TRIGGER_ROUTE.exists()
    assert "WorkflowTriggerObservabilityPage" in route
    assert "WorkflowTrigger" in model
    assert "WorkflowTriggerEvent" in model
    assert "WorkflowTriggerDispatchRun" in model
    assert "WorkflowTriggerDispatch" in model
    assert "WorkflowTriggerInboxEvent" in model
    assert "WorkflowTriggerInboxReplayResult" in model
    assert "run?: WorkflowTriggerDispatchRun | null" in model
    assert "fetchWorkflowTriggers" in api
    assert "fetchWorkflowTriggerEvents" in api
    assert "fetchWorkflowTriggerInboxEvents" in api
    assert "replayWorkflowTriggerInboxEvent" in api
    assert "/api/v1/workflow-triggers" in api
    assert "/inbox" in api
    assert "/replay" in api
    assert 'confirmation: "replay-dead-lettered-inbox-event"' in api
    assert "invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_EVENTS_CACHE_KEY)" in api
    assert "invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_INBOX_CACHE_KEY)" in api
    assert "requestLocalApiJson<WorkflowTriggerListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerEventListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerInboxEventListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerInboxReplayResponse>" in api
    assert "window.setInterval(() => {" in page
    assert "void loadEvents(true)" in page
    assert "fetchWorkflowTriggerInboxEvents(selectedTriggerId" in page
    assert "replayWorkflowTriggerInboxEvent(selectedTriggerId, inboxEventId)" in page
    assert "void loadInbox(true)" in page
    assert "fetchWorkflowTriggers().catch" in results
    assert 'href="/workflows/results/triggers"' in results
    assert "RunSummary" in panel
    assert "WorkflowTriggerInboxPanel" in panel
    assert "inboxEvents={inboxEvents}" in panel
    assert "dispatch?.run" in panel
    assert 'href={`/workflows/results/detail?run=${encodeURIComponent(runId)}`}' in panel
    assert "run.status" in panel
    assert "run.stage" in panel
    assert "run.lastUpdatedAt" in panel
    assert "runStatusStyle" in panel
    assert "payloadHash" in panel
    assert "eventContext" in panel
    assert "resource" in panel
    assert "triggerSpecLabel" in panel
    assert "triggerSpecSummary" in panel
    assert "triggerScheduleLabel" in panel
    assert "triggerInboxLabel" in panel
    assert "triggerPartitionPolicyLabel" in panel
    assert "triggerResourceLabel" in panel
    assert "triggerRunSpecLabel" in panel
    assert "dispatchLabel" in panel
    assert "database-ready" in panel
    assert "definition enabled" in panel
    assert "scheduledAt" in panel
    assert "scheduleVersion" in panel
    assert "scheduleItems" in panel
    assert "backfillItems" in panel
    assert "shortIdentity(event.externalEventId" in panel
    assert "shortIdentity(event.cursor" in panel
    assert "stringValue(record.errorType) || \"dispatch error\"" in panel
    assert "Webhook inbox" in inbox_panel
    assert "Dead-letter" in inbox_panel
    assert "onReplayInboxEvent(event.inboxEventId)" in inbox_panel
    assert 'event.state === "dead_lettered"' in inbox_panel
    assert "payloadSizeBytes" in inbox_panel
    assert "rawBodySha256" in inbox_panel
    assert "rawHeaderNames" in inbox_panel
    assert "signatureState" in inbox_panel
    assert "resource.uri" not in panel
    assert '"actor"' not in panel
    assert "trigger.createdBy" not in panel
    assert "raw payload" not in inbox_panel.lower()
    assert "raw body bytes" not in inbox_panel.lower()
    assert "bulk replay" not in inbox_panel.lower()

    forbidden_controls = (
        "createWorkflowTrigger",
        "submitWorkflowTrigger",
        "pauseTrigger",
        "suspendTrigger",
        "catchup",
        "concurrencyPolicy",
        "replayAll",
        "bulkReplay",
        "raw payload",
        "Advanced Config",
    )
    for forbidden in forbidden_controls:
        assert forbidden not in page
        assert forbidden not in panel
        assert forbidden not in inbox_panel


def test_backfill_and_results_pages_link_to_trigger_observability() -> None:
    backfills = _source("workflow-backfill-launches-page.tsx")
    results = _source("workflow-results-page.tsx")

    assert 'href="/workflows/results/triggers"' in backfills
    assert "触发器事件" in backfills
    assert 'href="/workflows/results/triggers"' in results
    assert "fetchWorkflowTriggers" in results
