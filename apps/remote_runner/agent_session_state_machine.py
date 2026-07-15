from __future__ import annotations

from dataclasses import dataclass

from core.contracts.agent_session import AgentSessionEventType, AgentSessionStatus

from .errors import AgentSessionTransitionConflictError


AGENT_SESSION_STATUSES = frozenset(
    {
        "created",
        "planning",
        "awaiting_approval",
        "plan_failed",
        "changes_requested",
        "ready_to_run",
        "cancelled",
    }
)
TERMINAL_AGENT_SESSION_STATUSES = frozenset({"cancelled"})
REPLANABLE_AGENT_SESSION_STATUSES = frozenset(
    {"plan_failed", "changes_requested", "ready_to_run"}
)


@dataclass(frozen=True)
class AgentSessionTransition:
    event_type: AgentSessionEventType
    from_status: AgentSessionStatus | None
    to_status: AgentSessionStatus
    state_version: int
    plan_generation: int
    event_message: str
    plan_hash: str | None = None
    workflow_revision_id: str | None = None
    clear_active_plan: bool = False
    update_session: bool = True


class AgentSessionStateMachine:
    @staticmethod
    def create() -> AgentSessionTransition:
        return AgentSessionTransition(
            event_type="agent.session_created",
            from_status=None,
            to_status="created",
            state_version=1,
            plan_generation=0,
            event_message="Agent session created.",
        )

    @staticmethod
    def start_planning(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, frozenset({"created"}), action="START_PLANNING")
        if generation != 0:
            raise AgentSessionTransitionConflictError(
                f"AGENT_SESSION_INITIAL_PLAN_GENERATION_INVALID: {generation}"
            )
        return AgentSessionTransition(
            event_type="agent.plan_requested",
            from_status=status,
            to_status="planning",
            state_version=version + 1,
            plan_generation=1,
            event_message="Initial agent plan requested.",
            clear_active_plan=True,
        )

    @staticmethod
    def plan_validated(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
        plan_hash: str,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, frozenset({"planning"}), action="PLAN_VALIDATED")
        _require_planned_generation(generation)
        normalized_plan_hash = _required_text(plan_hash, "AGENT_SESSION_PLAN_HASH_REQUIRED")
        return AgentSessionTransition(
            event_type="agent.plan_validated",
            from_status=status,
            to_status="awaiting_approval",
            state_version=version + 1,
            plan_generation=generation,
            event_message="Agent plan validated and awaits approval.",
            plan_hash=normalized_plan_hash,
        )

    @staticmethod
    def plan_failed(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, frozenset({"planning"}), action="PLAN_FAILED")
        _require_planned_generation(generation)
        return AgentSessionTransition(
            event_type="agent.plan_rejected",
            from_status=status,
            to_status="plan_failed",
            state_version=version + 1,
            plan_generation=generation,
            event_message="Agent plan validation failed.",
        )

    @staticmethod
    def request_changes(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
        current_plan_hash: str,
        expected_plan_hash: str,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, frozenset({"awaiting_approval"}), action="REQUEST_CHANGES")
        plan_hash = _matching_plan_hash(
            current_plan_hash=current_plan_hash,
            expected_plan_hash=expected_plan_hash,
        )
        return AgentSessionTransition(
            event_type="agent.changes_requested",
            from_status=status,
            to_status="changes_requested",
            state_version=version + 1,
            plan_generation=generation,
            event_message="Changes requested for the active agent plan.",
            plan_hash=plan_hash,
        )

    @staticmethod
    def approve(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
        current_plan_hash: str,
        expected_plan_hash: str,
        workflow_revision_id: str,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, frozenset({"awaiting_approval"}), action="APPROVE")
        plan_hash = _matching_plan_hash(
            current_plan_hash=current_plan_hash,
            expected_plan_hash=expected_plan_hash,
        )
        revision_id = _required_text(
            workflow_revision_id,
            "AGENT_SESSION_WORKFLOW_REVISION_REQUIRED",
        )
        return AgentSessionTransition(
            event_type="agent.workflow_revision_compiled",
            from_status=status,
            to_status="ready_to_run",
            state_version=version + 1,
            plan_generation=generation,
            event_message="Approved agent plan compiled as an immutable workflow revision.",
            plan_hash=plan_hash,
            workflow_revision_id=revision_id,
        )

    @staticmethod
    def request_replan(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
        max_replans: int,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        _require_source(status, REPLANABLE_AGENT_SESSION_STATUSES, action="REPLAN")
        _require_planned_generation(generation)
        budget = _strict_nonnegative_int(max_replans, "AGENT_SESSION_MAX_REPLANS_INVALID")
        replans_used = generation - 1
        if replans_used >= budget:
            raise AgentSessionTransitionConflictError(
                f"AGENT_SESSION_REPLAN_BUDGET_EXHAUSTED: used={replans_used} max={budget}"
            )
        return AgentSessionTransition(
            event_type="agent.replan_requested",
            from_status=status,
            to_status="planning",
            state_version=version + 1,
            plan_generation=generation + 1,
            event_message="Agent replan requested.",
            clear_active_plan=True,
        )

    @staticmethod
    def cancel(
        *,
        current_status: str,
        state_version: int,
        plan_generation: int,
        expected_state_version: int,
    ) -> AgentSessionTransition:
        status, version, generation = _command_context(
            current_status=current_status,
            state_version=state_version,
            plan_generation=plan_generation,
            expected_state_version=expected_state_version,
        )
        if status == "cancelled":
            return AgentSessionTransition(
                event_type="agent.session_cancelled",
                from_status=status,
                to_status=status,
                state_version=version,
                plan_generation=generation,
                event_message="Agent session was already cancelled.",
                update_session=False,
            )
        return AgentSessionTransition(
            event_type="agent.session_cancelled",
            from_status=status,
            to_status="cancelled",
            state_version=version + 1,
            plan_generation=generation,
            event_message="Agent session cancelled.",
        )

    @staticmethod
    def is_terminal(status: str) -> bool:
        return _normalize_status(status) in TERMINAL_AGENT_SESSION_STATUSES


def _command_context(
    *,
    current_status: str,
    state_version: int,
    plan_generation: int,
    expected_state_version: int,
) -> tuple[AgentSessionStatus, int, int]:
    status = _normalize_status(current_status)
    version = _strict_positive_int(state_version, "AGENT_SESSION_STATE_VERSION_INVALID")
    expected = _strict_positive_int(
        expected_state_version,
        "AGENT_SESSION_EXPECTED_STATE_VERSION_INVALID",
    )
    if expected != version:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_STATE_VERSION_CONFLICT: expected={expected} actual={version}"
        )
    generation = _strict_nonnegative_int(
        plan_generation,
        "AGENT_SESSION_PLAN_GENERATION_INVALID",
    )
    return status, version, generation


