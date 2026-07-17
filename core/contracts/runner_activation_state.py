"""Private state-machine rules for recoverable runner activations."""

from __future__ import annotations

from collections.abc import Callable


RUNNER_ACTIVATION_INITIAL_STATE = "none"
RUNNER_ACTIVATION_STATES = (
    "prepared",
    "guarded",
    "stopping",
    "stopped",
    "promoting",
    "promoted",
    "starting",
    "verifying",
    "candidate_verified",
    "committing",
    "committed",
    "aborted",
    "recovery_required",
)
RUNNER_ACTIVATION_TERMINAL_STATES = (
    "committed",
    "aborted",
    "recovery_required",
)

LEGAL_RUNNER_ACTIVATION_TRANSITIONS = {
    RUNNER_ACTIVATION_INITIAL_STATE: frozenset({"prepared"}),
    "prepared": frozenset({"guarded", "aborted", "recovery_required"}),
    "guarded": frozenset({"stopping", "aborted", "recovery_required"}),
    "stopping": frozenset({"stopped", "recovery_required"}),
    "stopped": frozenset({"promoting", "recovery_required"}),
    "promoting": frozenset({"promoted", "recovery_required"}),
    "promoted": frozenset({"starting", "recovery_required"}),
    "starting": frozenset({"verifying", "recovery_required"}),
    "verifying": frozenset({"candidate_verified", "recovery_required"}),
    "candidate_verified": frozenset({"committing", "recovery_required"}),
    "committing": frozenset({"committed", "recovery_required"}),
}

RUNNER_ACTIVATION_INVOCATION_REQUIRED_STATES = frozenset(
    {"verifying", "candidate_verified", "committing", "committed"}
)
RUNNER_ACTIVATION_INVOCATION_FORBIDDEN_STATES = frozenset(
    {
        "prepared",
        "guarded",
        "stopping",
        "stopped",
        "promoting",
        "promoted",
        "starting",
        "aborted",
    }
)


def require_runner_activation_state(
    value: object,
    *,
    allow_initial: bool,
    make_error: Callable[[str], Exception],
) -> str:
    allowed = set(RUNNER_ACTIVATION_STATES)
    if allow_initial:
        allowed.add(RUNNER_ACTIVATION_INITIAL_STATE)
    if not isinstance(value, str) or value not in allowed:
        raise make_error("runner activation transition state is invalid")
    return value


def require_legal_runner_activation_transition(
    from_state: str,
    to_state: str,
    *,
    make_error: Callable[[str], Exception],
) -> None:
    if to_state not in LEGAL_RUNNER_ACTIVATION_TRANSITIONS.get(
        from_state,
        frozenset(),
    ):
        raise make_error(
            f"runner activation transition {from_state}->{to_state} is illegal"
        )


def require_runner_activation_embedded_lineage_shape(
    operation: str,
    lineage: tuple[str, str, str],
    *,
    make_error: Callable[[str], Exception],
) -> None:
    previous_target_fingerprint, previous_commit_fingerprint, recovery = lineage
    has_previous_target = bool(previous_target_fingerprint)
    has_previous_commit = bool(previous_commit_fingerprint)
    if has_previous_target != has_previous_commit:
        raise make_error("runner activation embedded previous lineage is invalid")
    if operation == "install" and has_previous_target:
        raise make_error("runner activation install has previous lineage")
    if operation in {"upgrade", "token_rotation", "rollback"} and not (
        has_previous_target and has_previous_commit
    ):
        raise make_error(f"runner activation {operation} has no previous lineage")
    if operation == "rollback":
        if not recovery:
            raise make_error("runner activation rollback has no recovery lineage")
    elif recovery:
        raise make_error("runner activation non-rollback has recovery lineage")


__all__ = [
    "RUNNER_ACTIVATION_INITIAL_STATE",
    "RUNNER_ACTIVATION_INVOCATION_FORBIDDEN_STATES",
    "RUNNER_ACTIVATION_INVOCATION_REQUIRED_STATES",
    "RUNNER_ACTIVATION_STATES",
    "RUNNER_ACTIVATION_TERMINAL_STATES",
    "require_legal_runner_activation_transition",
    "require_runner_activation_embedded_lineage_shape",
    "require_runner_activation_state",
]
