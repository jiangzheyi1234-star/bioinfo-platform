from __future__ import annotations

from typing import Any


WORKFLOW_DESIGN_DRAFT_LIST = "workflow_design_draft.list"
WORKFLOW_DESIGN_DRAFT_CREATE = "workflow_design_draft.create"
WORKFLOW_DESIGN_DRAFT_READ = "workflow_design_draft.read"
WORKFLOW_DESIGN_DRAFT_UPDATE = "workflow_design_draft.update"
WORKFLOW_DESIGN_DRAFT_FORK = "workflow_design_draft.fork"
WORKFLOW_DESIGN_DRAFT_DELETE = "workflow_design_draft.delete"
WORKFLOW_DESIGN_DRAFT_PLAN = "workflow_design_draft.plan"
WORKFLOW_DESIGN_DRAFT_COMPILE = "workflow_design_draft.compile"


WORKFLOW_DESIGN_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    WORKFLOW_DESIGN_DRAFT_LIST: {
        "method": "GET",
        "path_template": "/api/v1/workflow-design-drafts",
        "operation_id": "listWorkflowDesignDrafts",
        "governance_action": "workflow_design_draft.list",
        "request_schema": None,
        "response_schema": "workflow-design-draft-list.v1",
        "cache_scope": "workflow-design-draft-read-model",
        "response_item_key": "items",
    },
    WORKFLOW_DESIGN_DRAFT_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/workflow-design-drafts",
        "operation_id": "createWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.create",
        "request_schema": "workflow-design-draft-create-request.v1",
        "response_schema": "workflow-design-draft-record.v1",
        "cache_scope": "workflow-design-draft-command",
        "invalidates": ("workflow-design-draft-read-model",),
        "accepted_statuses": (201,),
    },
    WORKFLOW_DESIGN_DRAFT_READ: {
        "method": "GET",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}",
        "operation_id": "getWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.read",
        "request_schema": None,
        "response_schema": "workflow-design-draft-record.v1",
        "cache_scope": "workflow-design-draft-read-model",
    },
    WORKFLOW_DESIGN_DRAFT_UPDATE: {
        "method": "PATCH",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}",
        "operation_id": "updateWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.update",
        "request_schema": "workflow-design-draft-update-request.v1",
        "response_schema": "workflow-design-draft-record.v1",
        "cache_scope": "workflow-design-draft-command",
        "invalidates": ("workflow-design-draft-read-model",),
    },
    WORKFLOW_DESIGN_DRAFT_FORK: {
        "method": "POST",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}/fork",
        "operation_id": "forkWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.fork",
        "request_schema": "workflow-design-draft-fork-request.v1",
        "response_schema": "workflow-design-draft-record.v1",
        "cache_scope": "workflow-design-draft-command",
        "invalidates": ("workflow-design-draft-read-model",),
        "accepted_statuses": (201,),
    },
    WORKFLOW_DESIGN_DRAFT_DELETE: {
        "method": "DELETE",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}",
        "operation_id": "deleteWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.delete",
        "request_schema": None,
        "response_schema": "workflow-design-draft-delete-result.v1",
        "cache_scope": "workflow-design-draft-command",
        "invalidates": ("workflow-design-draft-read-model",),
    },
    WORKFLOW_DESIGN_DRAFT_PLAN: {
        "method": "POST",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}/plan",
        "operation_id": "planWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.plan",
        "request_schema": "workflow-design-draft-plan-request.v1",
        "response_schema": "workflow-design-draft-plan.v1",
        "cache_scope": "workflow-design-draft-command",
    },
    WORKFLOW_DESIGN_DRAFT_COMPILE: {
        "method": "POST",
        "path_template": "/api/v1/workflow-design-drafts/{draft_id}/compile",
        "operation_id": "compileWorkflowDesignDraft",
        "governance_action": "workflow_design_draft.compile",
        "request_schema": "workflow-design-draft-compile-request.v1",
        "response_schema": "workflow-design-draft-compile-result.v1",
        "cache_scope": "workflow-design-draft-command",
        "invalidates": ("workflow-revision-read-model",),
    },
}
