"""Strict immutable authorization receipt and execution-binding contracts."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash, exact_hash_payload
from .agent_session import AgentSessionModel, assert_agent_session_json_safe


AGENT_RUN_AUTHORIZATION_CONTRACT_VERSION = "agent-run-authorization.v1"
AGENT_RUN_AUTHORIZATION_REQUEST_SCHEMA = "agent-run-authorization-request.v1"
AGENT_RUN_AUTHORIZATION_READ_CONTRACT_VERSION = "agent-run-authorization-read.v1"
AGENT_RUN_AUTHORIZATION_RESULT_CONTRACT_VERSION = "agent-run-authorization-result.v1"
AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_DOMAIN = (
    "agent-run-authorization-run-idempotency.v1"
)

_COMMAND_HASH_DOMAIN = AGENT_RUN_AUTHORIZATION_REQUEST_SCHEMA
_RECEIPT_HASH_DOMAIN = AGENT_RUN_AUTHORIZATION_CONTRACT_VERSION
_HEX_SHA256 = r"^[0-9a-f]{64}$"
_DIGEST_SHA256 = r"^sha256:[0-9a-f]{64}$"
_RECEIPT_HASH_FIELDS = (
    "authorizationId",
    "contractVersion",
    "sessionId",
    "previewHash",
    "planRevisionId",
    "planGeneration",
    "planHash",
    "workflowRevisionId",
    "expectedStateVersion",
    "inputManifestDigest",
    "runSpecHash",
    "executionPolicyId",
    "executionPolicyHash",
    "runtimeLockHash",
    "runtimeProofHash",
    "effectBudgetHash",
    "runId",
    "scope",
    "confirmation",
    "actor",
    "requestId",
    "idempotencyKey",
    "commandHash",
    "createdAt",
)


class AgentRunAuthorizationRequest(AgentSessionModel):
    expectedStateVersion: int = Field(ge=1)
    expectedPlanRevisionId: str = Field(min_length=1, max_length=500)
    expectedPlanGeneration: int = Field(ge=1)
    expectedPlanHash: str = Field(pattern=_HEX_SHA256)
    expectedWorkflowRevisionId: str = Field(min_length=1, max_length=500)
    expectedPreviewHash: str = Field(pattern=_HEX_SHA256)
    expectedInputManifestDigest: str = Field(pattern=_DIGEST_SHA256)
    expectedRunSpecHash: str = Field(pattern=_HEX_SHA256)
    expectedExecutionPolicyHash: str = Field(pattern=_HEX_SHA256)
    expectedRuntimeProofHash: str = Field(pattern=_HEX_SHA256)
    confirmation: Literal["authorize-workflow-run"]
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)

    @field_validator(
        "expectedPlanRevisionId",
        "expectedWorkflowRevisionId",
        "requestId",
        "idempotencyKey",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_REQUEST_TEXT_REQUIRED")

    @model_validator(mode="after")
    def reject_secret_like_values(self) -> "AgentRunAuthorizationRequest":
        assert_agent_session_json_safe(
            self.runtime_payload(), path="runAuthorization.request"
        )
        return self


class AgentRunAuthorizationReceipt(AgentSessionModel):
    authorizationId: str = Field(min_length=1, max_length=500)
    contractVersion: Literal["agent-run-authorization.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    previewHash: str = Field(pattern=_HEX_SHA256)
    planRevisionId: str = Field(min_length=1, max_length=500)
    planGeneration: int = Field(ge=1)
    planHash: str = Field(pattern=_HEX_SHA256)
    workflowRevisionId: str = Field(min_length=1, max_length=500)
    expectedStateVersion: int = Field(ge=1)
    inputManifestDigest: str = Field(pattern=_DIGEST_SHA256)
    runSpecHash: str = Field(pattern=_HEX_SHA256)
    executionPolicyId: str = Field(min_length=1, max_length=500)
    executionPolicyHash: str = Field(pattern=_HEX_SHA256)
    runtimeLockHash: str = Field(pattern=_HEX_SHA256)
    runtimeProofHash: str = Field(pattern=_HEX_SHA256)
    effectBudgetHash: str = Field(pattern=_HEX_SHA256)
    runId: str = Field(min_length=1, max_length=500)
    scope: Literal["submit_workflow_run"]
    confirmation: Literal["authorize-workflow-run"]
    actor: str = Field(min_length=1, max_length=500)
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)
    commandHash: str = Field(pattern=_HEX_SHA256)
    receiptHash: str = Field(pattern=_HEX_SHA256)
    createdAt: str = Field(min_length=1, max_length=100)

    @field_validator(
        "authorizationId",
        "sessionId",
        "planRevisionId",
        "workflowRevisionId",
        "executionPolicyId",
        "runId",
        "actor",
        "requestId",
        "idempotencyKey",
        "createdAt",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_RECEIPT_TEXT_REQUIRED")

    @model_validator(mode="after")
    def validate_receipt(self) -> "AgentRunAuthorizationReceipt":
        payload = self.runtime_payload()
        assert_agent_session_json_safe(payload, path="runAuthorization.receipt")
        expected = agent_run_authorization_receipt_hash(payload)
        if not hmac.compare_digest(expected, self.receiptHash):
            raise ValueError("AGENT_RUN_AUTHORIZATION_RECEIPT_HASH_MISMATCH")
        return self


class AgentRunAuthorizationRead(AgentSessionModel):
    contractVersion: Literal["agent-run-authorization-read.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    state: Literal["absent", "present"]
    receipt: AgentRunAuthorizationReceipt | None = None

    @field_validator("sessionId")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_READ_SESSION_ID_REQUIRED")

    @model_validator(mode="after")
    def validate_presence_and_identity(self) -> "AgentRunAuthorizationRead":
        if self.state == "absent" and self.receipt is not None:
            raise ValueError("AGENT_RUN_AUTHORIZATION_READ_ABSENT_HAS_RECEIPT")
        if self.state == "present" and self.receipt is None:
            raise ValueError("AGENT_RUN_AUTHORIZATION_READ_PRESENT_REQUIRES_RECEIPT")
        if self.receipt is not None and self.receipt.sessionId != self.sessionId:
            raise ValueError("AGENT_RUN_AUTHORIZATION_READ_SESSION_ID_MISMATCH")
        return self


class AgentRunAuthorizationRunSummary(AgentSessionModel):
    """Exact public projection of the current authorized run lifecycle."""

    runId: str = Field(min_length=1, max_length=500)
    requestId: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=100)
    stage: str = Field(min_length=1, max_length=100)
    stateVersion: int = Field(ge=1)
    message: str = Field(max_length=10_000)
    submittedAt: str = Field(min_length=1, max_length=100)
    lastUpdatedAt: str = Field(min_length=1, max_length=100)

    @field_validator(
        "runId",
        "requestId",
        "status",
        "stage",
        "submittedAt",
        "lastUpdatedAt",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_RESULT_RUN_TEXT_REQUIRED")


class AgentRunAuthorizationResult(AgentSessionModel):
    contractVersion: Literal["agent-run-authorization-result.v1"]
    authorization: AgentRunAuthorizationReceipt
    run: AgentRunAuthorizationRunSummary
    idempotencyReplay: bool

    @model_validator(mode="after")
    def validate_binding_projection(self) -> "AgentRunAuthorizationResult":
        if (
            self.run.runId != self.authorization.runId
            or self.run.requestId != self.authorization.requestId
            or self.run.submittedAt != self.authorization.createdAt
        ):
            raise ValueError("AGENT_RUN_AUTHORIZATION_RESULT_BINDING_MISMATCH")
        return self


def agent_run_authorization_command_hash(
    session_id: str,
    actor: str,
    request: AgentRunAuthorizationRequest | Mapping[str, object],
) -> str:
    normalized = (
        request
        if isinstance(request, AgentRunAuthorizationRequest)
        else AgentRunAuthorizationRequest.model_validate(request)
    )
    payload = normalized.runtime_payload()
    return agent_contract_hash(
        _COMMAND_HASH_DOMAIN,
        {
            "sessionId": _required_text(
                session_id, "AGENT_RUN_AUTHORIZATION_SESSION_ID_REQUIRED"
            ),
            "actor": _required_text(actor, "AGENT_RUN_AUTHORIZATION_ACTOR_REQUIRED"),
            "expectedStateVersion": payload["expectedStateVersion"],
            "expectedPlanRevisionId": payload["expectedPlanRevisionId"],
            "expectedPlanGeneration": payload["expectedPlanGeneration"],
            "expectedPlanHash": payload["expectedPlanHash"],
            "expectedWorkflowRevisionId": payload["expectedWorkflowRevisionId"],
            "expectedPreviewHash": payload["expectedPreviewHash"],
            "expectedInputManifestDigest": payload["expectedInputManifestDigest"],
            "expectedRunSpecHash": payload["expectedRunSpecHash"],
            "expectedExecutionPolicyHash": payload["expectedExecutionPolicyHash"],
            "expectedRuntimeProofHash": payload["expectedRuntimeProofHash"],
            "confirmation": payload["confirmation"],
            "requestId": payload["requestId"],
            "idempotencyKey": payload["idempotencyKey"],
        },
    )


def agent_run_authorization_receipt_hash(payload: Mapping[str, object]) -> str:
    return agent_contract_hash(
        _RECEIPT_HASH_DOMAIN,
        exact_hash_payload(
            payload,
            _RECEIPT_HASH_FIELDS,
            code="AGENT_RUN_AUTHORIZATION_RECEIPT_HASH_FIELD_MISSING",
        ),
    )


def agent_run_authorization_run_idempotency_key(
    session_id: str,
    authorization_id: str,
    command_hash: str,
) -> str:
    """Derive the internal run key for one immutable authorization command."""

    normalized_session_id = _required_text(
        session_id,
        "AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_SESSION_ID_REQUIRED",
    )
    normalized_authorization_id = _required_text(
        authorization_id,
        "AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_AUTHORIZATION_ID_REQUIRED",
    )
    if (
        not isinstance(command_hash, str)
        or re.fullmatch(_HEX_SHA256, command_hash) is None
    ):
        raise ValueError("AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_COMMAND_HASH_INVALID")
    digest = agent_contract_hash(
        AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_DOMAIN,
        {
            "sessionId": normalized_session_id,
            "authorizationId": normalized_authorization_id,
            "commandHash": command_hash,
        },
    )
    return f"agrunidem_v1_{digest}"


def _required_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)
    return value


__all__ = [
    "AGENT_RUN_AUTHORIZATION_CONTRACT_VERSION",
    "AGENT_RUN_AUTHORIZATION_READ_CONTRACT_VERSION",
    "AGENT_RUN_AUTHORIZATION_REQUEST_SCHEMA",
    "AGENT_RUN_AUTHORIZATION_RESULT_CONTRACT_VERSION",
    "AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_DOMAIN",
    "AgentRunAuthorizationRead",
    "AgentRunAuthorizationReceipt",
    "AgentRunAuthorizationRequest",
    "AgentRunAuthorizationResult",
    "AgentRunAuthorizationRunSummary",
    "agent_run_authorization_command_hash",
    "agent_run_authorization_receipt_hash",
    "agent_run_authorization_run_idempotency_key",
]
