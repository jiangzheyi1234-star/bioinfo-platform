"""Immutable Agent plan and approval read contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .agent_session import (
    AgentApprovalDecision,
    AgentPlanProposal,
    AgentSessionBudget,
    AgentSessionModel,
    assert_agent_session_json_safe,
)


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
        return self


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
