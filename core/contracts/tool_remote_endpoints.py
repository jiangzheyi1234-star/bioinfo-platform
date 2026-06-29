from __future__ import annotations

from typing import Any


TOOL_LIST = "tool.list"
TOOL_INDEX_READ = "tool.index.read"
TOOL_CREATE = "tool.create"
TOOL_PREPARE_JOB_CREATE = "tool.prepare_job.create"
TOOL_PREPARE_JOB_LATEST_READ = "tool.prepare_job.latest.read"
TOOL_PREPARE_JOB_QUEUE_READ = "tool.prepare_job.queue.read"
TOOL_PREPARE_JOB_READ = "tool.prepare_job.read"
TOOL_PREPARE_JOB_CANCEL = "tool.prepare_job.cancel"
TOOL_RULE_TEMPLATE_UPDATE = "tool.rule_template.update"
TOOL_DELETE = "tool.delete"
TOOL_PRODUCTION_ENABLE = "tool.production.enable"


TOOL_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    TOOL_LIST: {
        "method": "GET",
        "path_template": "/api/v1/tools",
        "operation_id": "listTools",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-list.v1",
        "cache_scope": "tool-read-model",
        "response_item_key": "items",
    },
    TOOL_INDEX_READ: {
        "method": "GET",
        "path_template": "/api/v1/tools/index",
        "operation_id": "listToolIndex",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-index.v1",
        "cache_scope": "tool-read-model",
        "query_params": ("query", "limit", "offset", "source", "state"),
    },
    TOOL_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/tools",
        "operation_id": "createTool",
        "governance_action": "tool.create",
        "request_schema": "tool-manifest-request.v1",
        "response_schema": "tool.v1",
        "cache_scope": "tool-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model"),
        "accepted_statuses": (201,),
    },
    TOOL_PREPARE_JOB_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/tools/prepare-jobs",
        "operation_id": "createToolPrepareJob",
        "governance_action": "tool.prepare",
        "request_schema": "tool-manifest-request.v1",
        "response_schema": "tool-prepare-job.v1",
        "cache_scope": "tool-prepare-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model"),
        "accepted_statuses": (202,),
    },
    TOOL_PREPARE_JOB_LATEST_READ: {
        "method": "GET",
        "path_template": "/api/v1/tools/prepare-jobs",
        "operation_id": "listLatestToolPrepareJobs",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-prepare-job-latest-list.v1",
        "cache_scope": "tool-prepare-read-model",
        "query_params": ("toolIds",),
        "response_item_key": "byToolId",
    },
    TOOL_PREPARE_JOB_QUEUE_READ: {
        "method": "GET",
        "path_template": "/api/v1/tools/prepare-jobs/queue",
        "operation_id": "listToolPrepareJobQueue",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-prepare-job-queue.v1",
        "cache_scope": "tool-prepare-read-model",
        "query_params": ("status", "limit", "offset"),
    },
    TOOL_PREPARE_JOB_READ: {
        "method": "GET",
        "path_template": "/api/v1/tools/prepare-jobs/{job_id}",
        "operation_id": "getToolPrepareJob",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "tool-prepare-job.v1",
        "cache_scope": "tool-prepare-read-model",
    },
    TOOL_PREPARE_JOB_CANCEL: {
        "method": "POST",
        "path_template": "/api/v1/tools/prepare-jobs/{job_id}/cancel",
        "operation_id": "cancelToolPrepareJob",
        "governance_action": "tool.prepare.cancel",
        "request_schema": None,
        "response_schema": "tool-prepare-job.v1",
        "cache_scope": "tool-prepare-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model", "tool-prepare-read-model"),
    },
    TOOL_RULE_TEMPLATE_UPDATE: {
        "method": "PATCH",
        "path_template": "/api/v1/tools/{tool_id}/rule-template",
        "operation_id": "updateToolRuleTemplate",
        "governance_action": "tool.rule_template.update",
        "request_schema": "tool-rule-template-request.v1",
        "response_schema": "tool.v1",
        "cache_scope": "tool-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model"),
    },
    TOOL_DELETE: {
        "method": "DELETE",
        "path_template": "/api/v1/tools/{tool_id}",
        "operation_id": "deleteTool",
        "governance_action": "tool.delete",
        "request_schema": None,
        "response_schema": "tool-delete-result.v1",
        "cache_scope": "tool-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model"),
    },
    TOOL_PRODUCTION_ENABLE: {
        "method": "POST",
        "path_template": "/api/v1/tools/{tool_id}/production",
        "operation_id": "enableToolProduction",
        "governance_action": "tool.production.enable",
        "request_schema": "tool-production-evidence-request.v1",
        "response_schema": "tool.v1",
        "cache_scope": "tool-command",
        "invalidates": ("tool-read-model", "workflow-catalog-read-model"),
    },
}
