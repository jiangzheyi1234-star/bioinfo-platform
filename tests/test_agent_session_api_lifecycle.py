from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.remote_runner.agent_plan_storage import list_agent_approvals, list_agent_plan_revisions
from apps.remote_runner.agent_session_storage import fetch_agent_events
from apps.remote_runner.main import app
from apps.remote_runner.storage import list_runs
from apps.remote_runner.workflow_revision_storage import fetch_workflow_revision
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.helpers.workflow_design_drafts import (
    workflow_design_config,
    workflow_design_draft,
    workflow_design_tool_manifest,
)


def _data(response) -> Any:
    return json.loads(response.content)["data"]


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 8,
        "maxToolCalls": 12,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _create_payload() -> dict[str, Any]:
    return {
        "contractVersion": "agent-session.v1",
        "projectId": "proj_design",
        "creationRequestId": "create-fastq-qc-agent",
        "createdBy": "user-1",
        "goal": {
            "summary": "Inspect these FASTQ files and produce a shareable QC report.",
            "successCriteria": ["Produce a validated QC report."],
            "context": {"inputManifestDigest": "sha256:fixture-inputs"},
        },
        "constraints": {
            "forbiddenActions": ["arbitrary_shell", "undeclared_network"],
            "requirements": {"runner": "configured"},
        },
        "budget": _budget(),
    }


def _plan_payload(*, request_id: str, state_version: int, draft: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "requestId": request_id,
        "actor": "user-1",
        "idempotencyKey": request_id,
        "expectedStateVersion": state_version,
        "proposal": {
            "draft": draft or workflow_design_draft(),
            "planner": {
                "adapterId": "fixture.fastq-qc.v1",
                "adapterVersion": "1",
                "modelRef": "deterministic-fixture",
            },
        },
    }


