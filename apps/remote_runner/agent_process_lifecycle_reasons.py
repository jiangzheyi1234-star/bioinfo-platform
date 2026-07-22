"""Exact path-free reason vocabulary for governed process lifecycles."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal, TypeAlias


AgentProcessLifecycleReasonState: TypeAlias = Literal[
    "spawn_failed",
    "exited",
    "terminated",
    "lost",
]

AGENT_PROCESS_SPAWN_FAILURE_CODES = frozenset(
    {
        "HELPER_NOT_READY",
        "INCARNATION_CAPTURE_FAILED",
        "LAUNCH_CONTROLLER_LOST",
        "PROCESS_CREATE_FAILED",
        "START_AUTHORITY_REJECTED",
    }
)
AGENT_PROCESS_EXIT_REASONS = frozenset({"exit_code", "signal"})
AGENT_PROCESS_TERMINATION_REASONS = frozenset(
    {"cancelled", "lease_lost", "reconciler_terminated", "release_failed"}
)
AGENT_PROCESS_LOSS_REASONS = frozenset(
    {
        "controller_lost",
        "exit_unobserved",
        "incarnation_mismatch",
        "release_state_unknown",
    }
)

AGENT_PROCESS_LIFECYCLE_REASONS_BY_STATE = MappingProxyType(
    {
        "spawn_failed": AGENT_PROCESS_SPAWN_FAILURE_CODES,
        "exited": AGENT_PROCESS_EXIT_REASONS,
        "terminated": AGENT_PROCESS_TERMINATION_REASONS,
        "lost": AGENT_PROCESS_LOSS_REASONS,
    }
)


def agent_process_lifecycle_reason_is_allowed(
    state: object,
    reason: object,
) -> bool:
    """Return whether ``reason`` is an exact public code for ``state``."""

    if not isinstance(state, str) or not isinstance(reason, str):
        return False
    allowed = AGENT_PROCESS_LIFECYCLE_REASONS_BY_STATE.get(state)
    return allowed is not None and reason in allowed


def _sql_text_list(values: frozenset[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))


AGENT_PROCESS_LIFECYCLE_REASON_SQL_PREDICATE = (
    "("
    + " OR ".join(
        f"(NEW.state = '{state}' AND NEW.exit_reason IN ({_sql_text_list(reasons)}))"
        for state, reasons in AGENT_PROCESS_LIFECYCLE_REASONS_BY_STATE.items()
    )
    + ")"
)


__all__ = [
    "AGENT_PROCESS_EXIT_REASONS",
    "AGENT_PROCESS_LIFECYCLE_REASONS_BY_STATE",
    "AGENT_PROCESS_LIFECYCLE_REASON_SQL_PREDICATE",
    "AGENT_PROCESS_LOSS_REASONS",
    "AGENT_PROCESS_SPAWN_FAILURE_CODES",
    "AGENT_PROCESS_TERMINATION_REASONS",
    "AgentProcessLifecycleReasonState",
    "agent_process_lifecycle_reason_is_allowed",
]
