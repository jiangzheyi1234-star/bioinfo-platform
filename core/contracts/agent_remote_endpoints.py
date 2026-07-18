from __future__ import annotations

from typing import Any


AGENT_PRINCIPAL_CONTEXT_READ = "agent_session.principal_context.read"
AGENT_SESSION_LIST = "agent_session.list"
AGENT_SESSION_CREATE = "agent_session.create"
AGENT_SESSION_READ = "agent_session.read"
AGENT_SESSION_SNAPSHOT_READ = "agent_session.snapshot.read"
AGENT_RUN_AUTHORIZATION_PREVIEW_READ = "agent_session.run_authorization_preview.read"
AGENT_RUN_AUTHORIZE = "agent_session.run_authorize"
AGENT_SESSION_EVENTS_READ = "agent_session.events.read"
AGENT_SESSION_PLANS_READ = "agent_session.plans.read"
AGENT_SESSION_APPROVALS_READ = "agent_session.approvals.read"
AGENT_SESSION_PLAN = "agent_session.plan"
AGENT_SESSION_APPROVAL = "agent_session.approval"
AGENT_SESSION_REPLAN = "agent_session.replan"
AGENT_SESSION_CANCEL = "agent_session.cancel"


AGENT_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    AGENT_PRINCIPAL_CONTEXT_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-principal-context",
        "operation_id": "getAgentPrincipalContext",
        "governance_action": "agent_session.principal_context.read",
        "request_schema": None,
        "response_schema": "agent-principal-context.v1",
        "cache_scope": "agent-principal-context-read-model",
    },
    AGENT_SESSION_LIST: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions",
        "operation_id": "listAgentSessions",
        "governance_action": "agent_session.list",
        "request_schema": None,
        "response_schema": "agent-session-list.v1",
        "cache_scope": "agent-session-read-model",
        "response_item_key": "items",
    },
    AGENT_SESSION_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions",
        "operation_id": "createAgentSession",
        "governance_action": "agent_session.create",
        "request_schema": "agent-session.v1",
        "response_schema": "agent-session.v1",
        "cache_scope": "agent-session-command",
        "invalidates": ("agent-session-read-model",),
        "accepted_statuses": (201,),
    },
    AGENT_SESSION_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}",
        "operation_id": "getAgentSession",
        "governance_action": "agent_session.read",
        "request_schema": None,
        "response_schema": "agent-session.v1",
        "cache_scope": "agent-session-read-model",
    },
    AGENT_SESSION_SNAPSHOT_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}/snapshot",
        "operation_id": "getAgentSessionSnapshot",
        "governance_action": "agent_session.snapshot.read",
        "request_schema": None,
        "response_schema": "agent-session-snapshot.v1",
        "cache_scope": "agent-session-read-model",
    },
    AGENT_RUN_AUTHORIZATION_PREVIEW_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}/run-authorization-preview",
        "operation_id": "getAgentRunAuthorizationPreview",
        "governance_action": AGENT_RUN_AUTHORIZATION_PREVIEW_READ,
        "request_schema": None,
        "response_schema": "agent-run-authorization-preview.v1",
        "cache_scope": "agent-run-authorization-preview-read-model",
    },
    AGENT_RUN_AUTHORIZE: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions/{session_id}/run-authorization",
        "operation_id": "authorizeAgentWorkflowRun",
        "governance_action": AGENT_RUN_AUTHORIZE,
        "request_schema": "agent-run-authorization-request.v1",
        "response_schema": "agent-run-authorization-result.v1",
        "cache_scope": "agent-run-authorization-command",
        "invalidates": (
            "agent-run-authorization-preview-read-model",
            "agent-session-read-model",
            "run-read-model",
        ),
        "accepted_statuses": (202,),
    },
    AGENT_SESSION_EVENTS_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}/events",
        "operation_id": "listAgentSessionEvents",
        "governance_action": "agent_session.events.read",
        "request_schema": None,
        "response_schema": "agent-event-list.v1",
        "cache_scope": "agent-session-read-model",
        "response_item_key": "items",
    },
    AGENT_SESSION_PLANS_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}/plans",
        "operation_id": "listAgentPlanRevisions",
        "governance_action": "agent_session.plans.read",
        "request_schema": None,
        "response_schema": "agent-plan-revision-list.v1",
        "cache_scope": "agent-session-read-model",
        "response_item_key": "items",
    },
    AGENT_SESSION_APPROVALS_READ: {
        "method": "GET",
        "path_template": "/api/v1/agent-sessions/{session_id}/approvals",
        "operation_id": "listAgentApprovals",
        "governance_action": "agent_session.approvals.read",
        "request_schema": None,
        "response_schema": "agent-approval-list.v1",
        "cache_scope": "agent-session-read-model",
        "response_item_key": "items",
    },
    AGENT_SESSION_PLAN: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions/{session_id}/plan",
        "operation_id": "planAgentSession",
        "governance_action": "agent_session.plan",
        "request_schema": "agent-plan-request.v1",
        "response_schema": "agent-plan-result.v1",
        "cache_scope": "agent-session-command",
        "invalidates": ("agent-session-read-model", "workflow-design-draft-read-model"),
    },
    AGENT_SESSION_APPROVAL: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions/{session_id}/approval",
        "operation_id": "approveAgentSessionPlan",
        "governance_action": "agent_session.approval",
        "request_schema": "agent-approval-request.v1",
        "response_schema": "agent-approval-result.v1",
        "cache_scope": "agent-session-command",
        "invalidates": ("agent-session-read-model", "workflow-revision-read-model"),
    },
    AGENT_SESSION_REPLAN: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions/{session_id}/replan",
        "operation_id": "replanAgentSession",
        "governance_action": "agent_session.replan",
        "request_schema": "agent-replan-request.v1",
        "response_schema": "agent-plan-result.v1",
        "cache_scope": "agent-session-command",
        "invalidates": ("agent-session-read-model", "workflow-design-draft-read-model"),
    },
    AGENT_SESSION_CANCEL: {
        "method": "POST",
        "path_template": "/api/v1/agent-sessions/{session_id}/cancel",
        "operation_id": "cancelAgentSession",
        "governance_action": "agent_session.cancel",
        "request_schema": "agent-cancel-request.v1",
        "response_schema": "agent-session.v1",
        "cache_scope": "agent-session-command",
        "invalidates": ("agent-session-read-model",),
    },
}
