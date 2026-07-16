"""Local-only routing wrappers for provider-neutral AgentSession contracts."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import Field

from core.contracts.agent_fastq_qc import (
    AgentFastqQcPlanCommand as AgentPlanCommandContract,
    AgentFastqQcReplanCommand as AgentReplanCommandContract,
)
from core.contracts.agent_session import (
    AgentApprovalRequest as AgentApprovalContract,
    AgentCancelRequest as AgentCancelContract,
    AgentSessionCreateRequest as AgentSessionCreateContract,
)


class AgentSessionCreateRequest(AgentSessionCreateContract):
    serverId: str | None = Field(default=None, min_length=1, max_length=500)


class AgentPlanRequest(AgentPlanCommandContract):
    serverId: str = Field(min_length=1, max_length=500)


class AgentReplanRequest(AgentReplanCommandContract):
    serverId: str = Field(min_length=1, max_length=500)


class AgentApprovalRequest(AgentApprovalContract):
    serverId: str | None = Field(default=None, min_length=1, max_length=500)


class AgentCancelRequest(AgentCancelContract):
    serverId: str | None = Field(default=None, min_length=1, max_length=500)


LocalAgentRequest: TypeAlias = (
    AgentSessionCreateRequest
    | AgentPlanRequest
    | AgentReplanRequest
    | AgentApprovalRequest
    | AgentCancelRequest
)


def split_agent_routing(request: LocalAgentRequest) -> tuple[str | None, dict[str, object]]:
    """Return local routing separately from the strict remote contract payload."""

    server_id = str(request.serverId or "").strip() or None
    payload = request.model_dump(
        by_alias=True,
        exclude={"serverId"},
        exclude_none=True,
        mode="json",
    )
    return server_id, payload
