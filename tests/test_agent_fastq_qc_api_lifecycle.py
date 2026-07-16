from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.agent_fastq_qc_planner import build_fastq_qc_plan_proposal
from apps.api.agent_session_models import AgentPlanRequest
from apps.api.agent_session_routes import plan_agent_session_api
from apps.api.capability_graph_service import CapabilityGraphService
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_sources import all_tool_profiles
from apps.remote_runner.main import app
from apps.remote_runner.storage import get_connection, list_runs, list_tools, persist_upload
from apps.remote_runner.tool_platform_storage import upsert_tool_index
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.helpers.workflow_design_drafts import workflow_design_config


class HttpRemoteBridgeRuntime:
    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers
        self.calls: list[tuple[str, str | None]] = []

    def get_agent_session(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._get("session", f"/api/v1/agent-sessions/{session_id}", server_id)

    def get_upload(
        self,
        upload_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._get("upload", f"/api/v1/uploads/{upload_id}", server_id)

    def list_tools(self, server_id: str | None = None) -> dict[str, Any]:
        return self._get("tools", "/api/v1/tools", server_id)

    def list_agent_session_events(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "events",
            f"/api/v1/agent-sessions/{session_id}/events",
            server_id,
        )

    def list_agent_session_plans(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "plans",
            f"/api/v1/agent-sessions/{session_id}/plans",
            server_id,
        )

    def plan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("plan", server_id))
        response = self.client.post(
            f"/api/v1/agent-sessions/{session_id}/plan",
            headers=self.headers,
            json=payload,
        )
        assert response.status_code == 200, response.text
        return response.json()

    def _get(self, action: str, path: str, server_id: str | None) -> dict[str, Any]:
        self.calls.append((action, server_id))
        response = self.client.get(path, headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()


def test_single_fastq_agent_plan_approves_real_fastqc_multiqc_compile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNt b2tlCkFDR1RBQ0dUCisKRkZGRkZGRkYK".replace(" ", ""),
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}

    created_response = client.post(
        "/api/v1/agent-sessions",
        headers=headers,
        json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
    )
    assert created_response.status_code == 201, created_response.text
    created = _data(created_response)
    capability_graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(
        session=created,
        capability_graph=capability_graph,
    )
    plan_request = {
        "requestId": "plan-fastq-qc-1",
        "actor": "user-1",
        "idempotencyKey": "plan-fastq-qc-1",
        "expectedStateVersion": created["stateVersion"],
        "proposal": proposal.runtime_payload(),
    }

    planned_response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json=plan_request,
    )

    assert planned_response.status_code == 200, planned_response.text
    planned = _data(planned_response)
    assert planned["session"]["status"] == "awaiting_approval"
    assert planned["validation"]["valid"] is True
    assert [item["id"] for item in planned["validation"]["orderedSteps"]] == [
        "fastqc",
        "multiqc",
    ]
    assert planned["draft"]["draft"]["inputs"][0]["metadata"]["sha256"] == upload["sha256"]
    assert list_runs(cfg) == []

    approval = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/approval",
        headers=headers,
        json={
            "requestId": "approve-fastq-qc-1",
            "actor": "user-1",
            "idempotencyKey": "approve-fastq-qc-1",
            "expectedStateVersion": planned["session"]["stateVersion"],
            "decision": "approve",
            "expectedPlanHash": planned["plan"]["planHash"],
            "reason": "Reviewed exact input digest, tool revisions, resources, and outputs.",
        },
    )

    assert approval.status_code == 200, approval.text
    approved = _data(approval)
    assert approved["session"]["status"] == "ready_to_run"
    assert approved["compiled"]["workflowRevisionId"] == approved["session"]["workflowRevisionId"]
    export_dir = (
        Path(cfg.work_dir)
        / "workflow-design-exports"
        / planned["draft"]["draftId"]
        / f"rev-{planned['draft']['revision']}"
    )
    generated_rules = (export_dir / "workflow" / "rules" / "generated.smk").read_text(
        encoding="utf-8"
    )
    assert "'v9.8.0/bio/fastqc'" in generated_rules
    assert "'v9.8.0/bio/multiqc'" in generated_rules
    run_config = json.loads((export_dir / ".test" / "run-config.json").read_text(encoding="utf-8"))
    assert run_config["workflow"]["outputs"]["multiqc_report"]["step"] == "multiqc"
    assert run_config["workflow"]["steps"][1]["tool"]["capabilityBundle"]["environmentLock"][
        "packageSpec"
    ] == "bioconda::multiqc=1.34"
    assert list_runs(cfg) == []

    rejected_replan = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/replan",
        headers=headers,
        json={
            "requestId": "replan-fastq-qc-unsupported",
            "actor": "user-1",
            "idempotencyKey": "replan-fastq-qc-unsupported",
            "expectedStateVersion": approved["session"]["stateVersion"],
            "reason": "Change the plan without a typed adjustment.",
            "proposal": proposal.runtime_payload(),
        },
    )
    assert rejected_replan.status_code == 422
    assert "WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED" in rejected_replan.text
    unchanged = _data(
        client.get(
            f"/api/v1/agent-sessions/{created['sessionId']}",
            headers=headers,
        )
    )
    assert unchanged["status"] == "ready_to_run"
    assert unchanged["stateVersion"] == approved["session"]["stateVersion"]
    assert unchanged["planGeneration"] == 1


