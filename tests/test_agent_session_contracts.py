from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from core.contracts.agent_session import (
    AgentApprovalRequest,
    AgentPlanRequest,
    AgentPrincipalContext,
    AgentSessionCreateRequest,
    AgentSessionEvent,
    AgentSessionRecord,
)
from tests.helpers.workflow_design_drafts import workflow_design_draft


def _budget() -> dict[str, int]:
    return {
        "maxModelTurns": 12,
        "maxToolCalls": 30,
        "maxReplans": 3,
        "maxRetries": 2,
        "maxWallClockSeconds": 3_600,
    }


def _create_request() -> dict[str, Any]:
    return {
        "contractVersion": "agent-session.v1",
        "projectId": "proj_design",
        "creationRequestId": "create_agent_1",
        "createdBy": "user_1",
        "goal": {
            "summary": "Inspect paired FASTQ quality and produce a shareable report.",
            "successCriteria": ["Produce a validated MultiQC report."],
            "context": {"inputManifest": {"sampleCount": 4}},
        },
        "constraints": {
            "allowedToolRevisionIds": ["tr_fastqc", "tr_multiqc"],
            "forbiddenActions": ["arbitrary_shell", "undeclared_network"],
            "requirements": {"runner": {"networkAccess": "declared-only"}},
        },
        "budget": _budget(),
    }


def _plan_request() -> dict[str, Any]:
    return {
        "requestId": "req_plan_1",
        "actor": "user_1",
        "idempotencyKey": "idem_plan_1",
        "expectedStateVersion": 1,
        "proposal": {
            "draft": workflow_design_draft(),
            "planner": {
                "adapterId": "structured-draft-adapter",
                "adapterVersion": "1.0.0",
                "modelRef": "provider-neutral:model-family",
            },
        },
    }


def _record() -> dict[str, Any]:
    created = _create_request()
    return {
        "contractVersion": created["contractVersion"],
        "sessionId": "ags_1",
        "projectId": created["projectId"],
        "goal": created["goal"],
        "constraints": created["constraints"],
        "budget": created["budget"],
        "status": "awaiting_approval",
        "stateVersion": 3,
        "planGeneration": 1,
        "activeDraftId": "wfd_1",
        "activeDraftRevision": 1,
        "activePlanHash": "sha256:plan-1",
        "workflowRevisionId": None,
        "creationRequestId": created["creationRequestId"],
        "createdBy": created["createdBy"],
        "createdAt": "2026-07-15T10:00:00Z",
        "updatedAt": "2026-07-15T10:01:00Z",
        "cancelledAt": None,
    }


def _event() -> dict[str, Any]:
    return {
        "schemaVersion": "agent-event.v1",
        "eventId": "age_1",
        "sessionId": "ags_1",
        "sequence": 3,
        "eventType": "agent.plan_validated",
        "fromStatus": "planning",
        "toStatus": "awaiting_approval",
        "stateVersion": 3,
        "planGeneration": 1,
        "requestId": "req_plan_1",
        "correlationId": "corr_1",
        "idempotencyKey": "idem_plan_1",
        "actor": "user_1",
        "payload": {"validation": {"valid": True, "issueCount": 0}},
        "payloadHash": "sha256:payload",
        "eventHash": "sha256:event",
        "prevEventHash": "sha256:previous",
        "createdAt": "2026-07-15T10:01:00Z",
    }


def test_create_contract_is_strict_and_serializes_camel_case_runtime_payload() -> None:
    request = AgentSessionCreateRequest.model_validate(_create_request())

    payload = request.runtime_payload()
    assert payload["contractVersion"] == "agent-session.v1"
    assert payload["creationRequestId"] == "create_agent_1"
    assert payload["budget"] == _budget()
    assert "creation_request_id" not in payload

    invalid = _create_request()
    invalid["budget"]["maxModelTurns"] = "12"
    with pytest.raises(ValidationError) as exc_info:
        AgentSessionCreateRequest.model_validate(invalid)
    assert exc_info.value.errors()[0]["type"] == "int_type"

    extra = _create_request()
    extra["serverId"] = "server-local-routing-must-not-be-persisted"
    with pytest.raises(ValidationError) as extra_exc:
        AgentSessionCreateRequest.model_validate(extra)
    assert extra_exc.value.errors()[0]["type"] == "extra_forbidden"


def test_authenticated_principal_context_is_minimal_and_strict() -> None:
    context = AgentPrincipalContext.model_validate(
        {
            "schemaVersion": "agent-principal-context.v1",
            "actor": "runner-user",
        }
    )

    assert context.runtime_payload() == {
        "schemaVersion": "agent-principal-context.v1",
        "actor": "runner-user",
    }
    with pytest.raises(ValidationError) as extra_exc:
        AgentPrincipalContext.model_validate(
            context.runtime_payload() | {"roles": ["workflow-operator"]}
        )
    assert extra_exc.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("target", "secret_key"),
    [
        ("goal", "apiKey"),
        ("goal", "db_password"),
        ("constraints", "accessToken"),
        ("constraints", "credentialValue"),
        ("constraints", "private-key"),
        ("constraints", "chainOfThought"),
        ("constraints", "rawModelOutput"),
    ],
)
def test_goal_and_constraints_reject_nested_secret_like_keys(target: str, secret_key: str) -> None:
    payload = _create_request()
    if target == "goal":
        payload["goal"]["context"] = {"nested": [{secret_key: "must-not-enter-agent-state"}]}
    else:
        payload["constraints"]["requirements"] = {
            "nested": [{secret_key: "must-not-enter-agent-state"}]
        }

    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        AgentSessionCreateRequest.model_validate(payload)


