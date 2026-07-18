"""Strict immutable effect-budget contracts for AgentSession execution."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash, exact_hash_payload
from .agent_session import AgentSessionModel, assert_agent_session_json_safe


AGENT_SESSION_EFFECT_BUDGET_CONTRACT_VERSION = "agent-session-effect-budget.v1"
AGENT_SESSION_EFFECT_BUDGET_GRANT_REQUEST_SCHEMA = "agent-session-effect-budget-grant.v1"
AGENT_SESSION_EFFECT_BUDGET_READ_CONTRACT_VERSION = "agent-session-effect-budget-read.v1"

_COMMAND_HASH_DOMAIN = "agent-session-effect-budget-grant-command.v1"
_RECEIPT_HASH_DOMAIN = "agent-session-effect-budget-receipt.v1"
_EFFECT_BUDGET_HASH_DOMAIN = AGENT_SESSION_EFFECT_BUDGET_CONTRACT_VERSION
_HEX_SHA256 = r"^[0-9a-f]{64}$"
_RECEIPT_HASH_FIELDS = (
    "contractVersion",
    "sessionId",
    "maxRunSubmissions",
    "actor",
    "requestId",
    "idempotencyKey",
    "commandHash",
    "createdAt",
)


class AgentSessionEffectBudgetGrantRequest(AgentSessionModel):
    expectedStateVersion: Literal[1]
    maxRunSubmissions: Literal[1]
    confirmation: Literal["enable-one-run"]
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)

    @field_validator("expectedStateVersion", "maxRunSubmissions", mode="before")
    @classmethod
    def validate_exact_one(cls, value: object) -> int:
        return _exact_one(value, "AGENT_EFFECT_BUDGET_GRANT_EXACT_ONE_REQUIRED")

    @field_validator("requestId", "idempotencyKey")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_EFFECT_BUDGET_GRANT_TEXT_REQUIRED")

    @model_validator(mode="after")
    def reject_secret_like_values(self) -> "AgentSessionEffectBudgetGrantRequest":
        assert_agent_session_json_safe(self.runtime_payload(), path="effectBudget.grant")
        return self


class AgentSessionEffectBudgetReceipt(AgentSessionModel):
    contractVersion: Literal["agent-session-effect-budget.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    maxRunSubmissions: Literal[1]
    actor: str = Field(min_length=1, max_length=500)
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)
    commandHash: str = Field(pattern=_HEX_SHA256)
    receiptHash: str = Field(pattern=_HEX_SHA256)
    createdAt: str = Field(min_length=1, max_length=100)

    @field_validator("maxRunSubmissions", mode="before")
    @classmethod
    def validate_exact_one(cls, value: object) -> int:
        return _exact_one(value, "AGENT_EFFECT_BUDGET_RECEIPT_EXACT_ONE_REQUIRED")

    @field_validator("sessionId", "actor", "requestId", "idempotencyKey", "createdAt")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_EFFECT_BUDGET_RECEIPT_TEXT_REQUIRED")

    @model_validator(mode="after")
    def validate_receipt(self) -> "AgentSessionEffectBudgetReceipt":
        payload = self.runtime_payload()
        assert_agent_session_json_safe(payload, path="effectBudget.receipt")
        expected = agent_effect_budget_receipt_hash(payload)
        if not hmac.compare_digest(expected, self.receiptHash):
            raise ValueError("AGENT_EFFECT_BUDGET_RECEIPT_HASH_MISMATCH")
        return self


class AgentSessionEffectBudgetRead(AgentSessionModel):
    contractVersion: Literal["agent-session-effect-budget-read.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    state: Literal["absent", "present"]
    budget: AgentSessionEffectBudgetReceipt | None = None

    @field_validator("sessionId")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _required_text(value, "AGENT_EFFECT_BUDGET_READ_SESSION_ID_REQUIRED")

    @model_validator(mode="after")
    def validate_presence_and_identity(self) -> "AgentSessionEffectBudgetRead":
        if self.state == "absent" and self.budget is not None:
            raise ValueError("AGENT_EFFECT_BUDGET_READ_ABSENT_HAS_BUDGET")
        if self.state == "present" and self.budget is None:
            raise ValueError("AGENT_EFFECT_BUDGET_READ_PRESENT_REQUIRES_BUDGET")
        if self.budget is not None and self.budget.sessionId != self.sessionId:
            raise ValueError("AGENT_EFFECT_BUDGET_READ_SESSION_ID_MISMATCH")
        return self


def agent_effect_budget_command_hash(
    session_id: str,
    actor: str,
    request: AgentSessionEffectBudgetGrantRequest | Mapping[str, object],
) -> str:
    normalized = (
        request
        if isinstance(request, AgentSessionEffectBudgetGrantRequest)
        else AgentSessionEffectBudgetGrantRequest.model_validate(request)
    )
    payload = normalized.runtime_payload()
    return agent_contract_hash(
        _COMMAND_HASH_DOMAIN,
        {
            "sessionId": _required_text(session_id, "AGENT_EFFECT_BUDGET_SESSION_ID_REQUIRED"),
            "actor": _required_text(actor, "AGENT_EFFECT_BUDGET_ACTOR_REQUIRED"),
            "expectedStateVersion": payload["expectedStateVersion"],
            "maxRunSubmissions": payload["maxRunSubmissions"],
            "confirmation": payload["confirmation"],
            "requestId": payload["requestId"],
            "idempotencyKey": payload["idempotencyKey"],
        },
    )


def agent_effect_budget_receipt_hash(payload: Mapping[str, object]) -> str:
    return agent_contract_hash(
        _RECEIPT_HASH_DOMAIN,
        exact_hash_payload(
            payload,
            _RECEIPT_HASH_FIELDS,
            code="AGENT_EFFECT_BUDGET_RECEIPT_HASH_FIELD_MISSING",
        ),
    )


def agent_effect_budget_hash(
    receipt: AgentSessionEffectBudgetReceipt | Mapping[str, object],
) -> str:
    normalized = (
        receipt
        if isinstance(receipt, AgentSessionEffectBudgetReceipt)
        else AgentSessionEffectBudgetReceipt.model_validate(receipt)
    )
    return agent_contract_hash(_EFFECT_BUDGET_HASH_DOMAIN, normalized.runtime_payload())


def _required_text(value: str, code: str) -> str:
    if not value.strip():
        raise ValueError(code)
    return value


def _exact_one(value: object, code: str) -> int:
    if type(value) is not int or value != 1:
        raise ValueError(code)
    return value


__all__ = [
    "AGENT_SESSION_EFFECT_BUDGET_CONTRACT_VERSION",
    "AGENT_SESSION_EFFECT_BUDGET_GRANT_REQUEST_SCHEMA",
    "AGENT_SESSION_EFFECT_BUDGET_READ_CONTRACT_VERSION",
    "AgentSessionEffectBudgetGrantRequest",
    "AgentSessionEffectBudgetRead",
    "AgentSessionEffectBudgetReceipt",
    "agent_effect_budget_command_hash",
    "agent_effect_budget_hash",
    "agent_effect_budget_receipt_hash",
]