def _require_source(
    status: AgentSessionStatus,
    allowed: frozenset[str],
    *,
    action: str,
) -> None:
    if status in TERMINAL_AGENT_SESSION_STATUSES:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_TERMINAL_IMMUTABLE: {status}"
        )
    if status not in allowed:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_{action}_STATUS_INVALID: {status}"
        )


def _matching_plan_hash(*, current_plan_hash: str, expected_plan_hash: str) -> str:
    current = _required_text(current_plan_hash, "AGENT_SESSION_ACTIVE_PLAN_HASH_REQUIRED")
    expected = _required_text(expected_plan_hash, "AGENT_SESSION_EXPECTED_PLAN_HASH_REQUIRED")
    if current != expected:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_PLAN_HASH_CONFLICT: expected={expected} actual={current}"
        )
    return current


def _require_planned_generation(value: int) -> None:
    if value < 1:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_PLAN_GENERATION_NOT_STARTED: {value}"
        )


def _normalize_status(value: str) -> AgentSessionStatus:
    if not isinstance(value, str):
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_STATUS_UNSUPPORTED: {value}"
        )
    normalized = value.strip().lower()
    if normalized not in AGENT_SESSION_STATUSES:
        raise AgentSessionTransitionConflictError(
            f"AGENT_SESSION_STATUS_UNSUPPORTED: {normalized}"
        )
    return normalized  # type: ignore[return-value]


def _strict_positive_int(value: int, code: str) -> int:
    normalized = _strict_nonnegative_int(value, code)
    if normalized < 1:
        raise AgentSessionTransitionConflictError(f"{code}: {value}")
    return normalized


def _strict_nonnegative_int(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentSessionTransitionConflictError(f"{code}: {value}")
    return value


def _required_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentSessionTransitionConflictError(code)
    return value