def test_local_command_only_facade_replays_against_the_real_remote_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-local-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    remote_client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        remote_client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    runtime = HttpRemoteBridgeRuntime(remote_client, headers)
    monkeypatch.setattr("apps.api.agent_session_service.runtime_service", lambda: runtime)
    command = AgentPlanRequest.model_validate(
        {
            "requestId": "local-plan-real-remote",
            "actor": "user-1",
            "idempotencyKey": "local-plan-real-remote",
            "expectedStateVersion": created["stateVersion"],
            "serverId": "srv-real-remote",
        }
    )

    first = asyncio.run(plan_agent_session_api(created["sessionId"], command))
    second = asyncio.run(plan_agent_session_api(created["sessionId"], command))

    assert first == second
    assert first["data"]["session"]["status"] == "awaiting_approval"
    assert sum(action == "tools" for action, _ in runtime.calls) == 1
    assert all(server_id == "srv-real-remote" for _, server_id in runtime.calls)
    assert list_runs(cfg) == []


def test_local_facade_recovers_interrupted_plan_from_durable_proposal_intent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from apps.remote_runner import agent_session_service as remote_agent_service

    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-recovery-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    runtime = HttpRemoteBridgeRuntime(client, headers)
    monkeypatch.setattr("apps.api.agent_session_service.runtime_service", lambda: runtime)
    command = AgentPlanRequest.model_validate(
        {
            "requestId": "plan-interrupted-once",
            "actor": "user-1",
            "idempotencyKey": "plan-interrupted-once",
            "expectedStateVersion": created["stateVersion"],
            "serverId": "srv-recovery",
        }
    )
    original_create = remote_agent_service.create_or_fetch_workflow_design_draft
    original_validate = remote_agent_service.validate_fastq_qc_materialized_plan
    create_calls = 0
    validation_calls = 0

    def interrupt_first_draft(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise RuntimeError("SIMULATED_AFTER_COMMAND_EVENT")
        return original_create(*args, **kwargs)

    def count_canonical_validation(*args: Any, **kwargs: Any) -> None:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls > 1:
            raise AssertionError("idempotent recovery revalidated mutable ledgers")
        original_validate(*args, **kwargs)

    monkeypatch.setattr(
        remote_agent_service,
        "create_or_fetch_workflow_design_draft",
        interrupt_first_draft,
    )
    monkeypatch.setattr(
        remote_agent_service,
        "validate_fastq_qc_materialized_plan",
        count_canonical_validation,
    )

    with pytest.raises(RuntimeError, match="SIMULATED_AFTER_COMMAND_EVENT"):
        asyncio.run(plan_agent_session_api(created["sessionId"], command))
    interrupted = _data(
        client.get(f"/api/v1/agent-sessions/{created['sessionId']}", headers=headers)
    )
    interrupted_events = _data(
        client.get(
            f"/api/v1/agent-sessions/{created['sessionId']}/events",
            headers=headers,
        )
    )["items"]
    command_events = [item for item in interrupted_events if item["eventType"] == "agent.plan_requested"]
    assert interrupted["status"] == "planning"
    assert interrupted["planGeneration"] == 1
    assert len(command_events) == 1
    assert command_events[0]["payload"]["proposalIntent"]["planner"]["adapterId"] == (
        "h2ometa.fastq-qc.v1"
    )

    recovered_response = asyncio.run(plan_agent_session_api(created["sessionId"], command))

    recovered = recovered_response["data"]
    plans = _data(
        client.get(
            f"/api/v1/agent-sessions/{created['sessionId']}/plans",
            headers=headers,
        )
    )["items"]
    final_events = _data(
        client.get(
            f"/api/v1/agent-sessions/{created['sessionId']}/events",
            headers=headers,
        )
    )["items"]
    assert recovered["session"]["status"] == "awaiting_approval"
    assert recovered["session"]["planGeneration"] == 1
    assert validation_calls == 1
    assert sum(action == "upload" for action, _ in runtime.calls) == 1
    assert sum(action == "tools" for action, _ in runtime.calls) == 1
    assert all(server_id == "srv-recovery" for _, server_id in runtime.calls)
    assert len(plans) == 1
    assert sum(item["eventType"] == "agent.plan_requested" for item in final_events) == 1
    assert list_runs(cfg) == []


def test_fastq_qc_goal_cannot_bypass_validation_by_renaming_the_adapter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-adapter-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(
        session=created,
        capability_graph=graph,
    ).runtime_payload()
    proposal["planner"]["adapterId"] = "fixture.fastq-qc.v1"

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-adapter-bypass",
            "actor": "user-1",
            "idempotencyKey": "plan-adapter-bypass",
            "expectedStateVersion": created["stateVersion"],
            "proposal": proposal,
        },
    )

    assert response.status_code == 422
    assert "WORKFLOW_FASTQ_QC_ADAPTER_CONTEXT_MISMATCH" in response.text
    unchanged = _data(
        client.get(f"/api/v1/agent-sessions/{created['sessionId']}", headers=headers)
    )
    assert unchanged["status"] == "created"
    assert unchanged["stateVersion"] == created["stateVersion"]
    assert unchanged["planGeneration"] == 0


