from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api import agent_session_routes as local_routes
from apps.api import agent_session_service as local_service
from apps.remote_runner import agent_session_routes as remote_routes
from apps.remote_runner import agent_session_service as remote_service
from apps.remote_runner import agent_snapshot_storage
from apps.remote_runner.agent_plan_storage import create_agent_plan_revision
from apps.remote_runner.agent_session_storage import (
    AgentSessionStorageConflictError,
    create_agent_session,
    fetch_agent_session,
    transition_agent_session,
)
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from core.agent_governance_policy import AGENT_REMOTE_GOVERNANCE_SPECS
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.agent import AgentManager
from core.app_runtime.runner_agent_ops import RunnerAgentOperationsMixin
from core.contracts.agent_remote_endpoints import AGENT_SESSION_SNAPSHOT_READ
from core.contracts.agent_snapshot import AgentSessionSnapshot
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS
from tests.helpers.reference_database import make_remote_runner_config
from tests.helpers.workflow_design_drafts import workflow_design_config, workflow_design_draft


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 8,
        "maxToolCalls": 12,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _create_session(
    cfg,
    *,
    request_id: str = "snapshot-create",
    project_id: str = "project-snapshot",
) -> dict[str, Any]:
    return create_agent_session(
        cfg,
        project_id=project_id,
        goal={"summary": "Create an atomic AgentSession snapshot."},
        budget=_budget(),
        creation_request_id=request_id,
        created_by="user-1",
    )


def _minimal_snapshot(session_id: str = "ags_snapshot") -> dict[str, Any]:
    payload_hash = hashlib.sha256(b"{}").hexdigest()
    return AgentSessionSnapshot.model_validate(
        {
            "contractVersion": "agent-session-snapshot.v1",
            "session": {
                "contractVersion": "agent-session.v1",
                "sessionId": session_id,
                "projectId": "project-snapshot",
                "goal": {"summary": "Read one atomic snapshot."},
                "constraints": {},
                "budget": _budget(),
                "status": "created",
                "stateVersion": 1,
                "planGeneration": 0,
                "planner": {},
                "lastErrorCode": "",
                "creationRequestId": "create-snapshot",
                "createdBy": "user-1",
                "createdAt": "2026-07-16T00:00:00Z",
                "updatedAt": "2026-07-16T00:00:00Z",
            },
            "events": [
                {
                    "schemaVersion": "agent-event.v1",
                    "eventId": "agev_snapshot",
                    "sessionId": session_id,
                    "sequence": 1,
                    "eventType": "agent.session_created",
                    "toStatus": "created",
                    "stateVersion": 1,
                    "planGeneration": 0,
                    "requestId": "create-snapshot",
                    "idempotencyKey": "create:create-snapshot",
                    "actor": "user-1",
                    "payload": {},
                    "payloadHash": payload_hash,
                    "eventHash": "e" * 64,
                    "createdAt": "2026-07-16T00:00:00Z",
                }
            ],
            "plans": [],
            "approvals": [],
        }
    ).runtime_payload()


