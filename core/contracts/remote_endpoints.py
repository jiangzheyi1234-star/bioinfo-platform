from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any
from urllib.parse import quote, urlencode

from core.contracts.workflow_design_remote_endpoints import WORKFLOW_DESIGN_REMOTE_ENDPOINT_SPECS


class RemoteEndpointContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RemoteEndpoint:
    endpoint_id: str
    method: str
    path_template: str
    operation_id: str
    governance_action: str | None
    request_schema: str | None
    response_schema: str
    cache_scope: str
    query_params: tuple[str, ...] = ()
    invalidates: tuple[str, ...] = ()
    response_key: str = "data"
    response_item_key: str | None = None
    accepted_statuses: tuple[int, ...] = (200,)

    @property
    def path_params(self) -> tuple[str, ...]:
        names = [
            str(field_name)
            for _, field_name, _, _ in Formatter().parse(self.path_template)
            if field_name
        ]
        return tuple(dict.fromkeys(names))


def _workflow_trigger_command_endpoint(
    endpoint_id: str,
    path_template: str,
    operation_id: str,
    governance_action: str,
    request_schema: str,
    response_schema: str,
    *,
    invalidates: tuple[str, ...] = (),
    response_key: str = "data",
    accepted_statuses: tuple[int, ...] = (200,),
) -> RemoteEndpoint:
    return RemoteEndpoint(
        endpoint_id=endpoint_id,
        method="POST",
        path_template=path_template,
        operation_id=operation_id,
        governance_action=governance_action,
        request_schema=request_schema,
        response_schema=response_schema,
        cache_scope="workflow-trigger-command",
        invalidates=invalidates,
        response_key=response_key,
        accepted_statuses=accepted_statuses,
    )


