"""Atomic AgentSession read-model contract shared across API boundaries."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import model_validator

from .agent_plan import AgentApprovalRecord, AgentPlanRevisionRecord
from .agent_session import AgentSessionEvent, AgentSessionModel, AgentSessionRecord


AGENT_SESSION_SNAPSHOT_CONTRACT_VERSION = "agent-session-snapshot.v1"


class AgentSessionSnapshot(AgentSessionModel):
    contractVersion: Literal["agent-session-snapshot.v1"]
    session: AgentSessionRecord
    events: list[AgentSessionEvent]
    plans: list[AgentPlanRevisionRecord]
    approvals: list[AgentApprovalRecord]

    @model_validator(mode="after")
    def validate_consistent_projection(self) -> "AgentSessionSnapshot":
        session_id = self.session.sessionId
        if not self.events:
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENTS_REQUIRED")
        if any(item.sessionId != session_id for item in self.events):
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_IDENTITY_MISMATCH")
        if any(item.sessionId != session_id for item in self.plans):
            raise ValueError("AGENT_SESSION_SNAPSHOT_PLAN_IDENTITY_MISMATCH")
        if any(item.sessionId != session_id for item in self.approvals):
            raise ValueError("AGENT_SESSION_SNAPSHOT_APPROVAL_IDENTITY_MISMATCH")

        expected_sequences = list(range(1, len(self.events) + 1))
        if [item.sequence for item in self.events] != expected_sequences:
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_SEQUENCE_INVALID")
        event_ids = {item.eventId for item in self.events}
        if len(event_ids) != len(self.events):
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_ID_DUPLICATE")
        previous_hash: str | None = None
        for event in self.events:
            if event.prevEventHash != previous_hash:
                raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_CHAIN_INVALID")
            canonical_payload = json.dumps(
                event.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
            if event.payloadHash != payload_hash:
                raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_PAYLOAD_HASH_INVALID")
            previous_hash = event.eventHash
        if max(item.stateVersion for item in self.events) != self.session.stateVersion:
            raise ValueError("AGENT_SESSION_SNAPSHOT_STATE_VERSION_MISMATCH")
        if any(item.planGeneration > self.session.planGeneration for item in self.events):
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_GENERATION_INVALID")
        latest_event = self.events[-1]
        if latest_event.toStatus != self.session.status:
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_STATUS_MISMATCH")
        if latest_event.planGeneration != self.session.planGeneration:
            raise ValueError("AGENT_SESSION_SNAPSHOT_EVENT_GENERATION_MISMATCH")

        generations = [item.planGeneration for item in self.plans]
        if generations != sorted(set(generations)):
            raise ValueError("AGENT_SESSION_SNAPSHOT_PLAN_ORDER_INVALID")
        if generations and generations[-1] > self.session.planGeneration:
            raise ValueError("AGENT_SESSION_SNAPSHOT_PLAN_GENERATION_INVALID")

        plans_by_id = {item.planRevisionId: item for item in self.plans}
        if len(plans_by_id) != len(self.plans):
            raise ValueError("AGENT_SESSION_SNAPSHOT_PLAN_ID_DUPLICATE")
        current_plans = [
            item
            for item in self.plans
            if item.planGeneration == self.session.planGeneration
        ]
        active_references = (
            self.session.activeDraftId,
            self.session.activeDraftRevision,
            self.session.activePlanHash,
        )
        has_any_active_reference = any(item is not None for item in active_references)
        has_complete_active_reference = all(item is not None for item in active_references)
        if has_any_active_reference and not has_complete_active_reference:
            raise ValueError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_PARTIAL")

        status_requires_active_plan = self.session.status in {
            "awaiting_approval",
            "plan_failed",
            "changes_requested",
            "ready_to_run",
        }
        if status_requires_active_plan and (
            not has_complete_active_reference or len(current_plans) != 1
        ):
            raise ValueError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_REQUIRED")
        if self.session.status == "created" and current_plans:
            raise ValueError("AGENT_SESSION_SNAPSHOT_CREATED_CURRENT_PLAN_FORBIDDEN")

        approval_ids = {item.approvalId for item in self.approvals}
        if len(approval_ids) != len(self.approvals):
            raise ValueError("AGENT_SESSION_SNAPSHOT_APPROVAL_ID_DUPLICATE")
        for approval in self.approvals:
            plan = plans_by_id.get(approval.planRevisionId)
            if (
                plan is None
                or plan.planGeneration != approval.planGeneration
                or plan.planHash != approval.planHash
            ):
                raise ValueError("AGENT_SESSION_SNAPSHOT_APPROVAL_PLAN_MISMATCH")
            if approval.expectedStateVersion > self.session.stateVersion:
                raise ValueError("AGENT_SESSION_SNAPSHOT_APPROVAL_VERSION_INVALID")

        if has_complete_active_reference:
            active = next(
                (
                    item
                    for item in self.plans
                    if item.planHash == self.session.activePlanHash
                    and item.planGeneration == self.session.planGeneration
                    and item.draftId == self.session.activeDraftId
                    and item.draftRevision == self.session.activeDraftRevision
                ),
                None,
            )
            if active is None:
                raise ValueError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH")
        return self


__all__ = [
    "AGENT_SESSION_SNAPSHOT_CONTRACT_VERSION",
    "AgentSessionSnapshot",
]
