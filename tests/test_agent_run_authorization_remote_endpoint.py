from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

import apps.remote_runner.agent_run_authorization_remote_endpoint as endpoint
from apps.remote_runner.agent_run_authorization_authority import (
    prepare_agent_run_authorization_authority,
)
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage import list_runs
from core.contracts.agent_remote_endpoints import AGENT_RUN_AUTHORIZE
from core.contracts.agent_run_authorization import AgentRunAuthorizationResult
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    remote_endpoint_success_status,
)
from core.governance_policy import HIGH_RISK_API_POLICIES


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


_PATH = "/api/v1/agent-sessions/{session_id}/run-authorization"
_HEADERS = {"Authorization": "Bearer workflow-design-token"}


def _request(preview: dict[str, Any], *, suffix: str = "http") -> dict[str, Any]:
    return {
        "expectedStateVersion": preview["stateVersion"],
        "expectedPlanRevisionId": preview["planRevisionId"],
        "expectedPlanGeneration": preview["planGeneration"],
        "expectedPlanHash": preview["planHash"],
        "expectedWorkflowRevisionId": preview["workflowRevisionId"],
        "expectedPreviewHash": preview["previewHash"],
        "expectedInputManifestDigest": preview["inputManifestDigest"],
        "expectedRunSpecHash": preview["runSpecHash"],
        "expectedExecutionPolicyHash": preview["executionPolicyHash"],
        "expectedRuntimeProofHash": preview["runtimeProofHash"],
        "confirmation": "authorize-workflow-run",
        "requestId": f"authorize-agent-run-{suffix}",
        "idempotencyKey": f"authorize-agent-run-{suffix}",
    }


def _preview(candidate_case: dict[str, Any]) -> dict[str, Any]:
    return prepare_agent_run_authorization_authority(
        candidate_case["cfg"],
        candidate_case["session"]["sessionId"],
        actor="user-1",
    ).preview


def _post(
    client: TestClient,
    session_id: str,
    payload: dict[str, Any],
):
    return client.post(
        _PATH.format(session_id=session_id),
        headers=_HEADERS,
        json=payload,
    )


def _authorization_audits(cfg: Any) -> list[dict[str, Any]]:
    return list_governance_audit_events(
        cfg,
        action=AGENT_RUN_AUTHORIZE,
        limit=20,
    )["items"]


def test_run_authorization_remote_contract_policy_and_openapi_are_exact() -> None:
    assert endpoint.AGENT_RUN_AUTHORIZATION_ACTION == AGENT_RUN_AUTHORIZE
    spec = REMOTE_ENDPOINTS[AGENT_RUN_AUTHORIZE]
    assert spec.method == "POST"
    assert spec.path_template == _PATH
    assert spec.operation_id == "authorizeAgentWorkflowRun"
    assert spec.governance_action == AGENT_RUN_AUTHORIZE
    assert spec.request_schema == "agent-run-authorization-request.v1"
    assert spec.response_schema == "agent-run-authorization-result.v1"
    assert spec.cache_scope == "agent-run-authorization-command"
    assert spec.invalidates == (
        "agent-run-authorization-preview-read-model",
        "agent-session-read-model",
        "run-read-model",
    )
    assert spec.accepted_statuses == (202,)
    assert remote_endpoint_success_status(AGENT_RUN_AUTHORIZE) == 202

    matches = [
        policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
        and policy.method == "POST"
        and policy.route == _PATH
    ]
    assert len(matches) == 1
    policy = matches[0]
    assert policy.action == AGENT_RUN_AUTHORIZE
    assert policy.subject_kind == "agent_run_authorization"
    assert policy.audit_status == "implemented"
    assert policy.future_roles == ("workflow-operator",)

    operation = app.openapi()["paths"][_PATH]["post"]
    assert operation["operationId"] == "authorizeAgentWorkflowRun"
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/AgentRunAuthorizationRequest")
    assert operation["responses"]["202"]["description"] == "Successful Response"
    response_schema = operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ]
    assert response_schema["$ref"].endswith("/AgentRunAuthorizationHttpResponse")
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["AgentRunAuthorizationHttpResponse"] == {
        "additionalProperties": False,
        "properties": {
            "data": {
                "$ref": "#/components/schemas/AgentRunAuthorizationResult",
            }
        },
        "type": "object",
        "required": ["data"],
        "title": "AgentRunAuthorizationHttpResponse",
    }