RUN_LIST = "run.list"
RUN_READ = "run.read"
RUN_EVENTS_READ = "run.events.read"
RUN_EXECUTION_CONTEXT_READ = "run.execution_context.read"
RUN_ATTEMPTS_READ = "run.attempts.read"
RUN_LOGS_READ = "run.logs.read"
RUN_RESULTS_READ = "run.results.read"
RUN_RULES_READ = "run.rules.read"
RUN_FAILURE_LOCATOR_READ = "run.failure_locator.read"
RUN_CANCEL = "run.cancel"
RUN_RETRY = "run.retry"
RUN_RESUME = "run.resume"
RUN_RULE_RETRY = "run.rule_retry"
RUN_RULE_OUTPUT_INVALIDATION_APPLY = "run.rule_output_invalidation.apply"
RUN_RULE_CACHE_RESTORE_PINS_PREPARE = "run.rule_cache_restore.pins.prepare"
RUN_RULE_CACHE_RESTORE_PINS_APPLY = "run.rule_cache_restore.pins.apply"
RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE = "run.rule_cache_restore.staged_files.prepare"
RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY = "run.rule_cache_restore.staged_files.apply"
RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE = "run.rule_cache_restore.final_outputs.prepare"
RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY = "run.rule_cache_restore.final_outputs.apply"
RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE = "run.rule_cache_restore.adoption.prepare"
RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY = "run.rule_cache_restore.adoption.apply"
WORKFLOW_REVISION_READ = "workflow_revision.read"
RESULT_LIST = "result.list"
RESULT_READ = "result.read"
RESULT_PREVIEW_READ = "result.preview.read"
RESULT_AUDIT_READ = "result.audit.read"
RESULT_PACKAGE_EXPORT_LIST = "result.package_export.list"
RESULT_PACKAGE_EXPORT = "result.package.export"
RESULT_PACKAGE_RETIRE = "result.package.retire"
RESULT_PACKAGE_BYTE_GC_PREVIEW = "result.package.byte_gc.preview"
RESULT_PACKAGE_BYTE_GC_RUN = "result.package.byte_gc.run"
ARTIFACT_LIFECYCLE_USAGE_READ = "artifact.lifecycle.usage.read"
ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ = "artifact.lifecycle.controller_ticks.read"
ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE = "artifact.lifecycle.controller.run_once"
ARTIFACT_LIFECYCLE_GC_PREVIEW = "artifact.gc.preview"
ARTIFACT_LIFECYCLE_GC_RUN = "artifact.gc.run"
ARTIFACT_CACHE_ENTRIES_READ = "artifact.cache.entries.read"
ARTIFACT_CACHE_PINS_READ = "artifact.cache_pins.read"
ARTIFACT_CACHE_PIN_RETAIN = "artifact.cache_pin.retain"
ARTIFACT_CACHE_PIN_RELEASE = "artifact.cache_pin.release"
ARTIFACT_CACHE_LOOKUP = "artifact.cache.lookup"
WORKFLOW_TRIGGER_LIST = "workflow_trigger.list"
WORKFLOW_TRIGGER_CREATE = "workflow_trigger.create"
WORKFLOW_TRIGGER_EVENTS_READ = "workflow_trigger.events.read"
WORKFLOW_TRIGGER_EVENT_SUBMIT = "workflow_trigger.event.submit"
WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ = "workflow_trigger.readiness_observation.read"
WORKFLOW_TRIGGER_READINESS_SUBMIT = "workflow_trigger.readiness.submit"
WORKFLOW_TRIGGER_INBOX_READ = "workflow_trigger.inbox.read"
WORKFLOW_TRIGGER_INBOX_SUBMIT = "workflow_trigger.inbox.submit"
WORKFLOW_TRIGGER_INBOX_REPLAY = "workflow_trigger.inbox.replay"
WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ = "workflow_trigger.scheduler_ticks.read"
WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE = "workflow_trigger.scheduler.run_once"
WORKFLOW_BACKFILL_LAUNCH_LIST = "workflow_trigger.backfill_launch.list"
WORKFLOW_BACKFILL_LAUNCH_READ = "workflow_trigger.backfill_launch.read"
WORKFLOW_TRIGGER_BACKFILL_PREVIEW = "workflow_trigger.backfill.preview"
WORKFLOW_TRIGGER_BACKFILL_LAUNCH = "workflow_trigger.backfill.launch"
WORKFLOW_BACKFILL_LAUNCH_CANCEL = "workflow_trigger.backfill_launch.cancel"
GOVERNANCE_AUDIT_EVENTS_READ = "audit.events.read"
SECRET_PROVIDER_READINESS_READ = "secret.provider_readiness.read"


