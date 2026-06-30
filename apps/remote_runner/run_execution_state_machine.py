from __future__ import annotations

from dataclasses import dataclass


TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "canceled", "cancelled"})
RETRYABLE_RUN_STATUSES = frozenset({"failed", "canceled", "cancelled"})
RELEASED_LEASE_STATES = frozenset({"expired", "fenced", "failed", "canceled", "cancelled"})
PUBLISHED_ATTEMPT_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
FENCE_ATTEMPT_REASONS = frozenset({"lease_expired", "attempt_timeout", "stale_generation"})


@dataclass(frozen=True)
class RunExecutionTransition:
    event_type: str
    from_status: str | None
    to_status: str
    stage: str
    state_version: int
    row_message: str
    event_message: str
    update_run: bool = True


@dataclass(frozen=True)
class RunAttemptCompletionDecision:
    attempt_state: str
    job_state: str
    lease_state: str
    event_type: str
    stage: str
    event_message: str


@dataclass(frozen=True)
class RunAttemptFenceDecision:
    reason: str
    attempt_state: str
    lease_state: str
    event_type: str
    stage: str
    event_message: str


class RunExecutionStateMachine:
    @staticmethod
    def submission_accepted() -> RunExecutionTransition:
        return RunExecutionTransition(
            event_type="accepted",
            from_status=None,
            to_status="queued",
            stage="submitted",
            state_version=1,
            row_message="Run accepted",
            event_message="Accepted for asynchronous execution",
        )

    @staticmethod
    def publish_status(
        *,
        current_status: str,
        state_version: int,
        status: str,
        stage: str,
        message: str,
    ) -> RunExecutionTransition:
        return RunExecutionTransition(
            event_type="status-transition",
            from_status=_normalize_optional_status(current_status),
            to_status=_normalize_required_status(status, "RUN_STATUS_REQUIRED"),
            stage=_normalize_required_text(stage, "RUN_STAGE_REQUIRED"),
            state_version=int(state_version) + 1,
            row_message=message,
            event_message=message,
        )

    @staticmethod
    def request_cancel(*, current_status: str, state_version: int) -> RunExecutionTransition:
        normalized_status = _normalize_required_status(current_status, "RUN_STATUS_REQUIRED")
        if normalized_status in TERMINAL_RUN_STATUSES:
            return RunExecutionTransition(
                event_type="run_cancel_requested",
                from_status=normalized_status,
                to_status=normalized_status,
                stage="cancel",
                state_version=int(state_version),
                row_message="Cancellation requested.",
                event_message="Run cancellation requested.",
                update_run=False,
            )
        return RunExecutionTransition(
            event_type="run_cancel_requested",
            from_status=normalized_status,
            to_status="canceling",
            stage="cancel",
            state_version=int(state_version) + 1,
            row_message="Cancellation requested.",
            event_message="Run cancellation requested.",
        )

    @staticmethod
    def request_retry(*, current_status: str, state_version: int) -> RunExecutionTransition:
        normalized_status = _normalize_required_status(current_status, "RUN_STATUS_REQUIRED")
        if normalized_status not in RETRYABLE_RUN_STATUSES:
            raise ValueError(f"RUN_RETRY_STATUS_NOT_RETRYABLE: {normalized_status}")
        return RunExecutionTransition(
            event_type="run_retry_requested",
            from_status=normalized_status,
            to_status="queued",
            stage="retry",
            state_version=int(state_version) + 1,
            row_message="Run retry requested.",
            event_message="Run retry requested.",
        )

    @staticmethod
    def dead_letter_job(*, current_status: str, state_version: int) -> RunExecutionTransition:
        return RunExecutionTransition(
            event_type="run_job_dead_lettered",
            from_status=_normalize_optional_status(current_status),
            to_status="failed",
            stage="dead_letter",
            state_version=int(state_version) + 1,
            row_message="Job dead-lettered after max retries.",
            event_message="Run job dead-lettered after exhausting retries.",
        )

    @staticmethod
    def complete_attempt(*, state: str) -> RunAttemptCompletionDecision:
        attempt_state = _normalize_required_status(state, "ATTEMPT_STATE_REQUIRED")
        if attempt_state == "succeeded":
            job_state = "completed"
        elif attempt_state == "failed":
            job_state = "failed"
        elif attempt_state in {"canceled", "cancelled"}:
            attempt_state = "cancelled"
            job_state = "cancelled"
        else:
            raise ValueError(f"ATTEMPT_TERMINAL_STATE_UNSUPPORTED: {attempt_state}")
        return RunAttemptCompletionDecision(
            attempt_state=attempt_state,
            job_state=job_state,
            lease_state=job_state,
            event_type="run_attempt_completed",
            stage="complete",
            event_message="Run attempt completed.",
        )

    @staticmethod
    def lease_state_for_non_running_attempt(state: str | None) -> str:
        normalized = _normalize_optional_status(state)
        if not normalized or normalized == "fenced":
            return "fenced"
        return RunExecutionStateMachine.complete_attempt(state=normalized).lease_state

    @staticmethod
    def fence_attempt(*, reason: str) -> RunAttemptFenceDecision:
        normalized_reason = _normalize_required_text(reason, "FENCE_REASON_REQUIRED").lower()
        if normalized_reason not in FENCE_ATTEMPT_REASONS:
            raise ValueError(f"FENCE_REASON_UNSUPPORTED: {normalized_reason}")
        return RunAttemptFenceDecision(
            reason=normalized_reason,
            attempt_state="fenced",
            lease_state="expired" if normalized_reason == "lease_expired" else "fenced",
            event_type="run_attempt_fenced",
            stage="fence",
            event_message="Run attempt fenced.",
        )

    @staticmethod
    def attempt_state_for_run_status(status: str) -> str:
        normalized = _normalize_optional_status(status)
        if normalized == "completed":
            return "succeeded"
        if normalized in {"canceled", "cancelled"}:
            return "cancelled"
        return "failed"

    @staticmethod
    def terminal_job_state_for_attempt_state(state: str) -> str:
        return RunExecutionStateMachine.complete_attempt(state=state).job_state

    @staticmethod
    def is_terminal_run_status(status: str) -> bool:
        return _normalize_optional_status(status) in TERMINAL_RUN_STATUSES

    @staticmethod
    def is_released_lease_state(state: str) -> bool:
        return _normalize_optional_status(state) in RELEASED_LEASE_STATES

    @staticmethod
    def is_published_attempt_terminal_state(state: str) -> bool:
        return _normalize_optional_status(state) in PUBLISHED_ATTEMPT_TERMINAL_STATES


def _normalize_required_status(value: str, error_code: str) -> str:
    normalized = _normalize_optional_status(value)
    if not normalized:
        raise ValueError(error_code)
    return normalized


def _normalize_required_text(value: str, error_code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error_code)
    return normalized


def _normalize_optional_status(value: str | None) -> str:
    return str(value or "").strip().lower()
