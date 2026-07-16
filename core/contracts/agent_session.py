"""Provider-neutral AgentSession v1 public contracts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .workflow_design import WorkflowDesignDraftV1


AGENT_SESSION_CONTRACT_VERSION = "agent-session.v1"
AGENT_SESSION_EVENT_CONTRACT_VERSION = "agent-event.v1"
AGENT_PRINCIPAL_CONTEXT_VERSION = "agent-principal-context.v1"

AgentSessionStatus = Literal[
    "created",
    "planning",
    "awaiting_approval",
    "plan_failed",
    "changes_requested",
    "ready_to_run",
    "cancelled",
]
AgentApprovalDecision = Literal["approve", "request_changes"]
AgentSessionEventType = Literal[
    "agent.session_created",
    "agent.plan_requested",
    "agent.draft_created",
    "agent.draft_revised",
    "agent.plan_validated",
    "agent.plan_rejected",
    "agent.approval_granted",
    "agent.changes_requested",
    "agent.workflow_revision_compiled",
    "agent.replan_requested",
    "agent.session_cancelled",
]

_SECRET_LIKE_KEY_MARKERS = (
    "accesstoken",
    "apikey",
    "authorization",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "cookie",
    "credential",
    "idtoken",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "sessiontoken",
    "chainofthought",
    "hiddenreasoning",
    "rawmodeloutput",
    "reasoningtrace",
    "scratchpad",
    "systemprompt",
)
_OPAQUE_REFERENCE_SUFFIXES = ("id", "ref", "reference")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)^bearer\s+\S{16,}$"),
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),
    re.compile(r"^AKIA[0-9A-Z]{16}$"),
)


class AgentSessionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False, strict=True)

    def runtime_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class AgentPrincipalContext(AgentSessionModel):
    schemaVersion: Literal["agent-principal-context.v1"]
    actor: str = Field(min_length=1, max_length=500)

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return _required_text(value, "AGENT_PRINCIPAL_CONTEXT_ACTOR_REQUIRED")


class AgentSessionGoal(AgentSessionModel):
    summary: str = Field(min_length=1, max_length=10_000)
    successCriteria: list[str] = Field(default_factory=list, max_length=100)
    context: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_GOAL_SUMMARY_REQUIRED")

    @field_validator("successCriteria")
    @classmethod
    def validate_success_criteria(cls, values: list[str]) -> list[str]:
        return [
            _required_text(value, "AGENT_SESSION_SUCCESS_CRITERION_REQUIRED")
            for value in values
        ]

    @field_validator("context")
    @classmethod
    def reject_secret_like_context_keys(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        assert_agent_session_json_safe(value, path="goal.context")
        return value


class AgentSessionConstraints(AgentSessionModel):
    allowedToolRevisionIds: list[str] = Field(default_factory=list, max_length=1_000)
    forbiddenActions: list[str] = Field(default_factory=list, max_length=100)
    requirements: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("allowedToolRevisionIds", "forbiddenActions")
    @classmethod
    def validate_nonempty_entries(cls, values: list[str]) -> list[str]:
        return [
            _required_text(value, "AGENT_SESSION_CONSTRAINT_ENTRY_REQUIRED")
            for value in values
        ]

    @field_validator("requirements")
    @classmethod
    def reject_secret_like_requirement_keys(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        assert_agent_session_json_safe(value, path="constraints.requirements")
        return value


class AgentSessionBudget(AgentSessionModel):
    maxModelTurns: int = Field(ge=1, le=1_000)
    maxToolCalls: int = Field(ge=0, le=10_000)
    maxReplans: int = Field(ge=0, le=100)
    maxRetries: int = Field(ge=0, le=100)
    maxWallClockSeconds: int = Field(ge=1, le=604_800)


class AgentPlannerAudit(AgentSessionModel):
    adapterId: str = Field(min_length=1, max_length=200)
    adapterVersion: str | None = Field(default=None, min_length=1, max_length=200)
    modelRef: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("adapterId", "adapterVersion", "modelRef")
    @classmethod
    def validate_audit_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_PLANNER_AUDIT_TEXT_REQUIRED")


class AgentPlannerRecord(AgentSessionModel):
    adapterId: str | None = Field(default=None, min_length=1, max_length=200)
    adapterVersion: str | None = Field(default=None, min_length=1, max_length=200)
    modelRef: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("adapterId", "adapterVersion", "modelRef")
    @classmethod
    def validate_audit_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_PLANNER_RECORD_TEXT_REQUIRED")

    @model_validator(mode="after")
    def require_adapter_identity_for_populated_record(self) -> "AgentPlannerRecord":
        if self.adapterId is None and (self.adapterVersion is not None or self.modelRef is not None):
            raise ValueError("AGENT_SESSION_PLANNER_ADAPTER_ID_REQUIRED")
        return self


class AgentPlanProposal(AgentSessionModel):
    draft: WorkflowDesignDraftV1
    planner: AgentPlannerAudit

    @model_validator(mode="after")
    def reject_secret_or_model_internal_payloads(self) -> "AgentPlanProposal":
        assert_agent_session_json_safe(
            self.model_dump(by_alias=True, exclude_none=True, mode="json"),
            path="plan.proposal",
        )
        return self


class AgentSessionCreateIntent(AgentSessionModel):
    contractVersion: Literal["agent-session.v1"]
    projectId: str = Field(min_length=1, max_length=500)
    creationRequestId: str = Field(min_length=1, max_length=500)
    goal: AgentSessionGoal
    constraints: AgentSessionConstraints = Field(default_factory=AgentSessionConstraints)
    budget: AgentSessionBudget

    @field_validator("projectId", "creationRequestId")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_CREATE_TEXT_REQUIRED")


class AgentSessionCreateRequest(AgentSessionCreateIntent):
    createdBy: str = Field(min_length=1, max_length=500)

    @field_validator("createdBy")
    @classmethod
    def validate_created_by(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_CREATE_TEXT_REQUIRED")


class AgentSessionCommandIntent(AgentSessionModel):
    requestId: str = Field(min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)
    expectedStateVersion: int = Field(ge=1)

    @field_validator("requestId", "idempotencyKey")
    @classmethod
    def validate_command_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_COMMAND_TEXT_REQUIRED")


class AgentSessionCommand(AgentSessionCommandIntent):
    actor: str = Field(min_length=1, max_length=500)

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_COMMAND_TEXT_REQUIRED")


class AgentPlanRequest(AgentSessionCommand):
    proposal: AgentPlanProposal


class AgentReplanRequest(AgentSessionCommand):
    proposal: AgentPlanProposal
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_REPLAN_REASON_REQUIRED")


class AgentApprovalIntent(AgentSessionCommandIntent):
    decision: AgentApprovalDecision
    expectedPlanHash: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, min_length=1, max_length=10_000)

    @field_validator("expectedPlanHash")
    @classmethod
    def validate_expected_plan_hash(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_EXPECTED_PLAN_HASH_REQUIRED")

    @field_validator("reason")
    @classmethod
    def validate_optional_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_APPROVAL_REASON_REQUIRED")

    @model_validator(mode="after")
    def require_change_reason(self) -> "AgentApprovalRequest":
        if self.decision == "request_changes" and self.reason is None:
            raise ValueError("AGENT_SESSION_CHANGE_REASON_REQUIRED")
        return self


class AgentApprovalRequest(AgentApprovalIntent):
    actor: str = Field(min_length=1, max_length=500)

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_COMMAND_TEXT_REQUIRED")


class AgentCancelIntent(AgentSessionCommandIntent):
    reason: str | None = Field(default=None, min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def validate_optional_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_CANCEL_REASON_REQUIRED")


class AgentCancelRequest(AgentCancelIntent):
    actor: str = Field(min_length=1, max_length=500)

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return _required_text(value, "AGENT_SESSION_COMMAND_TEXT_REQUIRED")


class AgentSessionRecord(AgentSessionModel):
    contractVersion: Literal["agent-session.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    projectId: str = Field(min_length=1, max_length=500)
    goal: AgentSessionGoal
    constraints: AgentSessionConstraints
    budget: AgentSessionBudget
    status: AgentSessionStatus
    stateVersion: int = Field(ge=1)
    planGeneration: int = Field(ge=0)
    activeDraftId: str | None = Field(default=None, min_length=1, max_length=500)
    activeDraftRevision: int | None = Field(default=None, ge=1)
    activePlanHash: str | None = Field(default=None, min_length=1, max_length=500)
    workflowRevisionId: str | None = Field(default=None, min_length=1, max_length=500)
    planner: AgentPlannerRecord = Field(default_factory=AgentPlannerRecord)
    lastErrorCode: str = Field(default="", max_length=500)
    creationRequestId: str = Field(min_length=1, max_length=500)
    createdBy: str = Field(min_length=1, max_length=500)
    createdAt: str = Field(min_length=1, max_length=100)
    updatedAt: str = Field(min_length=1, max_length=100)
    cancelledAt: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator(
        "sessionId",
        "projectId",
        "activeDraftId",
        "activePlanHash",
        "workflowRevisionId",
        "creationRequestId",
        "createdBy",
        "createdAt",
        "updatedAt",
        "cancelledAt",
    )
    @classmethod
    def validate_record_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_RECORD_TEXT_REQUIRED")

    @model_validator(mode="after")
    def validate_reference_pairs(self) -> "AgentSessionRecord":
        if self.activeDraftRevision is not None and self.activeDraftId is None:
            raise ValueError("AGENT_SESSION_ACTIVE_DRAFT_ID_REQUIRED")
        if self.status == "cancelled" and self.cancelledAt is None:
            raise ValueError("AGENT_SESSION_CANCELLED_AT_REQUIRED")
        return self


class AgentSessionEvent(AgentSessionModel):
    schemaVersion: Literal["agent-event.v1"]
    eventId: str = Field(min_length=1, max_length=500)
    sessionId: str = Field(min_length=1, max_length=500)
    sequence: int = Field(ge=1)
    eventType: AgentSessionEventType
    fromStatus: AgentSessionStatus | None = None
    toStatus: AgentSessionStatus
    stateVersion: int = Field(ge=1)
    planGeneration: int = Field(ge=0)
    requestId: str = Field(min_length=1, max_length=500)
    correlationId: str | None = Field(default=None, min_length=1, max_length=500)
    idempotencyKey: str = Field(min_length=1, max_length=500)
    actor: str = Field(min_length=1, max_length=500)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    payloadHash: str = Field(min_length=1, max_length=500)
    eventHash: str = Field(min_length=1, max_length=500)
    prevEventHash: str | None = Field(default=None, min_length=1, max_length=500)
    createdAt: str = Field(min_length=1, max_length=100)

    @field_validator(
        "eventId",
        "sessionId",
        "requestId",
        "correlationId",
        "idempotencyKey",
        "actor",
        "payloadHash",
        "eventHash",
        "prevEventHash",
        "createdAt",
    )
    @classmethod
    def validate_event_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_text(value, "AGENT_SESSION_EVENT_TEXT_REQUIRED")

    @field_validator("payload")
    @classmethod
    def reject_secret_like_payload_keys(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        assert_agent_session_json_safe(value, path="event.payload")
        return value


def assert_agent_session_json_safe(value: JsonValue, *, path: str = "agent") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            normalized = re.sub(r"[^a-z0-9]+", "", key_text.lower())
            is_opaque_reference = normalized.endswith(_OPAQUE_REFERENCE_SUFFIXES)
            if (
                any(marker in normalized for marker in _SECRET_LIKE_KEY_MARKERS)
                and not is_opaque_reference
            ):
                raise ValueError(f"AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN: {path}.{key_text}")
            assert_agent_session_json_safe(nested, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            assert_agent_session_json_safe(nested, path=f"{path}[{index}]")
    elif isinstance(value, str) and any(pattern.search(value.strip()) for pattern in _SECRET_VALUE_PATTERNS):
        raise ValueError(f"AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN: {path}")


def _required_text(value: str, code: str) -> str:
    if not value.strip():
        raise ValueError(code)
    return value
