from __future__ import annotations

import asyncio

from apps.remote_runner import agent_session_routes
from apps.remote_runner.main import app
from core.contracts.agent_remote_endpoints import (
    AGENT_RUN_AUTHORIZATION_PREVIEW_READ,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS
from core.governance_policy import HIGH_RISK_API_POLICIES


def test_run_authorization_preview_remote_endpoint_is_exact() -> None:
    endpoint = REMOTE_ENDPOINTS[AGENT_RUN_AUTHORIZATION_PREVIEW_READ]

    assert endpoint.method == "GET"
    assert endpoint.path_template == (
        "/api/v1/agent-sessions/{session_id}/run-authorization-preview"
    )
    assert endpoint.operation_id == "getAgentRunAuthorizationPreview"
    assert endpoint.governance_action == AGENT_RUN_AUTHORIZATION_PREVIEW_READ
    assert endpoint.request_schema is None
    assert endpoint.response_schema == "agent-run-authorization-preview.v1"
    assert endpoint.cache_scope == "agent-run-authorization-preview-read-model"


def test_run_authorization_preview_remote_policy_is_operator_only() -> None:
    matches = [
        policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
        and policy.method == "GET"
        and policy.route
        == "/api/v1/agent-sessions/{session_id}/run-authorization-preview"
    ]

    assert len(matches) == 1
    policy = matches[0]
    assert policy.action == AGENT_RUN_AUTHORIZATION_PREVIEW_READ
    assert policy.subject_kind == "agent_run_authorization"
    assert policy.audit_status == "implemented"
    assert policy.future_roles == ("workflow-operator",)


def test_run_authorization_preview_remote_openapi_uses_registered_operation() -> None:
    operation = app.openapi()["paths"][
        "/api/v1/agent-sessions/{session_id}/run-authorization-preview"
    ]["get"]

    assert operation["operationId"] == "getAgentRunAuthorizationPreview"


def test_run_authorization_preview_route_delegates_without_a_request_body(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    async def fake_service(
        session_id: str,
        authorization: str | None,
    ) -> dict:
        calls.append((session_id, authorization))
        return {"data": {"sessionId": session_id}}

    monkeypatch.setattr(
        agent_session_routes,
        "get_agent_run_authorization_preview_from_http",
        fake_service,
    )

    response = asyncio.run(
        agent_session_routes.get_agent_run_authorization_preview_api(
            "ags_preview",
            "Bearer preview-token",
        )
    )

    assert response == {"data": {"sessionId": "ags_preview"}}
    assert calls == [("ags_preview", "Bearer preview-token")]