def test_fastq_qc_remote_plan_rejects_manifest_not_matching_upload_bytes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QQ==",
        mime_type="text/plain",
    )
    forged = dict(upload)
    forged["sha256"] = "0" * 64
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(forged, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(session=created, capability_graph=graph)

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-forged-input",
            "actor": "user-1",
            "idempotencyKey": "plan-forged-input",
            "expectedStateVersion": 1,
            "proposal": proposal.runtime_payload(),
        },
    )

    assert response.status_code == 422
    assert "INPUT_FASTQ_QC_UPLOAD_MANIFEST_MISMATCH" in response.text
    assert list_runs(cfg) == []


@pytest.mark.parametrize(
    ("tamper_path", "tampered_value"),
    [
        (("outputs", 0, "from"), {"nodeId": "multiqc", "port": "report"}),
        (("nodes", 0, "runtime", "threads"), 4),
        (("nodes", 0, "outputs", "html", "expose"), False),
        (("nodes", 0, "outputs", "html", "metadata", "mimeType"), "text/plain"),
        (("resources", "metadata", "singleSampleOnly"), False),
    ],
)
def test_fastq_qc_remote_plan_rejects_noncanonical_draft_mutations(
    monkeypatch,
    tmp_path: Path,
    tamper_path: tuple[str | int, ...],
    tampered_value: Any,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-tamper-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(
        session=created,
        capability_graph=graph,
    ).runtime_payload()
    _set_nested(proposal["draft"], tamper_path, tampered_value)

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-tampered-output",
            "actor": "user-1",
            "idempotencyKey": "plan-tampered-output",
            "expectedStateVersion": 1,
            "proposal": proposal,
        },
    )

    assert response.status_code == 422
    assert "WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL" in response.text
    unchanged = _data(
        client.get(f"/api/v1/agent-sessions/{created['sessionId']}", headers=headers)
    )
    assert unchanged["status"] == "created"
    assert unchanged["stateVersion"] == created["stateVersion"]
    assert list_runs(cfg) == []


def test_fastq_qc_remote_plan_rejects_drifted_profile_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-lock-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    drifted_fastqc = _tool_manifest("fastqc")
    drifted_fastqc["ruleSpecDraft"]["lock"]["profileVersion"] = 1
    fastqc = _ready_profile_tool(cfg, "fastqc", manifest=drifted_fastqc)
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(session=created, capability_graph=graph)

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-drifted-profile",
            "actor": "user-1",
            "idempotencyKey": "plan-drifted-profile",
            "expectedStateVersion": 1,
            "proposal": proposal.runtime_payload(),
        },
    )

    assert response.status_code == 422
    assert "WORKFLOW_FASTQ_QC_TOOL_PROFILE_LOCK_INVALID" in response.text
    assert list_runs(cfg) == []