def test_snapshot_is_one_consistent_read_during_concurrent_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    created = _create_session(cfg)
    session_id = str(created["sessionId"])
    original_converter = agent_snapshot_storage.agent_session_row_to_dict
    writer_errors: list[Exception] = []
    writer_finished = threading.Event()

    def commit_cancel() -> None:
        try:
            transition_agent_session(
                cfg,
                session_id,
                expected_state_version=1,
                event_type="agent.session_cancelled",
                to_status="cancelled",
                request_id="cancel-during-snapshot",
                actor="user-1",
                idempotency_key="cancel-during-snapshot",
                payload={"reason": "concurrent test writer"},
            )
        except Exception as exc:  # pragma: no cover - asserted in reader thread
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    def convert_after_concurrent_commit(row) -> dict[str, Any]:
        session = original_converter(row)
        writer = threading.Thread(target=commit_cancel, daemon=True)
        writer.start()
        assert writer_finished.wait(5), "concurrent writer did not commit"
        writer.join(timeout=1)
        return session

    monkeypatch.setattr(
        agent_snapshot_storage,
        "agent_session_row_to_dict",
        convert_after_concurrent_commit,
    )

    snapshot = agent_snapshot_storage.read_agent_session_snapshot(cfg, session_id)

    assert writer_errors == []
    assert set(snapshot) == {
        "contractVersion",
        "session",
        "events",
        "plans",
        "approvals",
    }
    assert snapshot["contractVersion"] == "agent-session-snapshot.v1"
    assert snapshot["session"]["stateVersion"] == 1
    assert snapshot["session"]["status"] == "created"
    assert [item["eventType"] for item in snapshot["events"]] == [
        "agent.session_created"
    ]
    current = fetch_agent_session(cfg, session_id)
    assert current is not None
    assert current["stateVersion"] == 2
    assert current["status"] == "cancelled"
    monkeypatch.setattr(
        agent_snapshot_storage,
        "agent_session_row_to_dict",
        original_converter,
    )
    cancelled_snapshot = agent_snapshot_storage.read_agent_session_snapshot(
        cfg,
        session_id,
    )
    assert cancelled_snapshot["session"]["status"] == "cancelled"
    assert cancelled_snapshot["session"]["planGeneration"] == 0
    assert cancelled_snapshot["plans"] == []


def test_snapshot_rejects_corrupted_event_hash_chain(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    session_id = str(_create_session(cfg)["sessionId"])
    with agent_snapshot_storage.get_connection(cfg) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            ("agent_events_no_update",),
        ).fetchone()["sql"]
        connection.execute("DROP TRIGGER agent_events_no_update")
        connection.execute(
            "UPDATE agent_events SET event_hash = ? WHERE session_id = ?",
            ("f" * 64, session_id),
        )
        connection.execute(str(trigger_sql))
        connection.commit()

    with pytest.raises(
        AgentSessionStorageConflictError,
        match="AGENT_SESSION_EVENT_HASH_CHAIN_INVALID: EVENT_HASH_MISMATCH",
    ):
        agent_snapshot_storage.read_agent_session_snapshot(cfg, session_id)