def test_agent_principal_context_is_authenticated_and_minimal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.api_token_actor = "bound-runner-user"
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)

    unauthorized = client.get("/api/v1/agent-principal-context")
    authorized = client.get(
        "/api/v1/agent-principal-context",
        headers={"Authorization": "Bearer workflow-design-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert _data(authorized) == {
        "schemaVersion": "agent-principal-context.v1",
        "actor": "bound-runner-user",
    }


def test_agent_session_remote_api_plan_approve_compile_and_replan(monkeypatch, tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.api_token_actor = "user-1"
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}

    created_response = client.post("/api/v1/agent-sessions", headers=headers, json=_create_payload())
    assert created_response.status_code == 201
    created = _data(created_response)
    session_id = created["sessionId"]
    assert created["status"] == "created"
    assert created["stateVersion"] == 1

    plan_request = _plan_payload(request_id="plan-fastq-qc-1", state_version=1)
    planned_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/plan",
        headers=headers,
        json=plan_request,
    )
    assert planned_response.status_code == 200, planned_response.text
    planned = _data(planned_response)
    assert planned["session"]["status"] == "awaiting_approval"
    assert planned["session"]["stateVersion"] == 3
    assert planned["session"]["planGeneration"] == 1
    assert planned["validation"]["valid"] is True
    assert planned["plan"]["planHash"] == planned["session"]["activePlanHash"]
    assert planned["plan"]["draftId"] == planned["draft"]["draftId"]
    assert planned["draft"]["draft"]["provenance"]["agentSessionId"] == session_id
    assert list_runs(cfg) == []

    replay_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/plan",
        headers=headers,
        json=plan_request,
    )
    assert replay_response.status_code == 200
    assert _data(replay_response)["plan"]["planRevisionId"] == planned["plan"]["planRevisionId"]
    assert len(list_agent_plan_revisions(cfg, session_id)) == 1

    approval_request = {
        "requestId": "approve-fastq-qc-1",
        "actor": "user-1",
        "idempotencyKey": "approve-fastq-qc-1",
        "expectedStateVersion": planned["session"]["stateVersion"],
        "decision": "approve",
        "expectedPlanHash": planned["plan"]["planHash"],
        "reason": "Reviewed exact tool revision, inputs, parameters, and outputs.",
    }
    approved_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/approval",
        headers=headers,
        json=approval_request,
    )
    assert approved_response.status_code == 200, approved_response.text
    approved = _data(approved_response)
    assert approved["session"]["status"] == "ready_to_run"
    assert approved["session"]["stateVersion"] == 4
    workflow_revision_id = approved["session"]["workflowRevisionId"]
    assert workflow_revision_id.startswith("wfrev_")
    assert approved["compiled"]["workflowRevisionId"] == workflow_revision_id
    assert fetch_workflow_revision(cfg, workflow_revision_id) is not None
    assert len(list_agent_approvals(cfg, session_id)) == 1
    assert list_runs(cfg) == []

    events = fetch_agent_events(cfg, session_id)
    assert [event["eventType"] for event in events] == [
        "agent.session_created",
        "agent.plan_requested",
        "agent.plan_validated",
        "agent.approval_granted",
        "agent.workflow_revision_compiled",
    ]
    assert events[-1]["prevEventHash"] == events[-2]["eventHash"]

    approval_replay = client.post(
        f"/api/v1/agent-sessions/{session_id}/approval",
        headers=headers,
        json=approval_request,
    )
    assert approval_replay.status_code == 200
    assert _data(approval_replay)["session"]["workflowRevisionId"] == workflow_revision_id
    assert len(list_agent_approvals(cfg, session_id)) == 1
    assert list_runs(cfg) == []

    replan_request = _plan_payload(
        request_id="replan-fastq-qc-2",
        state_version=approved["session"]["stateVersion"],
    ) | {"reason": "Re-evaluate the same evidence with a new immutable plan generation."}
    replanned_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/replan",
        headers=headers,
        json=replan_request,
    )
    assert replanned_response.status_code == 200, replanned_response.text
    replanned = _data(replanned_response)
    assert replanned["session"]["status"] == "awaiting_approval"
    assert replanned["session"]["planGeneration"] == 2
    assert replanned["session"]["workflowRevisionId"] is None
    assert replanned["plan"]["parentPlanRevisionId"] == planned["plan"]["planRevisionId"]
    assert replanned["draft"]["parentDraftId"] == planned["draft"]["draftId"]
    assert replanned["plan"]["planHash"] != planned["plan"]["planHash"]
    assert fetch_workflow_revision(cfg, workflow_revision_id) is not None
    assert len(list_agent_plan_revisions(cfg, session_id)) == 2
    assert list_runs(cfg) == []

    listed = client.get("/api/v1/agent-sessions", headers=headers)
    events_response = client.get(f"/api/v1/agent-sessions/{session_id}/events", headers=headers)
    plans_response = client.get(f"/api/v1/agent-sessions/{session_id}/plans", headers=headers)
    approvals_response = client.get(f"/api/v1/agent-sessions/{session_id}/approvals", headers=headers)
    assert _data(listed)["items"][0]["sessionId"] == session_id
    assert len(_data(events_response)["items"]) == 7
    assert len(_data(plans_response)["items"]) == 2
    assert len(_data(approvals_response)["items"]) == 1


def test_agent_session_invalid_plan_is_durable_and_never_creates_run(monkeypatch, tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.api_token_actor = "user-1"
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(client.post("/api/v1/agent-sessions", headers=headers, json=_create_payload()))
    invalid_draft = workflow_design_draft()
    invalid_draft["inputs"] = []

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json=_plan_payload(request_id="plan-invalid-1", state_version=1, draft=invalid_draft),
    )

    assert response.status_code == 200
    result = _data(response)
    assert result["session"]["status"] == "plan_failed"
    assert result["session"]["lastErrorCode"] == "INPUT_REQUIRED"
    assert result["plan"]["validation"]["valid"] is False
    assert result["session"]["activePlanHash"] == result["plan"]["planHash"]
    assert result["validation"]["valid"] is False
    assert len(list_agent_plan_revisions(cfg, created["sessionId"])) == 1
    assert list_agent_approvals(cfg, created["sessionId"]) == []
    assert list_runs(cfg) == []