def test_remote_authorization_uses_authenticated_principal_and_exact_fresh_replay(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    payload = _request(_preview(candidate_case))
    delegated: list[tuple[str, str]] = []
    original = endpoint.authorize_agent_workflow_run

    def capturing_authorize(
        service_cfg: Any,
        delegated_session_id: str,
        request: Any,
        *,
        actor: str,
    ) -> dict[str, Any]:
        assert service_cfg is cfg
        delegated.append((delegated_session_id, actor))
        return original(
            service_cfg,
            delegated_session_id,
            request,
            actor=actor,
        )

    monkeypatch.setattr(endpoint, "authorize_agent_workflow_run", capturing_authorize)
    client = TestClient(app, raise_server_exceptions=False)

    fresh_response = _post(client, session_id, payload)
    audits_after_fresh = _authorization_audits(cfg)
    assert len(audits_after_fresh) == 1
    replay_response = _post(client, session_id, payload)

    assert fresh_response.status_code == 202, fresh_response.text
    assert replay_response.status_code == 202, replay_response.text
    assert set(fresh_response.json()) == {"data"}
    fresh = fresh_response.json()["data"]
    replay = replay_response.json()["data"]
    assert AgentRunAuthorizationResult.model_validate(fresh).runtime_payload() == fresh
    assert (
        AgentRunAuthorizationResult.model_validate(replay).runtime_payload() == replay
    )
    assert fresh["contractVersion"] == "agent-run-authorization-result.v1"
    assert fresh["idempotencyReplay"] is False
    assert replay["idempotencyReplay"] is True
    assert replay["authorization"] == fresh["authorization"]
    assert replay["run"] == fresh["run"]
    assert delegated == [(session_id, "user-1"), (session_id, "user-1")]
    assert len(list_runs(cfg)) == 1
    assert audits_after_fresh[0]["actor"] == "user-1"
    assert audits_after_fresh[0]["subjectKind"] == "agent_run_authorization"
    assert (
        audits_after_fresh[0]["subjectId"] == fresh["authorization"]["authorizationId"]
    )

    assert _authorization_audits(cfg) == audits_after_fresh

    for forged in (
        {**payload, "actor": "forged-user"},
        {**payload, "sessionId": "ags_forged"},
        {**payload, "expectedStateVersion": str(payload["expectedStateVersion"])},
    ):
        rejected = _post(client, session_id, forged)
        assert rejected.status_code == 422, rejected.text
    assert delegated == [(session_id, "user-1"), (session_id, "user-1")]
    assert _authorization_audits(cfg) == audits_after_fresh
    assert len(list_runs(cfg)) == 1


def test_remote_authorization_maps_stale_conflict_and_origin_integrity(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    payload = _request(_preview(candidate_case), suffix="integrity")
    client = TestClient(app, raise_server_exceptions=False)

    stale = deepcopy(payload)
    stale["expectedStateVersion"] += 1
    stale_response = _post(client, session_id, stale)
    assert stale_response.status_code == 409
    assert stale_response.json() == {
        "detail": "AGENT_RUN_AUTHORIZATION_PREVIEW_MISMATCH"
    }
    assert list_runs(cfg) == []
    stale_audits = _authorization_audits(cfg)
    assert len(stale_audits) == 1
    assert stale_audits[0]["decision"] == "error"
    assert stale_audits[0]["reasonCode"] == "AGENT_RUN_AUTHORIZATION_CONFLICT"
    assert stale_audits[0]["subjectId"] == session_id
    assert stale_audits[0]["details"] == {
        "sessionId": session_id,
        "requestId": payload["requestId"],
        "failureStage": "run-authorization-domain",
        "errorType": "WorkflowDesignRevisionConflictError",
    }

    fresh_response = _post(client, session_id, payload)
    assert fresh_response.status_code == 202, fresh_response.text
    fresh = fresh_response.json()["data"]
    audits_after_fresh = _authorization_audits(cfg)
    assert len(audits_after_fresh) == 2
    assert audits_after_fresh[:1] == stale_audits
    assert audits_after_fresh[1]["decision"] == "allow"

    conflict = deepcopy(payload)
    conflict["requestId"] = "authorize-agent-run-integrity-conflict"
    conflict_response = _post(client, session_id, conflict)
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "detail": "AGENT_RUN_AUTHORIZATION_IDEMPOTENCY_CONFLICT"
    }
    audits_after_conflict = _authorization_audits(cfg)
    assert len(audits_after_conflict) == 3
    assert audits_after_conflict[-1]["decision"] == "error"
    assert audits_after_conflict[-1]["reasonCode"] == "AGENT_RUN_AUTHORIZATION_CONFLICT"
    assert audits_after_conflict[-1]["details"]["errorType"] == (
        "AgentRunAuthorizationStorageConflictError"
    )

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE run_commands SET actor = 'tampered' WHERE run_id = ?",
            (fresh["run"]["runId"],),
        )
        connection.commit()

    origin_response = _post(client, session_id, payload)
    assert origin_response.status_code == 500
    assert origin_response.text == "Internal Server Error"
    assert len(list_runs(cfg)) == 1
    final_audits = _authorization_audits(cfg)
    assert len(final_audits) == 4
    assert final_audits[-1]["decision"] == "error"
    assert final_audits[-1]["reasonCode"] == "AGENT_RUN_AUTHORIZATION_FAILED"
    assert final_audits[-1]["details"]["errorType"] == (
        "AgentRunAuthorizationOriginIntegrityError"
    )


