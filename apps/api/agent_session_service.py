"""Local AgentSession façade over the selected remote runner."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

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
from core.contracts.agent_session import AgentPrincipalContext


AGENT_SESSION_CACHE_PREFIXES = (
    "agent_sessions:",
    "agent_session:",
    "agent_session_snapshot:",
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
    runtime = runtime_service()
    result = await run_runtime_payload(
        lambda: runtime.create_agent_session(
            _bind_trusted_principal(
                runtime,
                server_id=server_id,
                payload=body,
                claim_field="createdBy",
            ),
            server_id=server_id,
        ),
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


async def get_agent_session_snapshot_from_request(
    session_id: str,
    *,
    refresh: bool,
    server_id: str,
) -> dict[str, Any]:
    normalized_server_id = str(server_id or "").strip()
    if not normalized_server_id:
        raise ValueError("AGENT_SESSION_SERVER_ID_REQUIRED")
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("AGENT_SESSION_ID_REQUIRED")
    return await cached_runtime_payload(
        f"agent_session_snapshot:{normalized_server_id}:{normalized_session_id}",
        10,
        lambda: runtime_service().get_agent_session_snapshot(
            normalized_session_id,
            server_id=normalized_server_id,
        ),
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
    runtime = runtime_service()
    result = await run_runtime_payload(
        lambda: plan_agent_session_with_adapter(
            runtime=runtime,
            session_id=session_id,
            server_id=server_id,
            command=_bind_trusted_principal(
                runtime,
                server_id=server_id,
                payload=body,
                claim_field="actor",
            ),
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
    runtime = runtime_service()
    result = await run_runtime_payload(
        lambda: runtime.approve_agent_session(
            session_id,
            _bind_trusted_principal(
                runtime,
                server_id=server_id,
                payload=body,
                claim_field="actor",
            ),
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
    runtime = runtime_service()
    result = await run_runtime_payload(
        lambda: plan_agent_session_with_adapter(
            runtime=runtime,
            session_id=session_id,
            server_id=server_id,
            command=_bind_trusted_principal(
                runtime,
                server_id=server_id,
                payload=body,
                claim_field="actor",
            ),
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
    runtime = runtime_service()
    result = await run_runtime_payload(
        lambda: runtime.cancel_agent_session(
            session_id,
            _bind_trusted_principal(
                runtime,
                server_id=server_id,
                payload=body,
                claim_field="actor",
            ),
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


def _bind_trusted_principal(
    runtime: Any,
    *,
    server_id: str,
    payload: dict[str, object],
    claim_field: str,
) -> dict[str, object]:
    response = runtime.get_agent_principal_context(server_id=server_id)
    data = response.get("data") if isinstance(response, dict) else None
    try:
        context = AgentPrincipalContext.model_validate(data)
    except ValidationError as exc:
        raise ValueError("AGENT_PRINCIPAL_CONTEXT_INVALID") from exc
    if claim_field in payload:
        raise ValueError("AGENT_PRINCIPAL_CLAIM_FORBIDDEN")
    return dict(payload) | {claim_field: context.actor}
