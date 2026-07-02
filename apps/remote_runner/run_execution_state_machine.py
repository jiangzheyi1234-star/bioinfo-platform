from __future__ import annotations

from dataclasses import dataclass


RUN_STATUSES = frozenset({"queued", "running", "canceling", "completed", "failed", "canceled", "cancelled"})
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


@dataclass(frozen=True)
class RunJobRequeueDecision:
    action: str
    reason: str
    job_state: str | None
    remaining_attempts: int
    wait_reason_json: str | None
    event_type: str | None
    stage: str | None
    event_message: str | None


@dataclass(frozen=True)
class RunJobRetryDecision:
    action: str
    reason: str
    job_state: str | None
    remaining_attempts: int
    wait_reason_json: str | None


@dataclass(frozen=True)
class RunJobClaimDecision:
    attempt_state: str
    lease_state: str
    job_state: str
    attempt_number: int
    lease_generation: int
    wait_reason_json: str
    event_type: str
    stage: str
    event_message: str
    event_payload_keys: tuple[str, ...]


@dataclass(frozen=True)
class RunAttemptLeaseGuardDecision:
    accepted: bool
    reason: str


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
        from_status = _normalize_run_status(current_status, "RUN_STATUS_REQUIRED")
        to_status = _normalize_run_status(status, "RUN_STATUS_REQUIRED")
        if from_status in TERMINAL_RUN_STATUSES and to_status != from_status:
            raise ValueError(f"RUN_STATUS_TERMINAL_IMMUTABLE: {from_status} -> {to_status}")
        return RunExecutionTransition(
            event_type="status-transition",
            from_status=from_status,
            to_status=to_status,
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
    def requeue_retryable_job(
        *,
        current_job_state: str,
        attempt_count: int,
        max_attempts: int,
        dead_lettered: bool = False,
        expected_source_state: str = "claimed",
    ) -> RunJobRequeueDecision:
        normalized_state = _normalize_required_status(current_job_state, "JOB_STATE_REQUIRED")
        normalized_expected = _normalize_required_status(expected_source_state, "JOB_SOURCE_STATE_REQUIRED")
        attempts = max(0, int(attempt_count))
        limit = max(0, int(max_attempts))
        remaining_attempts = max(0, limit - attempts)
        if dead_lettered:
            return RunJobRequeueDecision(
                action="reject",
                reason="already_dead_lettered",
                job_state=None,
                remaining_attempts=remaining_attempts,
                wait_reason_json=None,
                event_type=None,
                stage=None,
                event_message=None,
            )
        if normalized_state != normalized_expected:
            return RunJobRequeueDecision(
                action="reject",
                reason=f"unexpected_state: {normalized_state}",
                job_state=None,
                remaining_attempts=remaining_attempts,
                wait_reason_json=None,
                event_type=None,
                stage=None,
                event_message=None,
            )
        if remaining_attempts <= 0:
            return RunJobRequeueDecision(
                action="dead_letter",
                reason="max_attempts_exceeded",
                job_state="failed",
                remaining_attempts=0,
                wait_reason_json=None,
                event_type=None,
                stage=None,
                event_message=None,
            )
        return RunJobRequeueDecision(
            action="requeue",
            reason="retryable",
            job_state="queued",
            remaining_attempts=remaining_attempts,
            wait_reason_json="{}",
            event_type="run_job_requeued",
            stage="requeue",
            event_message="Run job re-queued for retry.",
        )

    @staticmethod
    def retry_job_for_operator_request(
        *,
        current_job_state: str,
        attempt_count: int,
        max_attempts: int,
        dead_lettered: bool = False,
    ) -> RunJobRetryDecision:
        normalized_state = _normalize_required_status(current_job_state, "JOB_STATE_REQUIRED")
        attempts = max(0, int(attempt_count))
        limit = max(0, int(max_attempts))
        remaining_attempts = max(0, limit - attempts)
        if dead_lettered or remaining_attempts <= 0:
            return RunJobRetryDecision(
                action="reject",
                reason="max_attempts_exhausted",
                job_state=None,
                remaining_attempts=remaining_attempts,
                wait_reason_json=None,
            )
        if normalized_state == "queued":
            return RunJobRetryDecision(
                action="reject",
                reason="already_queued",
                job_state=None,
                remaining_attempts=remaining_attempts,
                wait_reason_json=None,
            )
        if normalized_state == "claimed":
            return RunJobRetryDecision(
                action="reject",
                reason="job_claimed",
                job_state=None,
                remaining_attempts=remaining_attempts,
                wait_reason_json=None,
            )
        return RunJobRetryDecision(
            action="retry",
            reason="retryable",
            job_state="queued",
            remaining_attempts=remaining_attempts,
            wait_reason_json="{}",
        )

    @staticmethod
    def claim_job(
        *,
        current_job_state: str,
        attempt_count: int,
        current_lease_state: str | None = None,
        current_lease_generation: int | None = None,
    ) -> RunJobClaimDecision:
        normalized_state = _normalize_required_status(current_job_state, "JOB_STATE_REQUIRED")
        if normalized_state != "queued":
            raise RuntimeError(f"RUN_JOB_NOT_CLAIMABLE: {normalized_state}")
        lease_state = _normalize_optional_status(current_lease_state)
        if lease_state and lease_state not in RELEASED_LEASE_STATES:
            raise RuntimeError(f"RUN_JOB_LEASE_NOT_RELEASED: {lease_state}")
        attempt_number = max(0, int(attempt_count)) + 1
        lease_generation = 1 if current_lease_generation is None else int(current_lease_generation) + 1
        return RunJobClaimDecision(
            attempt_state="running",
            lease_state="active",
            job_state="claimed",
            attempt_number=attempt_number,
            lease_generation=lease_generation,
            wait_reason_json="{}",
            event_type="run_attempt_claimed",
            stage="claim",
            event_message="Run attempt claimed.",
            event_payload_keys=(
                "jobId",
                "attemptId",
                "leaseGeneration",
                "attemptNumber",
                "workerId",
                "sessionId",
                "slotId",
            ),
        )

    @staticmethod
    def current_lease_guard(
        *,
        attempt_id: str | None,
        lease_generation: int | None,
        current_attempt_id: str | None,
        current_lease_generation: int | None,
        current_lease_state: str | None,
        allow_missing_attempt_context: bool = False,
    ) -> RunAttemptLeaseGuardDecision:
        requested_attempt_id = str(attempt_id or "").strip()
        has_generation = lease_generation is not None
        has_attempt_context = bool(requested_attempt_id) or has_generation
        if not has_attempt_context:
            return RunAttemptLeaseGuardDecision(
                accepted=bool(allow_missing_attempt_context),
                reason="" if allow_missing_attempt_context else "stale_generation",
            )
        if not requested_attempt_id or not has_generation:
            return RunAttemptLeaseGuardDecision(accepted=False, reason="stale_generation")
        stored_attempt_id = str(current_attempt_id or "").strip()
        if not stored_attempt_id:
            return RunAttemptLeaseGuardDecision(accepted=False, reason="stale_generation")
        if _normalize_optional_status(current_lease_state) != "active":
            return RunAttemptLeaseGuardDecision(accepted=False, reason="stale_generation")
        if stored_attempt_id != requested_attempt_id:
            return RunAttemptLeaseGuardDecision(accepted=False, reason="stale_generation")
        try:
            generation_matches = int(current_lease_generation) == int(lease_generation)
        except (TypeError, ValueError):
            generation_matches = False
        if not generation_matches:
            return RunAttemptLeaseGuardDecision(accepted=False, reason="stale_generation")
        return RunAttemptLeaseGuardDecision(accepted=True, reason="")

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


def _normalize_run_status(value: str, error_code: str) -> str:
    normalized = _normalize_required_status(value, error_code)
    if normalized not in RUN_STATUSES:
        raise ValueError(f"RUN_STATUS_UNSUPPORTED: {normalized}")
    return normalized


def _normalize_required_text(value: str, error_code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(error_code)
    return normalized


def _normalize_optional_status(value: str | None) -> str:
    return str(value or "").strip().lower()
