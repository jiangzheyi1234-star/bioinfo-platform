from __future__ import annotations

from typing import Any


WORKFLOW_TRIGGER_LIST = "workflow_trigger.list"
WORKFLOW_TRIGGER_CREATE = "workflow_trigger.create"
WORKFLOW_TRIGGER_EVENTS_READ = "workflow_trigger.events.read"
WORKFLOW_TRIGGER_EVENT_SUBMIT = "workflow_trigger.event.submit"
WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ = "workflow_trigger.readiness_observation.read"
WORKFLOW_TRIGGER_READINESS_SUBMIT = "workflow_trigger.readiness.submit"
WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE = "workflow_trigger.readiness_watcher.run_once"
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


def workflow_trigger_command_endpoint(
    *,
    method: str = "POST",
    path_template: str,
    operation_id: str,
    governance_action: str,
    request_schema: str,
    response_schema: str,
    invalidates: tuple[str, ...] = (),
    response_key: str = "data",
    accepted_statuses: tuple[int, ...] = (200,),
) -> dict[str, Any]:
    return {
        "method": method,
        "path_template": path_template,
        "operation_id": operation_id,
        "governance_action": governance_action,
        "request_schema": request_schema,
        "response_schema": response_schema,
        "cache_scope": "workflow-trigger-command",
        "invalidates": invalidates,
        "response_key": response_key,
        "accepted_statuses": accepted_statuses,
    }


WORKFLOW_TRIGGER_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    WORKFLOW_TRIGGER_LIST: {
        "method": "GET",
        "path_template": "/api/v1/workflow-triggers",
        "operation_id": "listWorkflowTriggers",
        "governance_action": "workflow_trigger.list",
        "request_schema": None,
        "response_schema": "workflow-trigger-list.v1",
        "cache_scope": "workflow-trigger-read-model",
    },
    WORKFLOW_TRIGGER_CREATE: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers",
        operation_id="createWorkflowTrigger",
        governance_action="workflow_trigger.create",
        request_schema="workflow-trigger-create-request.v1",
        response_schema="workflow-trigger.v1",
        invalidates=("workflow-trigger-read-model",),
        accepted_statuses=(201,),
    ),
    WORKFLOW_TRIGGER_EVENTS_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-triggers/{trigger_id}/events",
        "operation_id": "listWorkflowTriggerEvents",
        "governance_action": "workflow_trigger.events.read",
        "request_schema": None,
        "response_schema": "workflow-trigger-event-list.v1",
        "cache_scope": "workflow-trigger-read-model",
    },
    WORKFLOW_TRIGGER_EVENT_SUBMIT: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/events",
        operation_id="submitWorkflowTriggerEvent",
        governance_action="workflow_trigger.dispatch",
        request_schema="workflow-trigger-event-request.v1",
        response_schema="workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-triggers/{trigger_id}/readiness-observation",
        "operation_id": "getWorkflowTriggerReadinessObservation",
        "governance_action": "workflow_trigger.readiness_observation.read",
        "request_schema": None,
        "response_schema": "workflow-trigger-readiness-observation.v1",
        "cache_scope": "workflow-trigger-read-model",
    },
    WORKFLOW_TRIGGER_READINESS_SUBMIT: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/readiness",
        operation_id="submitWorkflowTriggerReadinessEvent",
        governance_action="workflow_trigger.dispatch",
        request_schema="workflow-trigger-readiness-event-request.v1",
        response_schema="workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-trigger-readiness-watcher/run-once",
        operation_id="runWorkflowTriggerReadinessWatcherOnce",
        governance_action="workflow_trigger.readiness_watcher.run_once",
        request_schema="workflow-trigger-readiness-watcher-run-once-request.v1",
        response_schema="h2ometa.workflow-trigger-readiness-watcher-run-once-result.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_INBOX_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-triggers/{trigger_id}/inbox",
        "operation_id": "listWorkflowTriggerInboxEvents",
        "governance_action": "workflow_trigger.inbox.read",
        "request_schema": None,
        "response_schema": "workflow-trigger-inbox-list.v1",
        "cache_scope": "workflow-trigger-read-model",
        "query_params": ("state", "limit"),
    },
    WORKFLOW_TRIGGER_INBOX_SUBMIT: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/inbox",
        operation_id="submitWorkflowTriggerInboxEvent",
        governance_action="workflow_trigger.dispatch",
        request_schema="workflow-trigger-inbox-event-request.v1",
        response_schema="workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_INBOX_REPLAY: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay",
        operation_id="replayWorkflowTriggerInboxEvent",
        governance_action="workflow_trigger.inbox_replay",
        request_schema="workflow-trigger-inbox-replay-request.v1",
        response_schema="workflow-trigger-dispatch.v1",
        invalidates=("workflow-trigger-read-model", "run-read-model"),
        response_key="",
        accepted_statuses=(202,),
    ),
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-trigger-scheduler/ticks",
        "operation_id": "listWorkflowTriggerSchedulerTicks",
        "governance_action": "workflow_trigger.scheduler_ticks.read",
        "request_schema": None,
        "response_schema": "h2ometa.workflow-trigger-scheduler-tick-read-model.v1",
        "cache_scope": "workflow-trigger-scheduler-read-model",
        "query_params": ("limit",),
    },
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-trigger-scheduler/run-once",
        operation_id="runWorkflowTriggerSchedulerOnce",
        governance_action="workflow_trigger.scheduler.run_once",
        request_schema="workflow-trigger-scheduler-run-once-request.v1",
        response_schema="h2ometa.workflow-trigger-scheduler-run-once-result.v1",
        invalidates=("workflow-trigger-read-model", "workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    WORKFLOW_BACKFILL_LAUNCH_LIST: {
        "method": "GET",
        "path_template": "/api/v1/workflow-backfill-launches",
        "operation_id": "listWorkflowBackfillLaunches",
        "governance_action": "workflow_trigger.backfill_launch.list",
        "request_schema": None,
        "response_schema": "workflow-backfill-launch-list.v1",
        "cache_scope": "workflow-backfill-read-model",
        "query_params": ("triggerId", "limit"),
    },
    WORKFLOW_BACKFILL_LAUNCH_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-backfill-launches/{launch_id}",
        "operation_id": "getWorkflowBackfillLaunch",
        "governance_action": "workflow_trigger.backfill_launch.read",
        "request_schema": None,
        "response_schema": "workflow-backfill-launch-detail.v1",
        "cache_scope": "workflow-backfill-read-model",
    },
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/backfill/preview",
        operation_id="previewWorkflowTriggerBackfill",
        governance_action="workflow_trigger.backfill_preview",
        request_schema="workflow-trigger-backfill-preview-request.v1",
        response_schema="workflow-trigger-backfill-preview-result.v1",
    ),
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-triggers/{trigger_id}/backfill/launch",
        operation_id="launchWorkflowTriggerBackfill",
        governance_action="workflow_trigger.backfill_launch",
        request_schema="workflow-trigger-backfill-launch-request.v1",
        response_schema="workflow-trigger-backfill-launch-result.v1",
        invalidates=("workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
    WORKFLOW_BACKFILL_LAUNCH_CANCEL: workflow_trigger_command_endpoint(
        path_template="/api/v1/workflow-backfill-launches/{launch_id}/cancel",
        operation_id="cancelWorkflowBackfillLaunch",
        governance_action="workflow_trigger.backfill_cancel",
        request_schema="workflow-backfill-cancel-request.v1",
        response_schema="workflow-backfill-cancel-result.v1",
        invalidates=("workflow-backfill-read-model", "run-read-model"),
        accepted_statuses=(202,),
    ),
}
