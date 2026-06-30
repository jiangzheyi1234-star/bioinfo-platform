from __future__ import annotations

import pytest

from apps.remote_runner.run_execution_state_machine import RunExecutionStateMachine


def test_submission_transition_matches_run_acceptance_contract() -> None:
    transition = RunExecutionStateMachine.submission_accepted()

    assert transition.event_type == "accepted"
    assert transition.from_status is None
    assert transition.to_status == "queued"
    assert transition.stage == "submitted"
    assert transition.state_version == 1
    assert transition.row_message == "Run accepted"
    assert transition.event_message == "Accepted for asynchronous execution"
    assert transition.update_run is True


def test_status_publication_increments_version_and_preserves_event_shape() -> None:
    transition = RunExecutionStateMachine.publish_status(
        current_status="queued",
        state_version=1,
        status="completed",
        stage="finalize",
        message="Run completed.",
    )

    assert transition.event_type == "status-transition"
    assert transition.from_status == "queued"
    assert transition.to_status == "completed"
    assert transition.stage == "finalize"
    assert transition.state_version == 2
    assert transition.row_message == "Run completed."
    assert transition.event_message == "Run completed."
    assert RunExecutionStateMachine.is_terminal_run_status(transition.to_status) is True


def test_cancel_transition_updates_only_nonterminal_runs() -> None:
    nonterminal = RunExecutionStateMachine.request_cancel(
        current_status="running",
        state_version=4,
    )
    terminal = RunExecutionStateMachine.request_cancel(
        current_status="failed",
        state_version=9,
    )

    assert nonterminal.event_type == "run_cancel_requested"
    assert nonterminal.from_status == "running"
    assert nonterminal.to_status == "canceling"
    assert nonterminal.stage == "cancel"
    assert nonterminal.state_version == 5
    assert nonterminal.update_run is True

    assert terminal.event_type == "run_cancel_requested"
    assert terminal.from_status == "failed"
    assert terminal.to_status == "failed"
    assert terminal.stage == "cancel"
    assert terminal.state_version == 9
    assert terminal.update_run is False


def test_retry_transition_rejects_non_retryable_statuses() -> None:
    transition = RunExecutionStateMachine.request_retry(
        current_status="cancelled",
        state_version=3,
    )

    assert transition.event_type == "run_retry_requested"
    assert transition.from_status == "cancelled"
    assert transition.to_status == "queued"
    assert transition.stage == "retry"
    assert transition.state_version == 4
    assert transition.row_message == "Run retry requested."

    with pytest.raises(ValueError, match="RUN_RETRY_STATUS_NOT_RETRYABLE: queued"):
        RunExecutionStateMachine.request_retry(current_status="queued", state_version=1)


def test_dead_letter_transition_matches_reconciler_contract() -> None:
    transition = RunExecutionStateMachine.dead_letter_job(
        current_status="running",
        state_version=6,
    )

    assert transition.event_type == "run_job_dead_lettered"
    assert transition.from_status == "running"
    assert transition.to_status == "failed"
    assert transition.stage == "dead_letter"
    assert transition.state_version == 7
    assert transition.row_message == "Job dead-lettered after max retries."
    assert transition.event_message == "Run job dead-lettered after exhausting retries."


@pytest.mark.parametrize(
    ("attempt_state", "canonical_attempt_state", "job_state", "lease_state"),
    [
        ("succeeded", "succeeded", "completed", "completed"),
        ("failed", "failed", "failed", "failed"),
        ("canceled", "cancelled", "cancelled", "cancelled"),
        ("cancelled", "cancelled", "cancelled", "cancelled"),
    ],
)
def test_attempt_completion_decision_owns_terminal_job_and_lease_states(
    attempt_state: str,
    canonical_attempt_state: str,
    job_state: str,
    lease_state: str,
) -> None:
    decision = RunExecutionStateMachine.complete_attempt(state=attempt_state)

    assert decision.attempt_state == canonical_attempt_state
    assert decision.job_state == job_state
    assert decision.lease_state == lease_state
    assert decision.event_type == "run_attempt_completed"
    assert decision.stage == "complete"
    assert decision.event_message == "Run attempt completed."


def test_attempt_completion_rejects_unsupported_terminal_state() -> None:
    with pytest.raises(ValueError, match="ATTEMPT_TERMINAL_STATE_UNSUPPORTED: unknown"):
        RunExecutionStateMachine.complete_attempt(state="unknown")


@pytest.mark.parametrize(
    ("attempt_state", "lease_state"),
    [
        ("succeeded", "completed"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
        ("fenced", "fenced"),
        ("", "fenced"),
    ],
)
def test_non_running_attempt_lease_closure_uses_completion_decision(
    attempt_state: str,
    lease_state: str,
) -> None:
    assert RunExecutionStateMachine.lease_state_for_non_running_attempt(attempt_state) == lease_state


@pytest.mark.parametrize(
    ("run_status", "attempt_state"),
    [
        ("completed", "succeeded"),
        ("canceled", "cancelled"),
        ("cancelled", "cancelled"),
        ("failed", "failed"),
        ("running", "failed"),
    ],
)
def test_attempt_state_mapping_for_worker_completion(run_status: str, attempt_state: str) -> None:
    assert RunExecutionStateMachine.attempt_state_for_run_status(run_status) == attempt_state


@pytest.mark.parametrize(
    ("attempt_state", "job_state"),
    [
        ("succeeded", "completed"),
        ("canceled", "cancelled"),
        ("cancelled", "cancelled"),
        ("failed", "failed"),
    ],
)
def test_terminal_job_state_mapping_for_attempt_completion(attempt_state: str, job_state: str) -> None:
    assert RunExecutionStateMachine.terminal_job_state_for_attempt_state(attempt_state) == job_state


def test_terminal_job_state_mapping_rejects_unknown_attempt_state() -> None:
    with pytest.raises(ValueError, match="ATTEMPT_TERMINAL_STATE_UNSUPPORTED: unknown"):
        RunExecutionStateMachine.terminal_job_state_for_attempt_state("unknown")


def test_lease_and_published_attempt_terminal_sets_are_explicit() -> None:
    assert RunExecutionStateMachine.is_released_lease_state("expired") is True
    assert RunExecutionStateMachine.is_released_lease_state("active") is False
    assert RunExecutionStateMachine.is_published_attempt_terminal_state("succeeded") is True
    assert RunExecutionStateMachine.is_published_attempt_terminal_state("cancelled") is True
