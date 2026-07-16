"""Local API façade for AgentSession control-plane endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.api.agent_session_models import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
)
from apps.api.agent_session_service import (
    approve_agent_session_from_request,
    cancel_agent_session_from_request,
    create_agent_session_from_request,
    get_agent_session_from_request,
    get_agent_session_snapshot_from_request,
    list_agent_session_approvals_from_request,
    list_agent_session_events_from_request,
    list_agent_session_plans_from_request,
    list_agent_sessions_from_request,
    plan_agent_session_from_request,
    replan_agent_session_from_request,
)
from core.contracts.agent_remote_endpoints import (
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
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status


router = APIRouter()


@router.get(
    "/api/v1/agent-sessions",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_LIST].operation_id,
)
async def list_agent_sessions_api(
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_agent_sessions_from_request(refresh=refresh, server_id=serverId)


@router.post(
    "/api/v1/agent-sessions",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_CREATE].operation_id,
    status_code=remote_endpoint_success_status(AGENT_SESSION_CREATE),
)
async def create_agent_session_api(payload: AgentSessionCreateRequest) -> dict[str, Any]:
    return await create_agent_session_from_request(payload)


@router.get(
    "/api/v1/agent-sessions/{session_id}",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_READ].operation_id,
)
async def get_agent_session_api(
    session_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await get_agent_session_from_request(
        session_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.get(
    "/api/v1/agent-sessions/{session_id}/snapshot",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_SNAPSHOT_READ].operation_id,
)
async def get_agent_session_snapshot_api(
    session_id: str,
    refresh: bool = False,
    serverId: str = Query(min_length=1, pattern=r".*\S.*"),
) -> dict[str, Any]:
    return await get_agent_session_snapshot_from_request(
        session_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.get(
    "/api/v1/agent-sessions/{session_id}/events",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_EVENTS_READ].operation_id,
)
async def list_agent_session_events_api(
    session_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_agent_session_events_from_request(
        session_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.get(
    "/api/v1/agent-sessions/{session_id}/plans",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_PLANS_READ].operation_id,
)
async def list_agent_session_plans_api(
    session_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_agent_session_plans_from_request(
        session_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.get(
    "/api/v1/agent-sessions/{session_id}/approvals",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_APPROVALS_READ].operation_id,
)
async def list_agent_session_approvals_api(
    session_id: str,
    refresh: bool = False,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await list_agent_session_approvals_from_request(
        session_id,
        refresh=refresh,
        server_id=serverId,
    )


@router.post(
    "/api/v1/agent-sessions/{session_id}/plan",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_PLAN].operation_id,
)
async def plan_agent_session_api(
    session_id: str,
    payload: AgentPlanRequest,
) -> dict[str, Any]:
    return await plan_agent_session_from_request(session_id, payload)


@router.post(
    "/api/v1/agent-sessions/{session_id}/approval",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_APPROVAL].operation_id,
)
async def approve_agent_session_api(
    session_id: str,
    payload: AgentApprovalRequest,
) -> dict[str, Any]:
    return await approve_agent_session_from_request(session_id, payload)


@router.post(
    "/api/v1/agent-sessions/{session_id}/replan",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_REPLAN].operation_id,
)
async def replan_agent_session_api(
    session_id: str,
    payload: AgentReplanRequest,
) -> dict[str, Any]:
    return await replan_agent_session_from_request(session_id, payload)


@router.post(
    "/api/v1/agent-sessions/{session_id}/cancel",
    operation_id=REMOTE_ENDPOINTS[AGENT_SESSION_CANCEL].operation_id,
)
async def cancel_agent_session_api(
    session_id: str,
    payload: AgentCancelRequest,
) -> dict[str, Any]:
    return await cancel_agent_session_from_request(session_id, payload)