REMOTE_ENDPOINTS: dict[str, RemoteEndpoint] = {
    RUN_LIST: RemoteEndpoint(
        endpoint_id=RUN_LIST,
        method="GET",
        path_template="/api/v1/runs",
        operation_id="listRuns",
        governance_action=None,
        request_schema=None,
        response_schema="run-list.v1",
        cache_scope="run-read-model",
        response_item_key="items",
    ),
    RUN_READ: RemoteEndpoint(
        endpoint_id=RUN_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}",
        operation_id="getRun",
        governance_action=None,
        request_schema=None,
        response_schema="run.v1",
        cache_scope="run-read-model",
    ),
    RUN_EVENTS_READ: RemoteEndpoint(
        endpoint_id=RUN_EVENTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/events",
        operation_id="getRunEvents",
        governance_action="run.events.read",
        request_schema=None,
        response_schema="run-events.v1",
        cache_scope="run-read-model",
    ),
    RUN_EXECUTION_CONTEXT_READ: RemoteEndpoint(
        endpoint_id=RUN_EXECUTION_CONTEXT_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/execution-context",
        operation_id="getRunExecutionContext",
        governance_action="run.execution_context.read",
        request_schema=None,
        response_schema="run-execution-context.v1",
        cache_scope="run-read-model",
    ),
    RUN_ATTEMPTS_READ: RemoteEndpoint(
        endpoint_id=RUN_ATTEMPTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/attempts",
        operation_id="getRunAttempts",
        governance_action="run.attempts.read",
        request_schema=None,
        response_schema="run-attempts.v1",
        cache_scope="run-read-model",
    ),
    RUN_LOGS_READ: RemoteEndpoint(
        endpoint_id=RUN_LOGS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/logs",
        operation_id="getRunLogs",
        governance_action="run.logs.read",
        request_schema=None,
        response_schema="run-logs.v1",
        cache_scope="run-read-model",
        query_params=("stream", "cursor"),
    ),
    RUN_RESULTS_READ: RemoteEndpoint(
        endpoint_id=RUN_RESULTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/results",
        operation_id="getRunResults",
        governance_action="run.results.read",
        request_schema=None,
        response_schema="run-results.v1",
        cache_scope="run-read-model",
    ),
    RUN_RULES_READ: RemoteEndpoint(
        endpoint_id=RUN_RULES_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/rules",
        operation_id="getRunRules",
        governance_action="run.rules.read",
        request_schema=None,
        response_schema="run-rules.v1",
        cache_scope="run-read-model",
    ),
    RUN_FAILURE_LOCATOR_READ: RemoteEndpoint(
        endpoint_id=RUN_FAILURE_LOCATOR_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/failure-locator",
        operation_id="getRunFailureLocator",
        governance_action="run.failure_locator.read",
        request_schema=None,
        response_schema="run-failure-locator.v1",
        cache_scope="run-read-model",
    ),
    RUN_CANCEL: RemoteEndpoint(
        endpoint_id=RUN_CANCEL,
        method="POST",
        path_template="/api/v1/runs/{run_id}/cancel",
        operation_id="cancelRun",
        governance_action="run.cancel",
        request_schema=None,
        response_schema="run-cancel-result.v1",
        cache_scope="run-command",
        invalidates=("run-read-model",),
    ),
    RUN_RETRY: RemoteEndpoint(
        endpoint_id=RUN_RETRY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/retry",
        operation_id="retryRun",
        governance_action="run.retry",
        request_schema="run-retry-request.v1",
        response_schema="run-retry-result.v1",
        cache_scope="run-command",
        invalidates=("run-read-model",),
        accepted_statuses=(202,),
    ),
    RUN_RESUME: RemoteEndpoint(
        endpoint_id=RUN_RESUME,
        method="POST",
        path_template="/api/v1/runs/{run_id}/resume",
        operation_id="resumeRun",
        governance_action="run.resume",
        request_schema="run-resume-request.v1",
        response_schema="run-resume-result.v1",
        cache_scope="run-command",
        invalidates=("run-read-model",),
        accepted_statuses=(202,),
    ),
    RUN_RULE_RETRY: RemoteEndpoint(
        endpoint_id=RUN_RULE_RETRY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/retry",
        operation_id="retryRunRules",
        governance_action="run.rule_retry",
        request_schema="run-rule-retry-request.v1",
        response_schema="run-rule-retry-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
        accepted_statuses=(202,),
    ),
    RUN_RULE_OUTPUT_INVALIDATION_APPLY: RemoteEndpoint(
        endpoint_id=RUN_RULE_OUTPUT_INVALIDATION_APPLY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/output-invalidation/apply",
        operation_id="applyRuleOutputInvalidation",
        governance_action="run.rule_output_invalidation.apply",
        request_schema="run-rule-output-invalidation-apply-request.v1",
        response_schema="rule-output-invalidation-apply-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
    ),
    RUN_RULE_CACHE_RESTORE_PINS_PREPARE: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_PINS_PREPARE,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/pins/prepare",
        operation_id="prepareRuleCacheRestorePins",
        governance_action="run.rule_cache_restore.pins.prepare",
        request_schema="run-rule-cache-restore-pin-prepare-request.v1",
        response_schema="rule-cache-restore-pin-prepare-result.v1",
        cache_scope="run-rule-command",
    ),
    RUN_RULE_CACHE_RESTORE_PINS_APPLY: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_PINS_APPLY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/pins/apply",
        operation_id="applyRuleCacheRestorePins",
        governance_action="run.rule_cache_restore.pins.apply",
        request_schema="run-rule-cache-restore-pin-apply-request.v1",
        response_schema="rule-cache-restore-pin-apply-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
    ),
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/staged-files/prepare",
        operation_id="prepareRuleCacheRestoreStagedFiles",
        governance_action="run.rule_cache_restore.staged_files.prepare",
        request_schema="run-rule-cache-restore-staged-file-prepare-request.v1",
        response_schema="rule-cache-restore-staged-file-prepare-result.v1",
        cache_scope="run-rule-command",
    ),
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/staged-files/apply",
        operation_id="applyRuleCacheRestoreStagedFiles",
        governance_action="run.rule_cache_restore.staged_files.apply",
        request_schema="run-rule-cache-restore-staged-file-apply-request.v1",
        response_schema="rule-cache-restore-staged-file-apply-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
    ),
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/prepare",
        operation_id="prepareRuleCacheRestoreFinalOutputs",
        governance_action="run.rule_cache_restore.final_outputs.prepare",
        request_schema="run-rule-cache-restore-final-output-prepare-request.v1",
        response_schema="rule-cache-restore-final-output-prepare-result.v1",
        cache_scope="run-rule-command",
    ),
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/apply",
        operation_id="applyRuleCacheRestoreFinalOutputs",
        governance_action="run.rule_cache_restore.final_outputs.apply",
        request_schema="run-rule-cache-restore-final-output-apply-request.v1",
        response_schema="rule-cache-restore-final-output-apply-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
    ),
    RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/adoption/prepare",
        operation_id="prepareRuleCacheRestoreAdoption",
        governance_action="run.rule_cache_restore.adoption.prepare",
        request_schema="run-rule-cache-restore-adoption-prepare-request.v1",
        response_schema="rule-cache-restore-adoption-prepare-result.v1",
        cache_scope="run-rule-command",
    ),
    RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY: RemoteEndpoint(
        endpoint_id=RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY,
        method="POST",
        path_template="/api/v1/runs/{run_id}/rules/cache-restore/adoption/apply",
        operation_id="applyRuleCacheRestoreAdoption",
        governance_action="run.rule_cache_restore.adoption.apply",
        request_schema="run-rule-cache-restore-adoption-apply-request.v1",
        response_schema="rule-cache-restore-adoption-apply-result.v1",
        cache_scope="run-rule-command",
        invalidates=("run-read-model",),
    ),
    WORKFLOW_REVISION_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_REVISION_READ,
        method="GET",
        path_template="/api/v1/workflow-revisions/{workflow_revision_id}",
        operation_id="getWorkflowRevision",
        governance_action="workflow_revision.read",
        request_schema=None,
        response_schema="workflow-revision.v1",
        cache_scope="workflow-revision-read-model",
    ),
    RESULT_LIST: RemoteEndpoint(
        endpoint_id=RESULT_LIST,
        method="GET",
        path_template="/api/v1/results",
        operation_id="listResults",
        governance_action="result.list",
        request_schema=None,
        response_schema="result-list.v1",
        cache_scope="result-read-model",
        response_item_key="items",
    ),
    RESULT_READ: RemoteEndpoint(
        endpoint_id=RESULT_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}",
        operation_id="getResult",
        governance_action="result.read",
        request_schema=None,
        response_schema="result.v1",
        cache_scope="result-read-model",
    ),
    RESULT_PREVIEW_READ: RemoteEndpoint(
        endpoint_id=RESULT_PREVIEW_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}/preview",
        operation_id="getResultPreview",
        governance_action="result.artifact.preview",
        request_schema=None,
        response_schema="result-preview.v1",
        cache_scope="result-read-model",
        query_params=("artifact_id",),
    ),
    RESULT_AUDIT_READ: RemoteEndpoint(
        endpoint_id=RESULT_AUDIT_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}/audit",
        operation_id="getResultAudit",
        governance_action="result.artifact_audit.read",
        request_schema=None,
        response_schema="result-artifact-audit.v1",
        cache_scope="result-read-model",
    ),
    RESULT_PACKAGE_EXPORT_LIST: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_EXPORT_LIST,
        method="GET",
        path_template="/api/v1/results/{result_id}/exports",
        operation_id="listResultPackageExports",
        governance_action="result.package.list",
        request_schema=None,
        response_schema="result-package-export-list.v1",
        cache_scope="result-package-export-read-model",
        query_params=("lifecycleState", "limit"),
    ),
    RESULT_PACKAGE_EXPORT: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_EXPORT,
        method="POST",
        path_template="/api/v1/results/{result_id}/export",
        operation_id="exportResultPackage",
        governance_action="result.export",
        request_schema="result-package-export-request.v1",
        response_schema="h2ometa.result-package.v2",
        cache_scope="result-package-export-command",
        invalidates=("result-package-export-read-model",),
    ),
    RESULT_PACKAGE_RETIRE: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_RETIRE,
        method="POST",
        path_template="/api/v1/results/{result_id}/exports/{package_export_id}/retire",
        operation_id="retireResultPackage",
        governance_action="result.package.retire",
        request_schema="result-package-retire-request.v1",
        response_schema="h2ometa.result-package-retire.v1",
        cache_scope="result-package-export-command",
        invalidates=("result-package-export-read-model", "artifact-lifecycle-read-model"),
    ),
    RESULT_PACKAGE_BYTE_GC_PREVIEW: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_BYTE_GC_PREVIEW,
        method="POST",
        path_template="/api/v1/result-package-exports/bytes/gc/preview",
        operation_id="previewResultPackageByteGc",
        governance_action="result.package.bytes.preview",
        request_schema="result-package-byte-gc-preview-request.v1",
        response_schema="h2ometa.result-package-byte-gc-preview.v1",
        cache_scope="result-package-byte-gc-command",
    ),
    RESULT_PACKAGE_BYTE_GC_RUN: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_BYTE_GC_RUN,
        method="POST",
        path_template="/api/v1/result-package-exports/bytes/gc/run",
        operation_id="runResultPackageByteGc",
        governance_action="result.package.bytes.run",
        request_schema="result-package-byte-gc-run-request.v1",
        response_schema="h2ometa.result-package-byte-gc-run.v1",
        cache_scope="result-package-byte-gc-command",
        invalidates=("result-package-export-read-model", "artifact-lifecycle-read-model"),
    ),
    ARTIFACT_LIFECYCLE_USAGE_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_USAGE_READ,
        method="GET",
        path_template="/api/v1/artifacts/lifecycle/usage",
        operation_id="getArtifactLifecycleUsage",
        governance_action="artifact.lifecycle.usage.read",
        request_schema=None,
        response_schema="h2ometa.artifact-lifecycle-usage.v1",
        cache_scope="artifact-lifecycle-read-model",
        query_params=("quotaBytes",),
    ),
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
        method="GET",
        path_template="/api/v1/artifacts/lifecycle/controller/ticks",
        operation_id="listArtifactLifecycleControllerTicks",
        governance_action="artifact.lifecycle.controller_ticks.read",
        request_schema=None,
        response_schema="h2ometa.artifact-lifecycle-controller-tick-read-model.v1",
        cache_scope="artifact-lifecycle-read-model",
        query_params=("limit",),
    ),
    ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
        method="POST",
        path_template="/api/v1/artifacts/lifecycle/controller/run-once",
        operation_id="runArtifactLifecycleControllerOnce",
        governance_action="artifact.lifecycle.controller.run_once",
        request_schema="artifact-lifecycle-controller-run-once-request.v1",
        response_schema="h2ometa.artifact-lifecycle-controller-run-once-result.v1",
        cache_scope="artifact-lifecycle-command",
        invalidates=("artifact-lifecycle-read-model",),
    ),
    ARTIFACT_LIFECYCLE_GC_PREVIEW: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_GC_PREVIEW,
        method="POST",
        path_template="/api/v1/artifacts/lifecycle/gc/preview",
        operation_id="previewArtifactGc",
        governance_action="artifact.gc.preview",
        request_schema="artifact-gc-preview-request.v1",
        response_schema="h2ometa.artifact-gc-public-plan.v1",
        cache_scope="artifact-lifecycle-command",
    ),
    ARTIFACT_LIFECYCLE_GC_RUN: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_GC_RUN,
        method="POST",
        path_template="/api/v1/artifacts/lifecycle/gc/run",
        operation_id="runArtifactGc",
        governance_action="artifact.gc.run",
        request_schema="artifact-gc-run-request.v1",
        response_schema="h2ometa.artifact-gc-public-run.v1",
        cache_scope="artifact-lifecycle-command",
        invalidates=("artifact-lifecycle-read-model", "artifact-cache-read-model"),
    ),
    ARTIFACT_CACHE_ENTRIES_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_ENTRIES_READ,
        method="GET",
        path_template="/api/v1/artifacts/cache/entries",
        operation_id="listArtifactCacheEntries",
        governance_action="artifact.cache.entries.read",
        request_schema=None,
        response_schema="artifact-cache-entries-public.v1",
        cache_scope="artifact-cache-read-model",
        query_params=("workflowRevisionId", "limit"),
    ),
    ARTIFACT_CACHE_PINS_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_PINS_READ,
        method="GET",
        path_template="/api/v1/artifacts/cache/pins",
        operation_id="listArtifactCachePins",
        governance_action="artifact.cache_pins.read",
        request_schema=None,
        response_schema="artifact-cache-pins-public.v1",
        cache_scope="artifact-cache-read-model",
        query_params=("cacheEntryId", "state", "limit"),
    ),
    ARTIFACT_CACHE_PIN_RETAIN: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_PIN_RETAIN,
        method="POST",
        path_template="/api/v1/artifacts/cache/entries/{cache_entry_id}/retain",
        operation_id="retainArtifactCachePin",
        governance_action="artifact.cache_pin.retain",
        request_schema="artifact-cache-pin-retain-request.v1",
        response_schema="artifact-cache-record-public.v1",
        cache_scope="artifact-cache-command",
        invalidates=("artifact-cache-read-model",),
    ),
    ARTIFACT_CACHE_PIN_RELEASE: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_PIN_RELEASE,
        method="POST",
        path_template="/api/v1/artifacts/cache/pins/{cache_pin_id}/release",
        operation_id="releaseArtifactCachePin",
        governance_action="artifact.cache_pin.release",
        request_schema="artifact-cache-pin-release-request.v1",
        response_schema="artifact-cache-record-public.v1",
        cache_scope="artifact-cache-command",
        invalidates=("artifact-cache-read-model",),
    ),
    ARTIFACT_CACHE_LOOKUP: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_LOOKUP,
        method="POST",
        path_template="/api/v1/artifacts/cache/lookup",
        operation_id="lookupArtifactCache",
        governance_action="artifact.cache.lookup",
        request_schema="artifact-cache-lookup-request.v1",
        response_schema="artifact-cache-lookup-public.v1",
        cache_scope="artifact-cache-command",
        invalidates=("artifact-cache-read-model",),
    ),
    **{
        endpoint_id: RemoteEndpoint(endpoint_id=endpoint_id, **spec)
        for endpoint_id, spec in WORKFLOW_DESIGN_REMOTE_ENDPOINT_SPECS.items()
    },
    WORKFLOW_TRIGGER_LIST: RemoteEndpoint(
        endpoint_id=WORKFLOW_TRIGGER_LIST,
        method="GET",
        path_template="/api/v1/workflow-triggers",
        operation_id="listWorkflowTriggers",
        governance_action="workflow_trigger.list",
        request_schema=None,
        response_schema="workflow-trigger-list.v1",
        cache_scope="workflow-trigger-read-model",
    ),
    WORKFLOW_TRIGGER_CREATE: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_CREATE, "/api/v1/workflow-triggers", "createWorkflowTrigger",
        "workflow_trigger.create", "workflow-trigger-create-request.v1", "workflow-trigger.v1",
        invalidates=("workflow-trigger-read-model",),
        accepted_statuses=(201,),
    ),
    WORKFLOW_TRIGGER_EVENTS_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_TRIGGER_EVENTS_READ,
        method="GET",
        path_template="/api/v1/workflow-triggers/{trigger_id}/events",
        operation_id="listWorkflowTriggerEvents",
        governance_action="workflow_trigger.events.read",
        request_schema=None,
        response_schema="workflow-trigger-event-list.v1",
        cache_scope="workflow-trigger-read-model",
    ),
    WORKFLOW_TRIGGER_EVENT_SUBMIT: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_EVENT_SUBMIT, "/api/v1/workflow-triggers/{trigger_id}/events",
        "submitWorkflowTriggerEvent", "workflow_trigger.dispatch",
        "workflow-trigger-event-request.v1", "workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
        method="GET",
        path_template="/api/v1/workflow-triggers/{trigger_id}/readiness-observation",
        operation_id="getWorkflowTriggerReadinessObservation",
        governance_action="workflow_trigger.readiness_observation.read",
        request_schema=None,
        response_schema="workflow-trigger-readiness-observation.v1",
        cache_scope="workflow-trigger-read-model",
    ),
    WORKFLOW_TRIGGER_READINESS_SUBMIT: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_READINESS_SUBMIT, "/api/v1/workflow-triggers/{trigger_id}/readiness",
        "submitWorkflowTriggerReadinessEvent", "workflow_trigger.dispatch",
        "workflow-trigger-readiness-event-request.v1", "workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_INBOX_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_TRIGGER_INBOX_READ,
        method="GET",
        path_template="/api/v1/workflow-triggers/{trigger_id}/inbox",
        operation_id="listWorkflowTriggerInboxEvents",
        governance_action="workflow_trigger.inbox.read",
        request_schema=None,
        response_schema="workflow-trigger-inbox-list.v1",
        cache_scope="workflow-trigger-read-model",
        query_params=("state", "limit"),
    ),
    WORKFLOW_TRIGGER_INBOX_SUBMIT: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_INBOX_SUBMIT, "/api/v1/workflow-triggers/{trigger_id}/inbox",
        "submitWorkflowTriggerInboxEvent", "workflow_trigger.dispatch",
        "workflow-trigger-inbox-event-request.v1", "workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_INBOX_REPLAY: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_INBOX_REPLAY, "/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay",
        "replayWorkflowTriggerInboxEvent", "workflow_trigger.inbox_replay",
        "workflow-trigger-inbox-replay-request.v1", "workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
        method="GET",
        path_template="/api/v1/workflow-trigger-scheduler/ticks",
        operation_id="listWorkflowTriggerSchedulerTicks",
        governance_action="workflow_trigger.scheduler_ticks.read",
        request_schema=None,
        response_schema="h2ometa.workflow-trigger-scheduler-tick-read-model.v1",
        cache_scope="workflow-trigger-scheduler-read-model",
        query_params=("limit",),
    ),
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE, "/api/v1/workflow-trigger-scheduler/run-once",
        "runWorkflowTriggerSchedulerOnce", "workflow_trigger.scheduler.run_once",
        "workflow-trigger-scheduler-run-once-request.v1", "h2ometa.workflow-trigger-scheduler-run-once-result.v1",
        invalidates=("workflow-trigger-read-model", "workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    WORKFLOW_BACKFILL_LAUNCH_LIST: RemoteEndpoint(
        endpoint_id=WORKFLOW_BACKFILL_LAUNCH_LIST,
        method="GET",
        path_template="/api/v1/workflow-backfill-launches",
        operation_id="listWorkflowBackfillLaunches",
        governance_action="workflow_trigger.backfill_launch.list",
        request_schema=None,
        response_schema="workflow-backfill-launch-list.v1",
        cache_scope="workflow-backfill-read-model",
        query_params=("triggerId", "limit"),
    ),
    WORKFLOW_BACKFILL_LAUNCH_READ: RemoteEndpoint(
        endpoint_id=WORKFLOW_BACKFILL_LAUNCH_READ,
        method="GET",
        path_template="/api/v1/workflow-backfill-launches/{launch_id}",
        operation_id="getWorkflowBackfillLaunch",
        governance_action="workflow_trigger.backfill_launch.read",
        request_schema=None,
        response_schema="workflow-backfill-launch-detail.v1",
        cache_scope="workflow-backfill-read-model",
    ),
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_BACKFILL_PREVIEW, "/api/v1/workflow-triggers/{trigger_id}/backfill/preview",
        "previewWorkflowTriggerBackfill", "workflow_trigger.backfill_preview",
        "workflow-trigger-backfill-preview-request.v1", "workflow-trigger-backfill-preview-result.v1",
    ),
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH: _workflow_trigger_command_endpoint(
        WORKFLOW_TRIGGER_BACKFILL_LAUNCH, "/api/v1/workflow-triggers/{trigger_id}/backfill/launch",
        "launchWorkflowTriggerBackfill", "workflow_trigger.backfill_launch",
        "workflow-trigger-backfill-launch-request.v1", "workflow-trigger-backfill-launch-result.v1",
        invalidates=("workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    WORKFLOW_BACKFILL_LAUNCH_CANCEL: _workflow_trigger_command_endpoint(
        WORKFLOW_BACKFILL_LAUNCH_CANCEL, "/api/v1/workflow-backfill-launches/{launch_id}/cancel",
        "cancelWorkflowBackfillLaunch", "workflow_trigger.backfill_cancel",
        "workflow-backfill-cancel-request.v1", "workflow-backfill-cancel-result.v1",
        invalidates=("workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    GOVERNANCE_AUDIT_EVENTS_READ: RemoteEndpoint(
        endpoint_id=GOVERNANCE_AUDIT_EVENTS_READ,
        method="GET",
        path_template="/api/v1/audit/events",
        operation_id="listGovernanceAuditEvents",
        governance_action="audit.events.read",
        request_schema=None,
        response_schema="governance-audit-events.v1",
        cache_scope="governance-audit-read-model",
        query_params=("subjectKind", "subjectId", "action", "limit"),
    ),
    SECRET_PROVIDER_READINESS_READ: RemoteEndpoint(
        endpoint_id=SECRET_PROVIDER_READINESS_READ,
        method="GET",
        path_template="/api/v1/secrets/provider-readiness",
        operation_id="getSecretProviderReadiness",
        governance_action="secret.provider_readiness.read",
        request_schema=None,
        response_schema="remote-runner-secret-provider-readiness.v1",
        cache_scope="secret-readiness-read-model",
    ),
}


def get_remote_endpoint(endpoint_id: str) -> RemoteEndpoint:
    try:
        return REMOTE_ENDPOINTS[endpoint_id]
    except KeyError as exc:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_UNKNOWN", endpoint_id) from exc


def render_remote_endpoint_path(
    endpoint_id: str,
    values: dict[str, Any],
    *,
    query_values: dict[str, Any] | None = None,
) -> str:
    endpoint = get_remote_endpoint(endpoint_id)
    rendered_values: dict[str, str] = {}
    for name in endpoint.path_params:
        value = str(values.get(name) or "").strip()
        if not value:
            raise RemoteEndpointContractError(
                "REMOTE_ENDPOINT_PATH_PARAM_REQUIRED",
                f"{endpoint_id}.{name}",
            )
        rendered_values[name] = quote(value, safe="")
    path = endpoint.path_template.format(**rendered_values)
    query = _declared_query_values(endpoint, query_values or {})
    if query:
        path = f"{path}?{urlencode(query)}"
    return path


def _declared_query_values(endpoint: RemoteEndpoint, query_values: dict[str, Any]) -> list[tuple[str, str]]:
    unknown = sorted(set(query_values) - set(endpoint.query_params))
    if unknown:
        raise RemoteEndpointContractError(
            "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN",
            f"{endpoint.endpoint_id}: {','.join(unknown)}",
        )
    query: list[tuple[str, str]] = []
    for name in endpoint.query_params:
        value = query_values.get(name)
        if value is None or str(value) == "":
            continue
        query.append((name, _query_value(value)))
    return query


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
