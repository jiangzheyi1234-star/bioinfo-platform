"""Immutable Agent plan and approval read contracts."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .agent_session import (
    AgentApprovalDecision,
    AgentPlanProposal,
    AgentSessionBudget,
    AgentSessionModel,
    assert_agent_session_json_safe,
)
from .workflow_design import normalize_workflow_design_draft


AGENT_PLAN_REVISION_CONTRACT_VERSION = "agent-plan-revision.v1"
AGENT_APPROVAL_CONTRACT_VERSION = "agent-approval.v1"


class AgentPlanRevisionRecord(AgentSessionModel):
    contractVersion: Literal["agent-plan-revision.v1"]
    planRevisionId: str = Field(min_length=1, max_length=500)
    sessionId: str = Field(min_length=1, max_length=500)
    planGeneration: int = Field(ge=1)
    parentPlanRevisionId: str | None = Field(default=None, min_length=1, max_length=500)
    draftId: str = Field(min_length=1, max_length=500)
    draftRevision: int = Field(ge=1)
    planHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonicalPayload: str = Field(min_length=2, max_length=10_000_000)
    proposal: AgentPlanProposal
    validation: dict[str, JsonValue]
    budget: AgentSessionBudget
    createdBy: str = Field(min_length=1, max_length=500)
    createdAt: str = Field(min_length=1, max_length=100)

    @field_validator(
        "planRevisionId",
        "sessionId",
        "parentPlanRevisionId",
        "draftId",
        "createdBy",
        "createdAt",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("AGENT_PLAN_REVISION_TEXT_REQUIRED")
        return value

    @field_validator("validation")
    @classmethod
    def validate_safe_validation(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        assert_agent_session_json_safe(value, path="plan.validation")
        return value

    @model_validator(mode="after")
    def validate_parent_generation(self) -> "AgentPlanRevisionRecord":
        if self.planGeneration == 1 and self.parentPlanRevisionId is not None:
            raise ValueError("AGENT_PLAN_PARENT_REVISION_UNEXPECTED")
        try:
            canonical = json.loads(
                self.canonicalPayload,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_finite_json_number,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("AGENT_PLAN_CANONICAL_PAYLOAD_INVALID") from exc
        normalized_proposal = self.proposal.runtime_payload()
        normalized_proposal["draft"] = normalize_workflow_design_draft(
            normalized_proposal["draft"]
        )
        expected = {
            "budget": self.budget.runtime_payload(),
            "contractVersion": self.contractVersion,
            "draftId": self.draftId,
            "draftRevision": self.draftRevision,
            "parentPlanRevisionId": self.parentPlanRevisionId,
            "planGeneration": self.planGeneration,
            "proposal": normalized_proposal,
            "sessionId": self.sessionId,
            "validation": self.validation,
        }
        if not _json_values_equivalent(canonical, expected):
            raise ValueError("AGENT_PLAN_CANONICAL_PAYLOAD_MISMATCH")
        actual_hash = hashlib.sha256(self.canonicalPayload.encode("utf-8")).hexdigest()
        if actual_hash != self.planHash:
            raise ValueError("AGENT_PLAN_CANONICAL_HASH_MISMATCH")
        return self


def _unique_json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _json_values_equivalent(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(float(left)) and math.isfinite(float(right)) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_values_equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_values_equivalent(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


class AgentApprovalRecord(AgentSessionModel):
    contractVersion: Literal["agent-approval.v1"]
    approvalId: str = Field(min_length=1, max_length=500)
    sessionId: str = Field(min_length=1, max_length=500)
    planRevisionId: str = Field(min_length=1, max_length=500)
    planGeneration: int = Field(ge=1)
    planHash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedStateVersion: int = Field(ge=1)
    decision: AgentApprovalDecision
    scope: Literal["compile_workflow_revision"] = "compile_workflow_revision"
    actor: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, min_length=1, max_length=10_000)
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)
    createdAt: str = Field(min_length=1, max_length=100)

    @field_validator(
        "approvalId",
        "sessionId",
        "planRevisionId",
        "actor",
        "reason",
        "requestId",
        "idempotencyKey",
        "createdAt",
    )
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("AGENT_APPROVAL_TEXT_REQUIRED")
        return value

    @model_validator(mode="after")
    def require_change_reason(self) -> "AgentApprovalRecord":
        if self.decision == "request_changes" and self.reason is None:
            raise ValueError("AGENT_APPROVAL_CHANGE_REASON_REQUIRED")
        return self
