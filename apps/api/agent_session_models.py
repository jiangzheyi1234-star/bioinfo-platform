"""Local-only routing wrappers for provider-neutral AgentSession contracts."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import Field, field_validator

from core.contracts.agent_session import (
    AgentApprovalIntent,
    AgentCancelIntent,
    AgentSessionCommandIntent,
    AgentSessionCreateIntent,
)


class AgentSessionCreateRequest(AgentSessionCreateIntent):
    serverId: str = Field(min_length=1, max_length=500)

    @field_validator("serverId")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        return _required_server_id(value)


class AgentPlanRequest(AgentSessionCommandIntent):
    serverId: str = Field(min_length=1, max_length=500)

    @field_validator("serverId")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        return _required_server_id(value)


class AgentReplanRequest(AgentSessionCommandIntent):
    serverId: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("serverId")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        return _required_server_id(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("AGENT_SESSION_REPLAN_REASON_REQUIRED")
        return normalized


class AgentApprovalRequest(AgentApprovalIntent):
    serverId: str = Field(min_length=1, max_length=500)

    @field_validator("serverId")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        return _required_server_id(value)


class AgentCancelRequest(AgentCancelIntent):
    serverId: str = Field(min_length=1, max_length=500)

    @field_validator("serverId")
    @classmethod
    def validate_server_id(cls, value: str) -> str:
        return _required_server_id(value)


LocalAgentRequest: TypeAlias = (
    AgentSessionCreateRequest
    | AgentPlanRequest
    | AgentReplanRequest
    | AgentApprovalRequest
    | AgentCancelRequest
)


def split_agent_routing(request: LocalAgentRequest) -> tuple[str, dict[str, object]]:
    """Return local routing separately from the strict remote contract payload."""

    server_id = request.serverId
    payload = request.model_dump(
        by_alias=True,
        exclude={"serverId"},
        exclude_none=True,
        mode="json",
    )
    return server_id, payload


def _required_server_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("AGENT_SESSION_SERVER_ID_REQUIRED")
    return normalized