def test_fastq_qc_remote_plan_rejects_extra_tool_environment_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    cfg.work_dir = str(tmp_path.parent / f"agent-qc-env-lock-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    drifted_fastqc = _tool_manifest("fastqc")
    drifted_fastqc["environmentSpec"] = {
        "adapter": "conda",
        "channels": ["conda-forge", "bioconda"],
        "dependencies": ["bioconda::fastqc=0.11.9"],
    }
    fastqc = _ready_profile_tool(cfg, "fastqc", manifest=drifted_fastqc)
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNtb2tlCkFDR1QKKwpGRkZGCg==",
        mime_type="text/plain",
    )
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created = _data(
        client.post(
            "/api/v1/agent-sessions",
            headers=headers,
            json=_create_request(upload, [fastqc["toolRevisionId"], multiqc["toolRevisionId"]]),
        )
    )
    graph = CapabilityGraphService().snapshot(
        registered_tools=_capability_tools(cfg),
        catalog={"items": [], "total": 0},
        agent_selectable_only=True,
    )
    proposal = build_fastq_qc_plan_proposal(session=created, capability_graph=graph)

    response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-drifted-environment",
            "actor": "user-1",
            "idempotencyKey": "plan-drifted-environment",
            "expectedStateVersion": 1,
            "proposal": proposal.runtime_payload(),
        },
    )

    assert response.status_code == 422
    assert "WORKFLOW_FASTQ_QC_TOOL_ENVIRONMENT_LOCK_INVALID" in response.text
    assert list_runs(cfg) == []


def _data(response: Any) -> dict[str, Any]:
    return json.loads(response.content)["data"]


def _set_nested(value: Any, path: tuple[str | int, ...], replacement: Any) -> None:
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement


def _create_request(upload: dict[str, Any], revisions: list[str]) -> dict[str, Any]:
    return {
        "contractVersion": "agent-session.v1",
        "projectId": "project-fastq-qc",
        "creationRequestId": f"create-{upload['uploadId']}",
        "createdBy": "user-1",
        "goal": {
            "summary": "Inspect this FASTQ and produce a reviewable QC report.",
            "successCriteria": ["Produce FastQC evidence and a MultiQC HTML report."],
            "context": {
                "schemaVersion": "agent-fastq-qc-goal.v1",
                "analysis": "fastq-qc",
                "inputs": [
                    {
                        key: upload[key]
                        for key in ("uploadId", "filename", "sha256", "sizeBytes", "mimeType")
                    }
                ],
                "reportFormat": "multiqc-html",
            },
        },
        "constraints": {
            "allowedToolRevisionIds": revisions,
            "forbiddenActions": ["arbitrary_shell", "undeclared_network"],
            "requirements": {},
        },
        "budget": {
            "maxModelTurns": 1,
            "maxToolCalls": 2,
            "maxReplans": 2,
            "maxRetries": 1,
            "maxWallClockSeconds": 600,
        },
    }


def _tool_manifest(profile_id: str) -> dict[str, Any]:
    profile = next(item for item in all_tool_profiles() if item.profile_id == profile_id)
    payload = deepcopy(profile_prepare_payload(profile))
    payload["summary"] = f"Agent FASTQ QC fixture for {profile_id}"
    return payload


def _ready_profile_tool(
    cfg: Any,
    profile_id: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool = upsert_ready_tool(cfg, manifest or _tool_manifest(profile_id))
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO tool_validation_results (
                validation_result_id, tool_id, tool_revision_id, runtime_profile_id,
                job_id, stage, status, evidence_id, logs_json, artifacts_json,
                failure_code, duration_ms, created_at
            ) VALUES (?, ?, ?, NULL, NULL, 'output_validation', 'passed', ?, '[]', '[]', NULL, 1, ?)
            """,
            (
                f"toolval_agent_qc_{profile_id}",
                str(tool["id"]),
                str(tool["toolRevisionId"]),
                f"evid_agent_qc_{profile_id}",
                "2026-07-15T00:00:00Z",
            ),
        )
        connection.commit()
    upsert_tool_index(cfg, tool)
    return tool


def _capability_tools(cfg: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in list_tools(cfg):
        tool = deepcopy(item)
        profile_id = str(tool["name"])
        tool["validationSummary"] = {
            "latestResultId": f"toolval_{profile_id}",
            "latestStatus": "passed",
            "evidenceId": f"evid_{profile_id}",
            "updatedAt": "2026-07-15T00:00:00Z",
        }
        tools.append(tool)
    return tools