def test_snapshot_contract_revalidates_plan_canonical_payload(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    created = _create_session(
        cfg,
        request_id="snapshot-with-plan",
        project_id="proj_design",
    )
    planning = transition_agent_session(
        cfg,
        str(created["sessionId"]),
        expected_state_version=1,
        event_type="agent.plan_requested",
        to_status="planning",
        request_id="snapshot-plan",
        actor="user-1",
        idempotency_key="snapshot-plan",
        payload={"planner": {"adapterId": "fixture.snapshot.v1"}},
        plan_generation=1,
        planner={"adapterId": "fixture.snapshot.v1"},
    )["session"]
    planning_without_plan = agent_snapshot_storage.read_agent_session_snapshot(
        cfg,
        str(created["sessionId"]),
    )
    assert planning_without_plan["session"]["status"] == "planning"
    assert planning_without_plan["plans"] == []
    draft = create_workflow_design_draft(cfg, workflow_design_draft())
    plan = create_agent_plan_revision(
        cfg,
        session_id=str(created["sessionId"]),
        plan_generation=1,
        draft_id=str(draft["draftId"]),
        draft_revision=int(draft["revision"]),
        proposal={
            "draft": draft["draft"],
            "planner": {"adapterId": "fixture.snapshot.v1"},
        },
        validation={"valid": True, "issues": []},
        budget=_budget(),
        created_by="fixture.snapshot.v1",
    )
    planning_snapshot = agent_snapshot_storage.read_agent_session_snapshot(
        cfg,
        str(created["sessionId"]),
    )
    assert planning_snapshot["session"]["status"] == "planning"
    assert "activePlanHash" not in planning_snapshot["session"]
    assert len(planning_snapshot["plans"]) == 1
    cancelled_with_unactivated_plan = copy.deepcopy(planning_snapshot)
    cancelled_with_unactivated_plan["session"]["status"] = "cancelled"
    cancelled_with_unactivated_plan["session"]["stateVersion"] += 1
    cancelled_with_unactivated_plan["session"]["cancelledAt"] = (
        "2026-07-16T01:00:00Z"
    )
    cancelled_with_unactivated_plan["events"].append(
        {
            "schemaVersion": "agent-event.v1",
            "eventId": "agev_cancelled_with_plan",
            "sessionId": created["sessionId"],
            "sequence": len(cancelled_with_unactivated_plan["events"]) + 1,
            "eventType": "agent.session_cancelled",
            "fromStatus": "planning",
            "toStatus": "cancelled",
            "stateVersion": cancelled_with_unactivated_plan["session"]["stateVersion"],
            "planGeneration": 1,
            "requestId": "cancel-with-unactivated-plan",
            "idempotencyKey": "cancel-with-unactivated-plan",
            "actor": "user-1",
            "payload": {},
            "payloadHash": hashlib.sha256(b"{}").hexdigest(),
            "eventHash": "c" * 64,
            "prevEventHash": planning_snapshot["events"][-1]["eventHash"],
            "createdAt": "2026-07-16T01:00:00Z",
        }
    )
    AgentSessionSnapshot.model_validate(cancelled_with_unactivated_plan)
    transition_agent_session(
        cfg,
        str(created["sessionId"]),
        expected_state_version=int(planning["stateVersion"]),
        expected_plan_generation=1,
        event_type="agent.plan_validated",
        to_status="awaiting_approval",
        request_id="snapshot-plan-validated",
        actor="fixture.snapshot.v1",
        idempotency_key="snapshot-plan-validated",
        payload={"planHash": plan["planHash"]},
        active_draft_id=draft["draftId"],
        active_draft_revision=draft["revision"],
        active_plan_hash=plan["planHash"],
    )
    snapshot = agent_snapshot_storage.read_agent_session_snapshot(
        cfg,
        str(created["sessionId"]),
    )
    assert hashlib.sha256(
        snapshot["plans"][0]["canonicalPayload"].encode("utf-8")
    ).hexdigest() == snapshot["plans"][0]["planHash"]

    tampered = copy.deepcopy(snapshot)
    canonical = json.loads(tampered["plans"][0]["canonicalPayload"])
    canonical["draftRevision"] += 1
    canonical_payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    tampered["plans"][0]["canonicalPayload"] = canonical_payload
    tampered["plans"][0]["planHash"] = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValidationError, match="AGENT_PLAN_CANONICAL_PAYLOAD_MISMATCH"):
        AgentSessionSnapshot.model_validate(tampered)

    for status in (
        "awaiting_approval",
        "plan_failed",
        "changes_requested",
        "ready_to_run",
    ):
        status_snapshot = copy.deepcopy(snapshot)
        status_snapshot["session"]["status"] = status
        status_snapshot["events"][-1]["toStatus"] = status
        AgentSessionSnapshot.model_validate(status_snapshot)
        for field in ("activeDraftId", "activeDraftRevision", "activePlanHash"):
            status_snapshot["session"].pop(field, None)
        with pytest.raises(
            ValidationError,
            match="AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_REQUIRED",
        ):
            AgentSessionSnapshot.model_validate(status_snapshot)

    partial_active = copy.deepcopy(snapshot)
    partial_active["session"].pop("activePlanHash")
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_PARTIAL",
    ):
        AgentSessionSnapshot.model_validate(partial_active)

    created_with_plan = copy.deepcopy(snapshot)
    created_with_plan["session"]["status"] = "created"
    created_with_plan["events"][-1]["toStatus"] = "created"
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SNAPSHOT_CREATED_CURRENT_PLAN_FORBIDDEN",
    ):
        AgentSessionSnapshot.model_validate(created_with_plan)


def test_snapshot_contract_binds_latest_event_to_session_projection() -> None:
    snapshot = _minimal_snapshot()
    wrong_status = copy.deepcopy(snapshot)
    wrong_status["session"]["status"] = "planning"
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SNAPSHOT_EVENT_STATUS_MISMATCH",
    ):
        AgentSessionSnapshot.model_validate(wrong_status)

    wrong_generation = copy.deepcopy(snapshot)
    wrong_generation["session"]["planGeneration"] = 1
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SNAPSHOT_EVENT_GENERATION_MISMATCH",
    ):
        AgentSessionSnapshot.model_validate(wrong_generation)


