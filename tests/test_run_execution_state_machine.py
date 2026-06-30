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
    ("reason", "stored_reason", "lease_state"),
    [
        ("lease_expired", "lease_expired", "expired"),
        ("attempt_timeout", "attempt_timeout", "fenced"),
        ("stale_generation", "stale_generation", "fenced"),
        ("STALE_GENERATION", "stale_generation", "fenced"),
    ],
)
def test_attempt_fence_decision_owns_attempt_lease_and_event_shape(
    reason: str,
    stored_reason: str,
    lease_state: str,
) -> None:
    decision = RunExecutionStateMachine.fence_attempt(reason=reason)

    assert decision.reason == stored_reason
    assert decision.attempt_state == "fenced"
    assert decision.lease_state == lease_state
    assert decision.event_type == "run_attempt_fenced"
    assert decision.stage == "fence"
    assert decision.event_message == "Run attempt fenced."


def test_attempt_fence_decision_rejects_missing_reason() -> None:
    with pytest.raises(ValueError, match="FENCE_REASON_REQUIRED"):
        RunExecutionStateMachine.fence_attempt(reason="")


def test_attempt_fence_decision_rejects_unsupported_reason() -> None:
    with pytest.raises(ValueError, match="FENCE_REASON_UNSUPPORTED: worker_lost"):
        RunExecutionStateMachine.fence_attempt(reason="worker_lost")


def test_job_requeue_decision_owns_recovery_event_shape() -> None:
    decision = RunExecutionStateMachine.requeue_retryable_job(
        current_job_state="claimed",
        attempt_count=1,
        max_attempts=3,
    )

    assert decision.action == "requeue"
    assert decision.reason == "retryable"
    assert decision.job_state == "queued"
    assert decision.remaining_attempts == 2
    assert decision.wait_reason_json == "{}"
    assert decision.event_type == "run_job_requeued"
    assert decision.stage == "requeue"
    assert decision.event_message == "Run job re-queued for retry."


def test_job_requeue_decision_rejects_unclaimed_or_exhausted_jobs() -> None:
    unexpected = RunExecutionStateMachine.requeue_retryable_job(
        current_job_state="failed",
        attempt_count=1,
        max_attempts=3,
    )
    exhausted = RunExecutionStateMachine.requeue_retryable_job(
        current_job_state="claimed",
        attempt_count=3,
        max_attempts=3,
    )

    assert unexpected.action == "reject"
    assert unexpected.reason == "unexpected_state: failed"
    assert unexpected.job_state is None
    assert unexpected.remaining_attempts == 2
    assert unexpected.wait_reason_json is None

    assert exhausted.action == "dead_letter"
    assert exhausted.reason == "max_attempts_exceeded"
    assert exhausted.job_state == "failed"
    assert exhausted.remaining_attempts == 0
    assert exhausted.event_type is None


def test_operator_retry_job_decision_is_distinct_from_recovery_requeue_event() -> None:
    retry = RunExecutionStateMachine.retry_job_for_operator_request(
        current_job_state="failed",
        attempt_count=1,
        max_attempts=3,
    )
    already_queued = RunExecutionStateMachine.retry_job_for_operator_request(
        current_job_state="queued",
        attempt_count=1,
        max_attempts=3,
    )
    claimed = RunExecutionStateMachine.retry_job_for_operator_request(
        current_job_state="claimed",
        attempt_count=1,
        max_attempts=3,
    )

    assert retry.action == "retry"
    assert retry.reason == "retryable"
    assert retry.job_state == "queued"
    assert retry.remaining_attempts == 2
    assert retry.wait_reason_json == "{}"

    assert already_queued.action == "reject"
    assert already_queued.reason == "already_queued"
    assert claimed.action == "reject"
    assert claimed.reason == "job_claimed"


def test_job_claim_decision_owns_attempt_job_lease_and_event_shape() -> None:
    decision = RunExecutionStateMachine.claim_job(
        current_job_state="queued",
        attempt_count=0,
    )

    assert decision.attempt_state == "running"
    assert decision.lease_state == "active"
    assert decision.job_state == "claimed"
    assert decision.attempt_number == 1
    assert decision.lease_generation == 1
    assert decision.wait_reason_json == "{}"
    assert decision.event_type == "run_attempt_claimed"
    assert decision.stage == "claim"
    assert decision.event_message == "Run attempt claimed."
    assert decision.event_payload_keys == (
        "jobId",
        "attemptId",
        "leaseGeneration",
        "attemptNumber",
        "workerId",
        "sessionId",
        "slotId",
    )


@pytest.mark.parametrize("released_lease_state", [None, "expired", "fenced", "failed", "canceled", "cancelled"])
def test_job_claim_decision_allows_released_or_missing_lease(released_lease_state: str | None) -> None:
    decision = RunExecutionStateMachine.claim_job(
        current_job_state="queued",
        attempt_count=1,
        current_lease_state=released_lease_state,
        current_lease_generation=None if released_lease_state is None else 4,
    )

    assert decision.attempt_number == 2
    assert decision.lease_generation == (1 if released_lease_state is None else 5)


@pytest.mark.parametrize("lease_state", ["active", "completed"])
def test_job_claim_decision_rejects_unreleased_lease(lease_state: str) -> None:
    with pytest.raises(RuntimeError, match=f"RUN_JOB_LEASE_NOT_RELEASED: {lease_state}"):
        RunExecutionStateMachine.claim_job(
            current_job_state="queued",
            attempt_count=1,
            current_lease_state=lease_state,
            current_lease_generation=3,
        )


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
