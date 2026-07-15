from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest
from pydantic import ValidationError

from apps.api.agent_session_models import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
    split_agent_routing,
)
from apps.api.agent_session_routes import (
    approve_agent_session_api,
    cancel_agent_session_api,
    create_agent_session_api,
    get_agent_session_api,
    list_agent_session_approvals_api,
    list_agent_session_events_api,
    list_agent_session_plans_api,
    list_agent_sessions_api,
    plan_agent_session_api,
    replan_agent_session_api,
)
from apps.api.main import app
from core.app_runtime.managers.agent import AgentManager
from core.app_runtime.runner_ops import RunnerOperationsMixin
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
)
from tests.helpers.workflow_design_drafts import workflow_design_draft


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 8,
        "maxToolCalls": 12,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _create_payload(*, server_id: str | None = "srv_agent") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contractVersion": "agent-session.v1",
        "projectId": "project-qc",
        "creationRequestId": "create-qc-1",
        "createdBy": "user-1",
        "goal": {
            "summary": "Run FASTQ QC and produce a reviewable MultiQC report.",
            "successCriteria": ["Produce a reviewable MultiQC report."],
            "context": {"sampleCount": 2},
        },
        "constraints": {
            "allowedToolRevisionIds": ["tr_fastqc", "tr_multiqc"],
            "forbiddenActions": ["arbitrary_shell"],
            "requirements": {"networkAccess": "declared-only"},
        },
        "budget": _budget(),
    }
    if server_id is not None:
        payload["serverId"] = server_id
    return payload


def _plan_payload(*, server_id: str | None = "srv_agent") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requestId": "req-plan-1",
        "actor": "user-1",
        "idempotencyKey": "idem-plan-1",
        "expectedStateVersion": 1,
        "proposal": {
            "draft": workflow_design_draft(),
            "planner": {
                "adapterId": "fixture.fastq-qc.v1",
                "adapterVersion": "1.0.0",
                "modelRef": "provider-neutral:fixture",
            },
        },
    }
    if server_id is not None:
        payload["serverId"] = server_id
    return payload


def _approval_payload(*, server_id: str | None = "srv_agent") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requestId": "req-approve-1",
        "actor": "user-1",
        "idempotencyKey": "idem-approve-1",
        "expectedStateVersion": 3,
        "decision": "approve",
        "expectedPlanHash": "a" * 64,
    }
    if server_id is not None:
        payload["serverId"] = server_id
    return payload


def _cancel_payload(*, server_id: str | None = "srv_agent") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requestId": "req-cancel-1",
        "actor": "user-1",
        "idempotencyKey": "idem-cancel-1",
        "expectedStateVersion": 3,
        "reason": "Operator cancelled before execution.",
    }
    if server_id is not None:
        payload["serverId"] = server_id
    return payload


class FakeRemoteRunnerManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call_remote_endpoint(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        endpoint_id = kwargs["endpoint_id"]
        if endpoint_id == AGENT_SESSION_LIST:
            return [{"sessionId": "ags_1"}]
        if endpoint_id == AGENT_SESSION_EVENTS_READ:
            return [{"eventId": "agev_1"}]
        if endpoint_id == AGENT_SESSION_PLANS_READ:
            return [{"planRevisionId": "agp_1"}]
        if endpoint_id == AGENT_SESSION_APPROVALS_READ:
            return [{"approvalId": "aga_1"}]
        if endpoint_id == AGENT_SESSION_CREATE:
            return {"sessionId": "ags_1", "status": "created"}
        if endpoint_id == AGENT_SESSION_READ:
            return {"sessionId": kwargs["path_values"]["session_id"], "status": "created"}
        if endpoint_id in {
            AGENT_SESSION_PLAN,
            AGENT_SESSION_APPROVAL,
            AGENT_SESSION_REPLAN,
            AGENT_SESSION_CANCEL,
        }:
            return {
                "sessionId": kwargs["path_values"]["session_id"],
                "endpointId": endpoint_id,
            }
        raise AssertionError(f"unexpected endpoint: {endpoint_id}")


class FakeRunnerOps(RunnerOperationsMixin):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.manager = FakeRemoteRunnerManager()
        self._service_locator = type(
            "ServiceLocator",
            (),
            {"remote_runner_manager": self.manager},
        )()
        self.selected_server_id = ""
        self.agents = AgentManager(self)

    def _ensure_initialized(self) -> None:
        return None

    def _require_existing_runner_ready(self, *, preferred_server_id: str | None = None):
        self.selected_server_id = preferred_server_id or "default"
        return "srv_agent", object(), {"ready": True}


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, dict[str, Any]]] = []

    def list_agent_sessions(self, *, server_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("list", server_id, {}))
        return {"data": {"items": []}}

    def create_agent_session(
        self,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command("create", "", payload, server_id)

    def get_agent_session(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("get", server_id, {"sessionId": session_id}))
        return {"data": {"sessionId": session_id}}

    def list_agent_session_events(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._child("events", session_id, server_id)

    def list_agent_session_plans(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._child("plans", session_id, server_id)

    def list_agent_session_approvals(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._child("approvals", session_id, server_id)

    def plan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command("plan", session_id, payload, server_id)

    def approve_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command("approval", session_id, payload, server_id)

    def replan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command("replan", session_id, payload, server_id)

    def cancel_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command("cancel", session_id, payload, server_id)

    def _child(self, child: str, session_id: str, server_id: str | None) -> dict[str, Any]:
        self.calls.append((child, server_id, {"sessionId": session_id}))
        return {"data": {"items": []}}

    def _command(
        self,
        action: str,
        session_id: str,
        payload: dict[str, Any],
        server_id: str | None,
    ) -> dict[str, Any]:
        self.calls.append((action, server_id, dict(payload)))
        return {"data": {"sessionId": session_id or "ags_1", "action": action}}


def test_local_models_accept_only_local_server_routing_and_strip_it_explicitly() -> None:
    request = AgentSessionCreateRequest.model_validate(_create_payload())
    server_id, remote_payload = split_agent_routing(request)

    assert server_id == "srv_agent"
    assert "serverId" not in remote_payload
    assert remote_payload["contractVersion"] == "agent-session.v1"
    assert remote_payload["budget"] == _budget()

    provider_specific = _plan_payload()
    provider_specific["proposal"]["planner"]["provider"] = "vendor-a"
    with pytest.raises(ValidationError) as provider_exc:
        AgentPlanRequest.model_validate(provider_specific)
    assert provider_exc.value.errors()[0]["type"] == "extra_forbidden"

    credential = _create_payload()
    credential["goal"]["context"]["apiKey"] = "must-not-pass"
    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        AgentSessionCreateRequest.model_validate(credential)


def test_local_write_routes_pass_server_separately_from_remote_contract(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.agent_session_service.runtime_service", lambda: runtime)

    created = asyncio.run(create_agent_session_api(AgentSessionCreateRequest.model_validate(_create_payload())))
    planned = asyncio.run(
        plan_agent_session_api(
            "ags_1",
            AgentPlanRequest.model_validate(_plan_payload()),
        )
    )
    approved = asyncio.run(
        approve_agent_session_api(
            "ags_1",
            AgentApprovalRequest.model_validate(_approval_payload()),
        )
    )
    replan_payload = _plan_payload()
    replan_payload["requestId"] = "req-replan-1"
    replan_payload["idempotencyKey"] = "idem-replan-1"
    replan_payload["expectedStateVersion"] = 4
    replan_payload["reason"] = "Use the corrected sample pairing."
    replanned = asyncio.run(
        replan_agent_session_api(
            "ags_1",
            AgentReplanRequest.model_validate(replan_payload),
        )
    )
    cancelled = asyncio.run(
        cancel_agent_session_api(
            "ags_1",
            AgentCancelRequest.model_validate(_cancel_payload()),
        )
    )

    assert created["data"]["action"] == "create"
    assert planned["data"]["action"] == "plan"
    assert approved["data"]["action"] == "approval"
    assert replanned["data"]["action"] == "replan"
    assert cancelled["data"]["action"] == "cancel"
    assert [call[0] for call in runtime.calls] == [
        "create",
        "plan",
        "approval",
        "replan",
        "cancel",
    ]
    assert all(server_id == "srv_agent" for _, server_id, _ in runtime.calls)
    assert all("serverId" not in payload for _, _, payload in runtime.calls)


def test_local_read_routes_pass_selected_server_id(monkeypatch) -> None:
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.agent_session_service.runtime_service", lambda: runtime)

    listed = asyncio.run(list_agent_sessions_api(refresh=True, serverId="srv_agent"))
    fetched = asyncio.run(get_agent_session_api("ags_1", refresh=True, serverId="srv_agent"))
    events = asyncio.run(list_agent_session_events_api("ags_1", refresh=True, serverId="srv_agent"))
    plans = asyncio.run(list_agent_session_plans_api("ags_1", refresh=True, serverId="srv_agent"))
    approvals = asyncio.run(
        list_agent_session_approvals_api("ags_1", refresh=True, serverId="srv_agent")
    )

    assert listed == {"data": {"items": []}}
    assert fetched == {"data": {"sessionId": "ags_1"}}
    assert events == {"data": {"items": []}}
    assert plans == {"data": {"items": []}}
    assert approvals == {"data": {"items": []}}
    assert runtime.calls == [
        ("list", "srv_agent", {}),
        ("get", "srv_agent", {"sessionId": "ags_1"}),
        ("events", "srv_agent", {"sessionId": "ags_1"}),
        ("plans", "srv_agent", {"sessionId": "ags_1"}),
        ("approvals", "srv_agent", {"sessionId": "ags_1"}),
    ]


def test_runtime_manager_strips_server_id_and_revalidates_remote_payloads() -> None:
    runner = FakeRunnerOps()

    created = runner.create_agent_session(_create_payload())
    planned = runner.plan_agent_session("ags_1", _plan_payload())
    approved = runner.approve_agent_session("ags_1", _approval_payload())
    cancelled = runner.cancel_agent_session("ags_1", _cancel_payload())

    assert created["data"]["status"] == "created"
    assert planned["data"]["endpointId"] == AGENT_SESSION_PLAN
    assert approved["data"]["endpointId"] == AGENT_SESSION_APPROVAL
    assert cancelled["data"]["endpointId"] == AGENT_SESSION_CANCEL
    assert runner.selected_server_id == "srv_agent"
    assert all("serverId" not in call.get("payload", {}) for call in runner.manager.calls)
    assert runner.manager.calls[0]["payload"]["contractVersion"] == "agent-session.v1"
    assert runner.manager.calls[1]["payload"]["proposal"]["planner"] == {
        "adapterId": "fixture.fastq-qc.v1",
        "adapterVersion": "1.0.0",
        "modelRef": "provider-neutral:fixture",
    }

    unsafe = _plan_payload()
    unsafe["proposal"]["planner"]["provider"] = "vendor-a"
    with pytest.raises(ValidationError):
        runner.plan_agent_session("ags_1", unsafe)
    assert len(runner.manager.calls) == 4


def test_runtime_read_operations_cover_all_agent_session_read_endpoints() -> None:
    runner = FakeRunnerOps()

    listed = runner.list_agent_sessions(server_id="srv_agent")
    fetched = runner.get_agent_session("ags_1", server_id="srv_agent")
    events = runner.list_agent_session_events("ags_1", server_id="srv_agent")
    plans = runner.list_agent_session_plans("ags_1", server_id="srv_agent")
    approvals = runner.list_agent_session_approvals("ags_1", server_id="srv_agent")

    assert listed == {"data": {"items": [{"sessionId": "ags_1"}]}}
    assert fetched == {"data": {"sessionId": "ags_1", "status": "created"}}
    assert events == {"data": {"items": [{"eventId": "agev_1"}]}}
    assert plans == {"data": {"items": [{"planRevisionId": "agp_1"}]}}
    assert approvals == {"data": {"items": [{"approvalId": "aga_1"}]}}
    assert [call["endpoint_id"] for call in runner.manager.calls] == [
        AGENT_SESSION_LIST,
        AGENT_SESSION_READ,
        AGENT_SESSION_EVENTS_READ,
        AGENT_SESSION_PLANS_READ,
        AGENT_SESSION_APPROVALS_READ,
    ]
    assert all(call["path_values"].get("session_id", "ags_1") == "ags_1" for call in runner.manager.calls)


def test_local_app_registers_the_complete_agent_session_facade() -> None:
    route_operations = {
        (route.path, method): route.operation_id
        for route in app.routes
        if hasattr(route, "operation_id")
        for method in getattr(route, "methods", set())
    }

    assert route_operations[("/api/v1/agent-sessions", "GET")] == "listAgentSessions"
    assert route_operations[("/api/v1/agent-sessions", "POST")] == "createAgentSession"
    assert route_operations[("/api/v1/agent-sessions/{session_id}", "GET")] == "getAgentSession"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/events", "GET")] == "listAgentSessionEvents"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/plans", "GET")] == "listAgentPlanRevisions"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/approvals", "GET")] == "listAgentApprovals"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/plan", "POST")] == "planAgentSession"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/approval", "POST")] == "approveAgentSessionPlan"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/replan", "POST")] == "replanAgentSession"
    assert route_operations[("/api/v1/agent-sessions/{session_id}/cancel", "POST")] == "cancelAgentSession"
