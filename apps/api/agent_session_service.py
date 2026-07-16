"""Local AgentSession façade over the selected remote runner."""

from __future__ import annotations

from typing import Any

from apps.api.agent_session_models import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
    split_agent_routing,
)
from apps.api.agent_session_planner_service import plan_agent_session_with_adapter
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, run_runtime_payload, runtime_service


AGENT_SESSION_CACHE_PREFIXES = (
    "agent_sessions:",
    "agent_session:",
    "agent_session_events:",
    "agent_session_plans:",
    "agent_session_approvals:",
)


async def list_agent_sessions_from_request(
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"agent_sessions:{server_id or 'default'}",
        10,
        lambda: runtime_service().list_agent_sessions(server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def create_agent_session_from_request(
    request: AgentSessionCreateRequest,
) -> dict[str, Any]:
    server_id, body = split_agent_routing(request)
    result = await run_runtime_payload(
        lambda: runtime_service().create_agent_session(body, server_id=server_id),
        wrapper="raw",
    )
    await _invalidate_agent_session_cache()
    return result


async def get_agent_session_from_request(
    session_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"agent_session:{server_id or 'default'}:{session_id}",
        10,
        lambda: runtime_service().get_agent_session(session_id, server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def list_agent_session_events_from_request(
    session_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await _cached_session_child(
        "events",
        session_id=session_id,
        refresh=refresh,
        server_id=server_id,
    )


async def list_agent_session_plans_from_request(
    session_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await _cached_session_child(
        "plans",
        session_id=session_id,
        refresh=refresh,
        server_id=server_id,
    )


async def list_agent_session_approvals_from_request(
    session_id: str,
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await _cached_session_child(
        "approvals",
        session_id=session_id,
        refresh=refresh,
        server_id=server_id,
    )


async def plan_agent_session_from_request(
    session_id: str,
    request: AgentPlanRequest,
) -> dict[str, Any]:
    server_id, body = split_agent_routing(request)
    if server_id is None:
        raise ValueError("AGENT_SESSION_SERVER_ID_REQUIRED")
    result = await run_runtime_payload(
        lambda: plan_agent_session_with_adapter(
            runtime=runtime_service(),
            session_id=session_id,
            server_id=server_id,
            command=body,
            replan=False,
        ),
        wrapper="raw",
    )
    await _invalidate_agent_session_cache()
    return result


async def approve_agent_session_from_request(
    session_id: str,
    request: AgentApprovalRequest,
) -> dict[str, Any]:
    server_id, body = split_agent_routing(request)
    result = await run_runtime_payload(
        lambda: runtime_service().approve_agent_session(
            session_id,
            body,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await _invalidate_agent_session_cache()
    return result


async def replan_agent_session_from_request(
    session_id: str,
    request: AgentReplanRequest,
) -> dict[str, Any]:
    server_id, body = split_agent_routing(request)
    if server_id is None:
        raise ValueError("AGENT_SESSION_SERVER_ID_REQUIRED")
    result = await run_runtime_payload(
        lambda: plan_agent_session_with_adapter(
            runtime=runtime_service(),
            session_id=session_id,
            server_id=server_id,
            command=body,
            replan=True,
        ),
        wrapper="raw",
    )
    await _invalidate_agent_session_cache()
    return result


async def cancel_agent_session_from_request(
    session_id: str,
    request: AgentCancelRequest,
) -> dict[str, Any]:
    server_id, body = split_agent_routing(request)
    result = await run_runtime_payload(
        lambda: runtime_service().cancel_agent_session(
            session_id,
            body,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await _invalidate_agent_session_cache()
    return result


async def _cached_session_child(
    child: str,
    *,
    session_id: str,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    runtime = runtime_service()
    loaders = {
        "events": runtime.list_agent_session_events,
        "plans": runtime.list_agent_session_plans,
        "approvals": runtime.list_agent_session_approvals,
    }
    return await cached_runtime_payload(
        f"agent_session_{child}:{server_id or 'default'}:{session_id}",
        10,
        lambda: loaders[child](session_id, server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def _invalidate_agent_session_cache() -> None:
    await invalidate_response_cache(prefixes=AGENT_SESSION_CACHE_PREFIXES)