def test_manager_requires_server_binding_and_validates_remote_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AgentManager(object())
    snapshot = _minimal_snapshot()
    captured: dict[str, Any] = {}

    def fake_read(endpoint_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["endpoint_id"] = endpoint_id
        captured.update(kwargs)
        return {"data": snapshot}

    monkeypatch.setattr(manager, "read_existing_remote_endpoint", fake_read)

    assert manager.get_agent_session_snapshot(
        "ags_snapshot",
        server_id=" srv_bound ",
    ) == {"data": snapshot}
    assert captured == {
        "endpoint_id": AGENT_SESSION_SNAPSHOT_READ,
        "path_values": {"session_id": "ags_snapshot"},
        "preferred_server_id": "srv_bound",
    }
    with pytest.raises(RuntimeServiceError, match="AGENT_SESSION_SERVER_ID_REQUIRED"):
        manager.get_agent_session_snapshot("ags_snapshot", server_id="   ")

    invalid = dict(snapshot) | {"unexpected": True}
    monkeypatch.setattr(
        manager,
        "read_existing_remote_endpoint",
        lambda *_args, **_kwargs: {"data": invalid},
    )
    with pytest.raises(RuntimeServiceError, match="AGENT_SESSION_SNAPSHOT_INVALID"):
        manager.get_agent_session_snapshot("ags_snapshot", server_id="srv_bound")

    wrong_identity = _minimal_snapshot("ags_other")
    monkeypatch.setattr(
        manager,
        "read_existing_remote_endpoint",
        lambda *_args, **_kwargs: {"data": wrong_identity},
    )
    with pytest.raises(
        RuntimeServiceError,
        match="AGENT_SESSION_SNAPSHOT_IDENTITY_MISMATCH",
    ):
        manager.get_agent_session_snapshot("ags_snapshot", server_id="srv_bound")


def test_runner_mixin_forwards_snapshot_identity_without_primary_fallback() -> None:
    calls: list[tuple[str, str]] = []

    class FakeAgents:
        @staticmethod
        def get_agent_session_snapshot(
            session_id: str,
            *,
            server_id: str,
        ) -> dict[str, Any]:
            calls.append((session_id, server_id))
            return {"data": _minimal_snapshot(session_id)}

    class FakeRuntime(RunnerAgentOperationsMixin):
        agents = FakeAgents()

    result = FakeRuntime().get_agent_session_snapshot(
        "ags_snapshot",
        server_id="srv_bound",
    )
    assert result["data"]["session"]["sessionId"] == "ags_snapshot"
    assert calls == [("ags_snapshot", "srv_bound")]


def test_local_snapshot_cache_is_server_scoped_and_refreshable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _minimal_snapshot()

    class FakeRuntime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def get_agent_session_snapshot(
            self,
            session_id: str,
            *,
            server_id: str,
        ) -> dict[str, Any]:
            self.calls.append((server_id, session_id))
            return {"data": snapshot}

    runtime = FakeRuntime()
    monkeypatch.setattr(local_service, "runtime_service", lambda: runtime)
    asyncio.run(
        local_service.invalidate_response_cache(
            prefixes=("agent_session_snapshot:",)
        )
    )

    async def exercise_cache() -> None:
        await local_service.get_agent_session_snapshot_from_request(
            "ags_snapshot", refresh=False, server_id="srv_a"
        )
        await local_service.get_agent_session_snapshot_from_request(
            "ags_snapshot", refresh=False, server_id="srv_a"
        )
        await local_service.get_agent_session_snapshot_from_request(
            "ags_snapshot", refresh=False, server_id="srv_b"
        )
        await local_service.get_agent_session_snapshot_from_request(
            "ags_snapshot", refresh=True, server_id="srv_a"
        )

    asyncio.run(exercise_cache())
    assert runtime.calls == [
        ("srv_a", "ags_snapshot"),
        ("srv_b", "ags_snapshot"),
        ("srv_a", "ags_snapshot"),
    ]
    with pytest.raises(ValueError, match="AGENT_SESSION_SERVER_ID_REQUIRED"):
        asyncio.run(
            local_service.get_agent_session_snapshot_from_request(
                "ags_snapshot",
                refresh=False,
                server_id="   ",
            )
        )
    with pytest.raises(ValueError, match="AGENT_SESSION_ID_REQUIRED"):
        asyncio.run(
            local_service.get_agent_session_snapshot_from_request(
                "   ",
                refresh=False,
                server_id="srv_a",
            )
        )


def test_snapshot_routes_and_endpoint_governance_are_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_called: dict[str, Any] = {}

    async def fake_local(session_id: str, **kwargs: Any) -> dict[str, Any]:
        local_called.update(session_id=session_id, **kwargs)
        return {"data": _minimal_snapshot(session_id)}

    monkeypatch.setattr(
        local_routes,
        "get_agent_session_snapshot_from_request",
        fake_local,
    )
    local_app = FastAPI()
    local_app.include_router(local_routes.router)
    client = TestClient(local_app)
    assert client.get("/api/v1/agent-sessions/ags_route/snapshot").status_code == 422
    response = client.get(
        "/api/v1/agent-sessions/ags_route/snapshot",
        params={"serverId": "srv_route", "refresh": "true"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["contractVersion"] == "agent-session-snapshot.v1"
    assert local_called == {
        "session_id": "ags_route",
        "refresh": True,
        "server_id": "srv_route",
    }

    remote_called: dict[str, Any] = {}

    async def fake_remote(session_id: str, authorization: str | None) -> dict[str, Any]:
        remote_called.update(session_id=session_id, authorization=authorization)
        return {"data": _minimal_snapshot(session_id)}

    monkeypatch.setattr(
        remote_routes,
        "get_agent_session_snapshot_from_http",
        fake_remote,
    )
    result = asyncio.run(
        remote_routes.get_agent_session_snapshot_api(
            "ags_remote",
            "Bearer runner-token",
        )
    )
    assert result["data"]["contractVersion"] == "agent-session-snapshot.v1"
    assert remote_called == {
        "session_id": "ags_remote",
        "authorization": "Bearer runner-token",
    }

    endpoint = REMOTE_ENDPOINTS[AGENT_SESSION_SNAPSHOT_READ]
    assert endpoint.method == "GET"
    assert endpoint.path_template == "/api/v1/agent-sessions/{session_id}/snapshot"
    assert endpoint.operation_id == "getAgentSessionSnapshot"
    assert endpoint.response_schema == "agent-session-snapshot.v1"
    assert any(
        spec[0] == "GET"
        and spec[1] == "/api/v1/agent-sessions/{session_id}/snapshot"
        and spec[3] == "agent_session.snapshot.read"
        and spec[-1] == ("workflow-operator", "auditor")
        for spec in AGENT_REMOTE_GOVERNANCE_SPECS
    )


def test_remote_snapshot_facade_authorizes_dedicated_read_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _minimal_snapshot()
    captured: dict[str, Any] = {}
    cfg = object()

    def fake_authorized_config(
        authorization: str | None,
        *,
        action: str,
    ) -> object:
        captured.update(authorization=authorization, action=action)
        return cfg

    monkeypatch.setattr(remote_service, "authorized_config", fake_authorized_config)
    monkeypatch.setattr(
        remote_service,
        "read_agent_session_snapshot",
        lambda selected_cfg, session_id: (
            captured.update(cfg=selected_cfg, session_id=session_id) or snapshot
        ),
    )

    result = asyncio.run(
        remote_service.get_agent_session_snapshot_from_http(
            "ags_snapshot",
            "Bearer runner-token",
        )
    )
    assert result == {"data": snapshot}
    assert captured == {
        "authorization": "Bearer runner-token",
        "action": "agent_session.snapshot.read",
        "cfg": cfg,
        "session_id": "ags_snapshot",
    }
