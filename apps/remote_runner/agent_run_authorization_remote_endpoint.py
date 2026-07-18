"""Authenticated HTTP boundary for Agent-owned WorkflowRun authorization."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from core.contracts.agent_remote_endpoints import AGENT_RUN_AUTHORIZE
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationRequest,
    AgentRunAuthorizationResult,
)
from core.contracts.agent_session import AgentSessionModel

from .agent_run_authorization_service import authorize_agent_workflow_run
from .errors import (
    RemoteRunnerAuthorizationError,
    RemoteRunnerNotFoundError,
    WorkflowDesignRevisionConflictError,
)
from .governance_audit import record_governance_audit_event
from .route_utils import (
    authorized_config,
    data_response,
    remote_runner_principal,
    run_sync,
)


AGENT_RUN_AUTHORIZATION_ACTION = AGENT_RUN_AUTHORIZE


class AgentRunAuthorizationHttpResponse(AgentSessionModel):
    data: AgentRunAuthorizationResult


async def authorize_agent_workflow_run_from_http(
    session_id: str,
    request: AgentRunAuthorizationRequest | Mapping[str, object],
    authorization: str | None,
) -> dict[str, Any]:
    """Run the authenticated boundary and audit only domain failures."""

    cfg = authorized_config(
        authorization,
        action="agent_session.run_authorize",
    )
    principal = remote_runner_principal(cfg)
    normalized_request = _normalize_request(request)
    try:
        result_payload = await run_sync(
            authorize_agent_workflow_run,
            cfg,
            session_id,
            normalized_request,
            actor=principal.actor,
        )
        result = _validate_result(result_payload)
    except Exception as exc:
        decision, reason_code = _failure_audit_classification(exc)
        await run_sync(
            record_governance_audit_event,
            cfg,
            action=AGENT_RUN_AUTHORIZATION_ACTION,
            actor=principal.actor,
            actor_roles=principal.roles,
            subject_kind="agent_run_authorization",
            subject_id=session_id,
            decision=decision,
            reason_code=reason_code,
            request_id=normalized_request.requestId,
            details={
                "sessionId": session_id,
                "requestId": normalized_request.requestId,
                "failureStage": "run-authorization-domain",
                "errorType": type(exc).__name__,
            },
        )
        raise
    return data_response(result.runtime_payload())


def _normalize_request(
    request: AgentRunAuthorizationRequest | Mapping[str, object],
) -> AgentRunAuthorizationRequest:
    payload = (
        request.runtime_payload()
        if isinstance(request, AgentRunAuthorizationRequest)
        else deepcopy(dict(request))
    )
    return AgentRunAuthorizationRequest.model_validate(payload)


def _validate_result(payload: Mapping[str, object]) -> AgentRunAuthorizationResult:
    try:
        return AgentRunAuthorizationResult.model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError("AGENT_RUN_AUTHORIZATION_RESULT_INVALID") from exc


def _failure_audit_classification(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, RemoteRunnerAuthorizationError):
        return "deny", "AGENT_RUN_AUTHORIZATION_OWNER_DENIED"
    if isinstance(exc, RemoteRunnerNotFoundError):
        return "error", "AGENT_RUN_AUTHORIZATION_NOT_FOUND"
    if isinstance(exc, WorkflowDesignRevisionConflictError):
        return "error", "AGENT_RUN_AUTHORIZATION_CONFLICT"
    return "error", "AGENT_RUN_AUTHORIZATION_FAILED"


__all__ = [
    "AGENT_RUN_AUTHORIZATION_ACTION",
    "AgentRunAuthorizationHttpResponse",
    "authorize_agent_workflow_run_from_http",
]