def test_opaque_credential_references_are_allowed_but_secret_values_are_not() -> None:
    payload = _create_request()
    payload["constraints"]["requirements"] = {
        "credentialReference": "cred_fastq_readonly"
    }
    assert AgentSessionCreateRequest.model_validate(payload).constraints.requirements == {
        "credentialReference": "cred_fastq_readonly"
    }

    proposal = _plan_request()
    proposal["proposal"]["draft"]["metadata"]["description"] = (
        "sk-abcdefghijklmnopqrstuvwxyz"
    )
    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN"):
        AgentPlanRequest.model_validate(proposal)


def test_plan_proposal_rejects_model_internal_trace_fields() -> None:
    payload = _plan_request()
    payload["proposal"]["draft"]["nodes"][0]["provenance"] = {
        "chainOfThought": "private model reasoning"
    }

    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        AgentPlanRequest.model_validate(payload)


def test_plan_proposal_embeds_strict_workflow_design_and_provider_neutral_planner_audit() -> None:
    request = AgentPlanRequest.model_validate(_plan_request())
    payload = request.runtime_payload()

    assert payload["proposal"]["draft"]["contractVersion"] == "workflow-design-draft-v1"
    assert payload["proposal"]["draft"]["outputs"][0]["from"] == {
        "nodeId": "qc",
        "port": "report",
    }
    assert payload["proposal"]["planner"] == {
        "adapterId": "structured-draft-adapter",
        "adapterVersion": "1.0.0",
        "modelRef": "provider-neutral:model-family",
    }

    provider_specific = _plan_request()
    provider_specific["proposal"]["planner"]["provider"] = "vendor-a"
    with pytest.raises(ValidationError) as provider_exc:
        AgentPlanRequest.model_validate(provider_specific)
    assert provider_exc.value.errors()[0]["type"] == "extra_forbidden"

    executable_bypass = _plan_request()
    executable_bypass["proposal"]["draft"]["nodes"][0]["command"] = "arbitrary shell"
    with pytest.raises(ValidationError) as draft_exc:
        AgentPlanRequest.model_validate(executable_bypass)
    assert draft_exc.value.errors()[0]["type"] == "extra_forbidden"


def test_approval_contract_binds_state_version_and_plan_hash() -> None:
    request = AgentApprovalRequest.model_validate(
        {
            "requestId": "req_approve_1",
            "actor": "user_1",
            "idempotencyKey": "idem_approve_1",
            "expectedStateVersion": 3,
            "decision": "approve",
            "expectedPlanHash": "sha256:plan-1",
        }
    )
    assert request.runtime_payload() == {
        "requestId": "req_approve_1",
        "actor": "user_1",
        "idempotencyKey": "idem_approve_1",
        "expectedStateVersion": 3,
        "decision": "approve",
        "expectedPlanHash": "sha256:plan-1",
    }

    missing_hash = request.runtime_payload()
    missing_hash.pop("expectedPlanHash")
    with pytest.raises(ValidationError) as hash_exc:
        AgentApprovalRequest.model_validate(missing_hash)
    assert hash_exc.value.errors()[0]["type"] == "missing"

    change_without_reason = request.runtime_payload()
    change_without_reason["decision"] = "request_changes"
    with pytest.raises(ValidationError, match="AGENT_SESSION_CHANGE_REASON_REQUIRED"):
        AgentApprovalRequest.model_validate(change_without_reason)


def test_public_record_and_event_exclude_local_routing_and_preserve_audit_refs() -> None:
    record = AgentSessionRecord.model_validate(_record())
    event = AgentSessionEvent.model_validate(_event())

    record_payload = record.runtime_payload()
    assert record_payload["activePlanHash"] == "sha256:plan-1"
    assert record_payload["planner"] == {}
    assert record_payload["lastErrorCode"] == ""
    event_payload = event.runtime_payload()
    assert event_payload["schemaVersion"] == "agent-event.v1"
    assert event_payload["sequence"] == 3
    assert event_payload["toStatus"] == "awaiting_approval"
    assert event_payload["stateVersion"] == 3
    assert event_payload["planGeneration"] == 1
    assert event_payload["payloadHash"] == "sha256:payload"
    assert event_payload["eventHash"] == "sha256:event"
    assert event_payload["prevEventHash"] == "sha256:previous"

    invalid_record = _record()
    invalid_record["serverId"] = "local-only"
    with pytest.raises(ValidationError) as record_exc:
        AgentSessionRecord.model_validate(invalid_record)
    assert record_exc.value.errors()[0]["type"] == "extra_forbidden"

    invalid_event = _event()
    invalid_event["payload"] = {"result": {"clientSecret": "must-not-be-public"}}
    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        AgentSessionEvent.model_validate(invalid_event)


def test_public_read_models_enforce_reference_and_terminal_invariants() -> None:
    missing_draft = _record()
    missing_draft["activeDraftId"] = None
    with pytest.raises(ValidationError, match="AGENT_SESSION_ACTIVE_DRAFT_ID_REQUIRED"):
        AgentSessionRecord.model_validate(missing_draft)

    cancelled = _record()
    cancelled["status"] = "cancelled"
    with pytest.raises(ValidationError, match="AGENT_SESSION_CANCELLED_AT_REQUIRED"):
        AgentSessionRecord.model_validate(cancelled)

    cancelled["cancelledAt"] = "2026-07-15T10:02:00Z"
    assert AgentSessionRecord.model_validate(cancelled).status == "cancelled"