def test_agent_session_http_binds_actor_protects_draft_and_replays_cancel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.api_token_actor = "user-1"
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}

    assert client.get(
        "/api/v1/agent-sessions/ags_missing/events",
        headers=headers,
    ).status_code == 404
    created = _data(client.post("/api/v1/agent-sessions", headers=headers, json=_create_payload()))
    session_id = created["sessionId"]

    spoofed = _plan_payload(request_id="plan-protected-1", state_version=1)
    spoofed["actor"] = "intruder"
    assert client.post(
        f"/api/v1/agent-sessions/{session_id}/plan",
        headers=headers,
        json=spoofed,
    ).status_code == 403

    plan_request = _plan_payload(request_id="plan-protected-1", state_version=1)
    planned_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/plan",
        headers=headers,
        json=plan_request,
    )
    assert planned_response.status_code == 200
    planned = _data(planned_response)

    changed_replay = json.loads(json.dumps(plan_request))
    changed_replay["expectedStateVersion"] = 2
    assert client.post(
        f"/api/v1/agent-sessions/{session_id}/plan",
        headers=headers,
        json=changed_replay,
    ).status_code == 409

    draft_response = client.patch(
        f"/api/v1/workflow-design-drafts/{planned['draft']['draftId']}",
        headers=headers,
        json={
            "draft": planned["draft"]["draft"],
            "expectedRevision": planned["draft"]["revision"],
        },
    )
    assert draft_response.status_code == 409
    assert "AGENT_MANAGED_WORKFLOW_DESIGN_DRAFT_IMMUTABLE" in draft_response.text

    cancel_request = {
        "requestId": "cancel-protected-1",
        "actor": "user-1",
        "idempotencyKey": "cancel-protected-1",
        "expectedStateVersion": planned["session"]["stateVersion"],
        "reason": "Stop before any run is submitted.",
    }
    cancelled = client.post(
        f"/api/v1/agent-sessions/{session_id}/cancel",
        headers=headers,
        json=cancel_request,
    )
    replayed = client.post(
        f"/api/v1/agent-sessions/{session_id}/cancel",
        headers=headers,
        json=cancel_request,
    )
    assert cancelled.status_code == 200
    assert replayed.status_code == 200
    assert _data(replayed)["status"] == "cancelled"
    assert [
        event["eventType"] for event in fetch_agent_events(cfg, session_id)
    ].count("agent.session_cancelled") == 1
    assert list_runs(cfg) == []


def test_invalid_replan_revision_remains_parent_of_next_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.api_token_actor = "user-1"
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(client.post("/api/v1/agent-sessions", headers=headers, json=_create_payload()))
    session_id = created["sessionId"]
    first = _data(
        client.post(
            f"/api/v1/agent-sessions/{session_id}/plan",
            headers=headers,
            json=_plan_payload(request_id="plan-lineage-1", state_version=1),
        )
    )
    changes = _data(
        client.post(
            f"/api/v1/agent-sessions/{session_id}/approval",
            headers=headers,
            json={
                "requestId": "changes-lineage-1",
                "actor": "user-1",
                "idempotencyKey": "changes-lineage-1",
                "expectedStateVersion": first["session"]["stateVersion"],
                "decision": "request_changes",
                "expectedPlanHash": first["plan"]["planHash"],
                "reason": "Exercise a rejected intermediate plan.",
            },
        )
    )
    invalid_draft = workflow_design_draft()
    invalid_draft["inputs"] = []
    invalid_payload = _plan_payload(
        request_id="replan-lineage-2",
        state_version=changes["session"]["stateVersion"],
        draft=invalid_draft,
    ) | {"reason": "Try an invalid input-free plan."}
    invalid = _data(
        client.post(
            f"/api/v1/agent-sessions/{session_id}/replan",
            headers=headers,
            json=invalid_payload,
        )
    )
    assert invalid["session"]["status"] == "plan_failed"
    assert invalid["plan"]["planGeneration"] == 2

    third_payload = _plan_payload(
        request_id="replan-lineage-3",
        state_version=invalid["session"]["stateVersion"],
    ) | {"reason": "Restore the validated input-bound plan."}
    third_response = client.post(
        f"/api/v1/agent-sessions/{session_id}/replan",
        headers=headers,
        json=third_payload,
    )
    assert third_response.status_code == 200, third_response.text
    third = _data(third_response)
    assert third["session"]["planGeneration"] == 3
    assert third["plan"]["parentPlanRevisionId"] == invalid["plan"]["planRevisionId"]
    assert [
        item["planGeneration"] for item in list_agent_plan_revisions(cfg, session_id)
    ] == [1, 2, 3]
    assert list_runs(cfg) == []
