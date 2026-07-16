"""AgentSession routes for the remote runner control plane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core.contracts.agent_remote_endpoints import (
    AGENT_PRINCIPAL_CONTEXT_READ,
    AGENT_SESSION_APPROVAL,
    AGENT_SESSION_APPROVALS_READ,
    AGENT_SESSION_CANCEL,
    AGENT_SESSION_CREATE,
    AGENT_SESSION_EVENTS_READ,
    AGENT_SESSION_LIST,
    AGENT_SESSION_PLAN,
    AGENT_SESSION_PLANS_READ,
    AGENT_SESSION_READ,
    AGENT_SESSION_REPLAN,
    AGENT_SESSION_SNAPSHOT_READ,
)
from core.contracts.agent_session import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status

from .agent_session_service import (
    approve_agent_session_from_http,
    cancel_agent_session_from_http,
    create_agent_session_from_http,
    get_agent_principal_context_from_http,
    get_agent_session_from_http,
    get_agent_session_snapshot_from_http,
    list_agent_approvals_from_http,
    list_agent_events_from_http,
    list_agent_plans_from_http,
    list_agent_sessions_from_http,
    plan_agent_session_from_http,
    replan_agent_session_from_http,
)
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get(
    "/api/v1/agent-principal-context",
    operation_id=REMOTE_ENDPOINTS[AGENT_PRINCIPAL_CONTEXT_READ].operation_id,
)
async def get_agent_principal_context_api(
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_agent_principal_context_from_http(authorization)


@router.get("/api/v1/agent-sessions", operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_LIST].operation_id)
async def list_agent_sessions_api(authorization: AuthorizationHeader = None) -> dict[str, Any]:
    return await list_agent_sessions_from_http(authorization)


@router.post(
    "/api/v1/agent-sessions",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_CREATE].operation_id,
    status_code=remote_endpoint_success_status(AGENT_SESSION_CREATE),
)
async def create_agent_session_api(
    payload: AgentSessionCreateRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await create_agent_session_from_http(payload, authorization)


@router.get(
    "/api/v1/agent-sessions/{session_id}",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_READ].operation_id,
)
async def get_agent_session_api(
    session_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_agent_session_from_http(session_id, authorization)


@router.get(
    "/api/v1/agent-sessions/{session_id}/snapshot",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_SNAPSHOT_READ].operation_id,
)
async def get_agent_session_snapshot_api(
    session_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_agent_session_snapshot_from_http(session_id, authorization)


@router.get(
    "/api/v1/agent-sessions/{session_id}/events",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_EVENTS_READ].operation_id,
)
async def list_agent_events_api(
    session_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_agent_events_from_http(session_id, authorization)


@router.get(
    "/api/v1/agent-sessions/{session_id}/plans",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_PLANS_READ].operation_id,
)
async def list_agent_plans_api(
    session_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_agent_plans_from_http(session_id, authorization)


@router.get(
    "/api/v1/agent-sessions/{session_id}/approvals",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_APPROVALS_READ].operation_id,
)
async def list_agent_approvals_api(
    session_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_agent_approvals_from_http(session_id, authorization)


@router.post(
    "/api/v1/agent-sessions/{session_id}/plan",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_PLAN].operation_id,
)
async def plan_agent_session_api(
    session_id: str,
    payload: AgentPlanRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await plan_agent_session_from_http(session_id, payload, authorization)


@router.post(
    "/api/v1/agent-sessions/{session_id}/approval",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_APPROVAL].operation_id,
)
async def approve_agent_session_api(
    session_id: str,
    payload: AgentApprovalRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await approve_agent_session_from_http(session_id, payload, authorization)


@router.post(
    "/api/v1/agent-sessions/{session_id}/replan",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_REPLAN].operation_id,
)
async def replan_agent_session_api(
    session_id: str,
    payload: AgentReplanRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await replan_agent_session_from_http(session_id, payload, authorization)


@router.post(
    "/api/v1/agent-sessions/{session_id}/cancel",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_CANCEL].operation_id,
)
async def cancel_agent_session_api(
    session_id: str,
    payload: AgentCancelRequest,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await cancel_agent_session_from_http(session_id, payload, authorization)
