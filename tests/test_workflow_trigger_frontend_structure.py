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
    backfill_api = _source("workflow-backfill-api.ts")
    page = _source("workflow-trigger-observability-page.tsx")
    panel = _source("workflow-trigger-observability-panel.tsx")
    scheduler_panel = _source("workflow-trigger-scheduler-panel.tsx")
    inbox_panel = _source("workflow-trigger-inbox-panel.tsx")
    results = _source("workflow-results-page.tsx")
    route = TRIGGER_ROUTE.read_text(encoding="utf-8")

    assert TRIGGER_ROUTE.exists()
    assert "WorkflowTriggerObservabilityPage" in route
    assert "WorkflowTrigger" in model
    assert "WorkflowTriggerContract" in model
    assert "WorkflowTriggerAuthoritativeIngress" in model
    assert "WorkflowTriggerOperatorAction" in model
    assert "WorkflowTriggerContractBlocker" in model
    assert "WorkflowTriggerEvent" in model
    assert "WorkflowTriggerDispatchRun" in model
    assert "WorkflowTriggerDispatch" in model
    assert "WorkflowTriggerInboxEvent" in model
    assert "WorkflowTriggerInboxReplayResult" in model
    assert "WorkflowTriggerEventSubmitResult" in model
    assert "WorkflowTriggerReadinessObservation" in model
    assert "WorkflowTriggerReadinessObservationResponse" in model
    assert "WorkflowTriggerSchedulerTick" in model
    assert "WorkflowTriggerSchedulerTickListResponse" in model
    assert "WorkflowTriggerSchedulerRunOnceResult" in model
    assert "WorkflowTriggerSchedulerRunOnceResponse" in model
    assert "controlsExposed?: boolean" in model
    assert "WorkflowRunAdmissionSummary" in model
    assert "waitReasonCode?: string" in model
    assert "admission?: WorkflowRunAdmissionSummary | null" in model
    assert "schemaVersion?: string;" in model
    assert "triggerContract?: WorkflowTriggerContract" in model
    assert "authoritativeIngress?: WorkflowTriggerAuthoritativeIngress" in model
    assert "supportedOperatorActions?: WorkflowTriggerOperatorAction[]" in model
    assert "blockers?: WorkflowTriggerContractBlocker[]" in model
    assert '"manual-event-api"' in model
    assert '"cron-scheduler"' in model
    assert '"webhook-inbox"' in model
    assert '"readiness-api"' in model
    assert '"backfill-launch"' in model
    assert '"unsupported"' in model
    assert '"submit-manual-event"' in model
    assert '"preview-backfill"' in model
    assert '"trigger-disabled"' in model
    assert '"unknown-trigger-source"' in model
    assert "resourceIdentity?: {" in model
    assert "idHash?: string" in model
    assert "resourceUriPresent?: boolean" in model
    assert "resourceId?: string" not in model
    assert "run?: WorkflowTriggerDispatchRun | null" in model
    assert "fetchWorkflowTriggers" in api
    assert "fetchWorkflowTriggerEvents" in api
    assert "fetchWorkflowTriggerInboxEvents" in api
    assert "replayWorkflowTriggerInboxEvent" in api
    assert "submitManualWorkflowTriggerEvent" in api
    assert "fetchWorkflowTriggerReadinessObservation" in api
    assert "fetchWorkflowTriggerSchedulerTicks" in api
    assert "runWorkflowTriggerSchedulerOnce" in api
    assert "requestLocalApiJson<WorkflowTriggerSchedulerRunOnceResponse>" in api
    assert "WORKFLOW_TRIGGER_READINESS_OBSERVATION_CACHE_KEY" in api
    assert "WORKFLOW_TRIGGER_SCHEDULER_TICKS_CACHE_KEY" in api
    assert "/api/v1/workflow-triggers" in api
    assert "/api/v1/workflow-trigger-scheduler/ticks" in api
    assert "/api/v1/workflow-trigger-scheduler/run-once" in api
    assert "/readiness-observation" in api
    assert "/inbox" in api
    assert "/replay" in api
    assert "`/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/events`" in api
    assert 'eventType: "manual"' in api
    assert "manual:web-ui:" in api
    assert 'confirmation: "run-scheduler-once"' in api
    assert 'limit: options.limit || 100' in api
    assert "invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_SCHEDULER_TICKS_CACHE_KEY)" in api
    assert "invalidateWorkflowBackfillLaunchCaches();" in api
    assert api.count("invalidateWorkflowRunResultCaches();") == 3
    assert "export function invalidateWorkflowBackfillLaunchCaches" in backfill_api
    assert "invalidateAsyncCachePrefix(WORKFLOW_BACKFILL_LAUNCHES_CACHE_KEY)" in backfill_api
    assert "invalidateAsyncCachePrefix(WORKFLOW_BACKFILL_LAUNCH_CACHE_KEY)" in backfill_api
    assert "cancelWorkflowBackfillLaunch" in backfill_api
    assert "launchWorkflowTriggerBackfill" in backfill_api
    assert backfill_api.count("invalidateWorkflowBackfillLaunchCaches();") == 2
    assert backfill_api.count("invalidateWorkflowRunResultCaches();") == 2
    assert 'confirmation: "replay-dead-lettered-inbox-event"' in api
    assert "invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_EVENTS_CACHE_KEY)" in api
    assert "invalidateAsyncCachePrefix(WORKFLOW_TRIGGER_INBOX_CACHE_KEY)" in api
    assert "requestLocalApiJson<WorkflowTriggerListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerEventListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerInboxEventListResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerInboxReplayResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerReadinessObservationResponse>" in api
    assert "requestLocalApiJson<WorkflowTriggerSchedulerTickListResponse>" in api
    assert "window.setInterval(() => {" in page
    assert "void loadEvents(true)" in page
    assert "void loadSchedulerTicks(true)" in page
    assert "void loadReadinessObservation(true)" in page
    assert "fetchWorkflowTriggerInboxEvents(selectedTriggerId" in page
    assert "fetchWorkflowTriggerReadinessObservation(selectedTriggerId" in page
    assert "fetchWorkflowTriggerSchedulerTicks({ forceRefresh, limit: 20 })" in page
    assert "runWorkflowTriggerSchedulerOnce({ limit: 100 })" in page
    assert "runningScheduler" in page
    assert "replayWorkflowTriggerInboxEvent(selectedTriggerId, inboxEventId)" in page
    assert "submitManualWorkflowTriggerEvent(triggerId)" in page
    assert "submittingManualTriggerId" in page
    assert "void loadInbox(true)" in page
    assert "readinessObservation={readinessObservation}" in page
    assert "schedulerTicks={schedulerTicks}" in page
    assert "onRunSchedulerOnce={runSchedulerOnce}" in page
    assert "runningScheduler={runningScheduler}" in page
    assert "isReadinessSource" in page
    assert "fetchWorkflowTriggers().catch" in results
    assert 'href="/workflows/results/triggers"' in results
    assert "RunSummary" in panel
    assert "WorkflowTriggerInboxPanel" in panel
    assert "WorkflowTriggerSchedulerPanel" in panel
    assert "workflow_trigger.scheduler_ticks.read" not in panel
    assert "Cron due" in scheduler_panel
    assert "Backfill submitted" in scheduler_panel
    assert "SchedulerMetric" in scheduler_panel
    assert "SchedulerTickLedger" in scheduler_panel
    assert "SchedulerTickLedgerRow" in scheduler_panel
    assert 'data-testid="workflow-trigger-scheduler-ledger"' in scheduler_panel
    assert 'data-testid="workflow-trigger-scheduler-ledger-row"' in scheduler_panel
    assert "tick.evidenceSeq" in scheduler_panel
    assert "tick.evaluatedAt || tick.occurredAt" in scheduler_panel
    assert "cron.dispatchRunCount" in scheduler_panel
    assert "cron.overlapSkipped" in scheduler_panel
    assert "backfills.stateCounts || backfills.reasonCodes" in scheduler_panel
    assert "BadgeSummary" in scheduler_panel
    assert "运行一次 scheduler" in scheduler_panel
    assert "确认运行 scheduler" in scheduler_panel
    assert "Input" in scheduler_panel
    assert "SCHEDULER_RUN_ONCE_CONFIRMATION" in scheduler_panel
    assert "run-scheduler-once" in scheduler_panel
    assert "disabled={confirmation.trim() !== SCHEDULER_RUN_ONCE_CONFIRMATION || runningScheduler}" in scheduler_panel
    assert "只返回聚合证据" in scheduler_panel
    assert "ManualTriggerRunControl" in panel
    assert 'trigger.sourceType === "manual"' in panel
    assert "onSubmitManualTrigger(trigger.triggerId)" in panel
    assert "确认提交 manual trigger" in panel
    assert "immutable trigger event" in panel
    assert "定义已禁用，不能提交运行" in panel
    assert "立即运行" in panel
    assert "ReadinessObservationPanel" in panel
    assert "inboxEvents={inboxEvents}" in panel
    assert "readinessObservation={readinessObservation}" in panel
    assert "observationStateStyle" in panel
    assert "dispatch?.run" in panel
    assert 'href={`/workflows/results/detail?run=${encodeURIComponent(runId)}`}' in panel
    assert "run.status" in panel
    assert "run.stage" in panel
    assert "run.lastUpdatedAt" in panel
    assert "AdmissionSummary" in panel
    assert "admissionWaitLabel" in panel
    assert "admission.availableAt" in panel
    assert "admission.attemptCount" in panel
    assert "admission.maxAttempts" in panel
    assert "ADMISSION_RESOURCES_UNAVAILABLE" in panel
    assert "ADMISSION_WAIT_UNSUPPORTED" not in panel
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
    assert "observedState" in panel
    assert "resourceIdentity" in panel
    assert "watcherAdapter" in panel
    assert "observedChecksum" in panel
    assert "controlsExposed" not in panel
    assert "controlsExposed" not in scheduler_panel
    assert "observation.resourceId ||" not in panel
    assert "observation.resourceId]" not in panel
    assert '"resourceId"' not in panel
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
        "pauseTrigger",
        "suspendTrigger",
        "catchup",
        "concurrencyPolicy",
        "submitCronTrigger",
        "submitWebhookTrigger",
        "submitReadinessTrigger",
        "launchBackfill",
        "replayAll",
        "bulkReplay",
        "raw payload",
        "Advanced Config",
    )
    for forbidden in forbidden_controls:
        assert forbidden not in page
        assert forbidden not in panel
        assert forbidden not in scheduler_panel
        assert forbidden not in inbox_panel


def test_backfill_and_results_pages_link_to_trigger_observability() -> None:
    backfills = _source("workflow-backfill-launches-page.tsx")
    results = _source("workflow-results-page.tsx")

    assert 'href="/workflows/results/triggers"' in backfills
    assert "触发器事件" in backfills
    assert 'href="/workflows/results/triggers"' in results
    assert "fetchWorkflowTriggers" in results