def test_authentication_role_denial_and_owner_denial_are_not_double_audited(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    payload = _request(_preview(candidate_case), suffix="denial")
    client = TestClient(app, raise_server_exceptions=False)

    unauthenticated = client.post(
        _PATH.format(session_id=session_id),
        headers={"Authorization": "Bearer wrong-token"},
        json=payload,
    )
    assert unauthenticated.status_code == 401
    assert _authorization_audits(cfg) == []

    original_roles = cfg.api_token_roles
    original_failure_audit = endpoint.record_governance_audit_event

    def unexpected_wrapper_audit(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        pytest.fail("role authorization denial must not reach the domain audit catch")

    cfg.api_token_roles = ("auditor",)
    monkeypatch.setattr(
        endpoint,
        "record_governance_audit_event",
        unexpected_wrapper_audit,
    )
    wrong_role = _post(client, session_id, payload)
    assert wrong_role.status_code == 403
    role_audits = _authorization_audits(cfg)
    assert len(role_audits) == 1
    assert role_audits[0]["decision"] == "deny"
    assert role_audits[0]["reasonCode"] == "REMOTE_RUNNER_ROLE_REQUIRED"

    cfg.api_token_roles = original_roles
    cfg.api_token_actor = "other-user"
    monkeypatch.setattr(
        endpoint,
        "record_governance_audit_event",
        original_failure_audit,
    )
    owner_denied = _post(client, session_id, payload)
    assert owner_denied.status_code == 403
    audits = _authorization_audits(cfg)
    assert len(audits) == 2
    owner_audit = audits[-1]
    assert owner_audit["decision"] == "deny"
    assert owner_audit["reasonCode"] == "AGENT_RUN_AUTHORIZATION_OWNER_DENIED"
    assert owner_audit["actor"] == "other-user"
    assert owner_audit["subjectId"] == session_id
    assert owner_audit["details"] == {
        "sessionId": session_id,
        "requestId": payload["requestId"],
        "failureStage": "run-authorization-domain",
        "errorType": "RemoteRunnerAuthorizationError",
    }
    assert list_runs(cfg) == []


def test_invalid_internal_result_fails_as_500_and_records_sanitized_error(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    payload = _request(_preview(candidate_case), suffix="invalid-result")
    monkeypatch.setattr(
        endpoint,
        "authorize_agent_workflow_run",
        lambda *_args, **_kwargs: {"broken": True},
    )

    response = _post(
        TestClient(app, raise_server_exceptions=False),
        session_id,
        payload,
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert list_runs(cfg) == []
    audits = _authorization_audits(cfg)
    assert len(audits) == 1
    assert audits[0]["decision"] == "error"
    assert audits[0]["reasonCode"] == "AGENT_RUN_AUTHORIZATION_FAILED"
    assert audits[0]["details"] == {
        "sessionId": session_id,
        "requestId": payload["requestId"],
        "failureStage": "run-authorization-domain",
        "errorType": "RuntimeError",
    }
