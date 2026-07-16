"""Local deterministic planner orchestration for AgentSession commands."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from apps.api.agent_fastq_qc_planner import build_fastq_qc_plan_proposal
from apps.api.capability_graph_service import CapabilityGraphService
from apps.api.tool_registry_payload import registered_tools_from_runtime_payload
from core.app_runtime.errors import RuntimeConflictError
from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_ADAPTER_ID,
    AgentFastqQcGoalContext,
)
from core.contracts.agent_session import (
    AgentPlanProposal,
    AgentPlanRequest as RemoteAgentPlanRequest,
    AgentReplanRequest as RemoteAgentReplanRequest,
    AgentSessionRecord,
)


def plan_agent_session_with_adapter(
    *,
    runtime: Any,
    session_id: str,
    server_id: str,
    command: dict[str, Any],
    replan: bool,
) -> dict[str, Any]:
    session = AgentSessionRecord.model_validate(
        _data_object(
            runtime.get_agent_session(session_id, server_id=server_id),
            "AGENT_SESSION_RESPONSE_INVALID",
        )
    )
    context = _goal_context(session)
    if replan:
        raise ValueError("WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED")
    proposal = _persisted_replay_proposal(
        runtime,
        session_id=session_id,
        server_id=server_id,
        idempotency_key=str(command["idempotencyKey"]),
        replan=replan,
    )
    if proposal is None:
        _validate_authoritative_upload(runtime, context=context, server_id=server_id)
        tools_payload = runtime.list_tools(server_id=server_id)
        registered_tools = registered_tools_from_runtime_payload(tools_payload)
        capability_graph = CapabilityGraphService().snapshot(
            registered_tools=registered_tools,
            catalog=_empty_catalog(),
            agent_selectable_only=True,
        )
        proposal = build_fastq_qc_plan_proposal(
            session=session,
            capability_graph=capability_graph,
        )

    remote_payload = dict(command) | {"proposal": proposal.runtime_payload()}
    if replan:
        validated = RemoteAgentReplanRequest.model_validate(remote_payload)
        return runtime.replan_agent_session(
            session_id,
            validated.runtime_payload(),
            server_id=server_id,
        )
    validated = RemoteAgentPlanRequest.model_validate(remote_payload)
    return runtime.plan_agent_session(
        session_id,
        validated.runtime_payload(),
        server_id=server_id,
    )


def _goal_context(session: AgentSessionRecord) -> AgentFastqQcGoalContext:
    try:
        return AgentFastqQcGoalContext.model_validate(session.goal.context)
    except ValidationError as exc:
        raise ValueError("INPUT_FASTQ_QC_GOAL_CONTEXT_INVALID") from exc


def _validate_authoritative_upload(
    runtime: Any,
    *,
    context: AgentFastqQcGoalContext,
    server_id: str,
) -> None:
    expected = context.inputs[0].runtime_payload()
    actual = _data_object(
        runtime.get_upload(str(expected["uploadId"]), server_id=server_id),
        "INPUT_FASTQ_QC_UPLOAD_RESPONSE_INVALID",
    )
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError("INPUT_FASTQ_QC_UPLOAD_MANIFEST_MISMATCH")


def _persisted_replay_proposal(
    runtime: Any,
    *,
    session_id: str,
    server_id: str,
    idempotency_key: str,
    replan: bool,
) -> AgentPlanProposal | None:
    events = _items(
        runtime.list_agent_session_events(session_id, server_id=server_id),
        "AGENT_SESSION_EVENTS_RESPONSE_INVALID",
    )
    matches = [item for item in events if item.get("idempotencyKey") == idempotency_key]
    if not matches:
        return None
    expected_type = "agent.replan_requested" if replan else "agent.plan_requested"
    if len(matches) != 1 or matches[0].get("eventType") != expected_type:
        raise RuntimeConflictError("AGENT_COMMAND_IDEMPOTENCY_CONFLICT")
    generation = matches[0].get("planGeneration")
    plans = _items(
        runtime.list_agent_session_plans(session_id, server_id=server_id),
        "AGENT_SESSION_PLANS_RESPONSE_INVALID",
    )
    match = next((item for item in plans if item.get("planGeneration") == generation), None)
    if match is not None:
        proposal_payload = match.get("proposal")
    else:
        event_payload = matches[0].get("payload")
        proposal_payload = (
            event_payload.get("proposalIntent") if isinstance(event_payload, dict) else None
        )
        if proposal_payload is None:
            raise RuntimeConflictError("AGENT_PLAN_REPLAY_INTENT_UNAVAILABLE")
    if not isinstance(proposal_payload, dict):
        raise ValueError("AGENT_SESSION_PLAN_PROPOSAL_INVALID")
    proposal_payload = dict(proposal_payload)
    draft_payload = proposal_payload.get("draft")
    if not isinstance(draft_payload, dict):
        raise ValueError("AGENT_SESSION_PLAN_PROPOSAL_INVALID")
    draft_payload = dict(draft_payload)
    provenance = draft_payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("AGENT_SESSION_PLAN_PROPOSAL_INVALID")
    provenance = dict(provenance)
    provenance.pop("agentSessionId", None)
    provenance.pop("agentPlanGeneration", None)
    draft_payload["provenance"] = provenance
    proposal_payload["draft"] = draft_payload
    proposal = AgentPlanProposal.model_validate(proposal_payload)
    if proposal.planner.adapterId != AGENT_FASTQ_QC_ADAPTER_ID:
        raise RuntimeConflictError("AGENT_COMMAND_IDEMPOTENCY_CONFLICT")
    return proposal


def _data_object(payload: Any, code: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(code)
    value = payload.get("data")
    if isinstance(value, dict):
        return value
    raise ValueError(code)


def _items(payload: Any, code: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError(code)
    data = payload.get("data")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError(code)
    return items


def _empty_catalog() -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 1,
        "hasMore": False,
        "sourceCounts": {},
        "addableDraftCounts": {},
        "qualityCounts": {},
    }


__all__ = ["plan_agent_session_with_adapter"]
