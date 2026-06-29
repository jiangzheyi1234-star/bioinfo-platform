from __future__ import annotations

import pytest

from apps.remote_runner.workflow_backfill_state_machine import WorkflowBackfillStateMachine


def test_backfill_run_order_contract_is_explicit() -> None:
    assert WorkflowBackfillStateMachine.normalize_run_order("forward") == "forward"
    assert WorkflowBackfillStateMachine.normalize_run_order(" Backward ") == "backward"
    assert WorkflowBackfillStateMachine.partition_order_direction("forward") == "ASC"
    assert WorkflowBackfillStateMachine.partition_order_direction("backward") == "DESC"

    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_RUN_ORDER_UNSUPPORTED: sideways"):
        WorkflowBackfillStateMachine.normalize_run_order("sideways")


def test_launch_advanceability_contract_matches_controller_behavior() -> None:
    running = {
        "state": "running",
        "partitionCount": 2,
        "partitionSummary": {"partitionCount": 2, "pendingPartitionCount": 1},
    }
    canceling = {
        "state": "canceling",
        "partitionCount": 2,
        "partitionSummary": {"partitionCount": 2},
    }
    incomplete = {
        "state": "running",
        "partitionCount": 2,
        "partitionSummary": {"partitionCount": 1},
    }

    assert WorkflowBackfillStateMachine.ensure_controller_advanceable(running) is True
    assert WorkflowBackfillStateMachine.ensure_controller_advanceable(canceling) is False
    assert WorkflowBackfillStateMachine.next_launch_state(running["partitionSummary"]) == "running"
    assert WorkflowBackfillStateMachine.next_launch_state({"pendingPartitionCount": 0}) == "submitted"

    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_LAUNCH_STATE_NOT_ADVANCEABLE: failed"):
        WorkflowBackfillStateMachine.ensure_controller_advanceable({"state": "failed"})
    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_LAUNCH_INCOMPLETE: expected=2 actual=1"):
        WorkflowBackfillStateMachine.ensure_controller_advanceable(incomplete)


def test_partition_state_transitions_and_cancel_guards_are_centralized() -> None:
    assert WorkflowBackfillStateMachine.initial_launch_state() == "launching"
    assert WorkflowBackfillStateMachine.canceling_launch_state() == "canceling"
    assert WorkflowBackfillStateMachine.submitted_partition_state(replayed=False) == "submitted"
    assert WorkflowBackfillStateMachine.submitted_partition_state(replayed=True) == "replayed"
    assert WorkflowBackfillStateMachine.failed_partition_state() == "failed"
    assert WorkflowBackfillStateMachine.cancel_requested_partition_state() == "cancel_requested"
    assert WorkflowBackfillStateMachine.can_request_cancel_without_run("pending") is True
    assert WorkflowBackfillStateMachine.can_request_cancel_without_run("admitting") is True
    assert WorkflowBackfillStateMachine.can_request_cancel_without_run("submitted") is False


@pytest.mark.parametrize(
    ("status", "skip"),
    [
        ("", False),
        ("queued", False),
        ("running", False),
        ("canceling", True),
        ("completed", True),
        ("failed", True),
        ("canceled", True),
        ("cancelled", True),
    ],
)
def test_run_cancel_skip_status_uses_run_execution_terminal_semantics(status: str, skip: bool) -> None:
    assert WorkflowBackfillStateMachine.should_skip_run_cancel(status) is skip


def test_partition_run_activity_and_concurrency_slot_rules() -> None:
    pending = {"state": "pending", "runId": None}
    admitting = {"state": "admitting", "runId": None}
    queued = {"state": "submitted", "run": {"runId": "run_a", "status": "queued"}}
    completed = {"state": "submitted", "run": {"runId": "run_b", "status": "completed"}}
    canceling = {"state": "cancel_requested", "run": {"runId": "run_c", "status": "canceling"}}

    assert WorkflowBackfillStateMachine.partition_has_active_run(pending) is False
    assert WorkflowBackfillStateMachine.partition_occupies_concurrency_slot(admitting) is True
    assert WorkflowBackfillStateMachine.partition_has_active_run(queued) is True
    assert WorkflowBackfillStateMachine.partition_occupies_concurrency_slot(queued) is True
    assert WorkflowBackfillStateMachine.partition_has_cancellable_run(queued) is True
    assert WorkflowBackfillStateMachine.partition_has_active_run(completed) is False
    assert WorkflowBackfillStateMachine.partition_occupies_concurrency_slot(completed) is False
    assert WorkflowBackfillStateMachine.partition_has_cancellable_run(completed) is False
    assert WorkflowBackfillStateMachine.partition_has_cancellable_run(canceling) is False


def test_partition_blocked_reason_is_public_and_stable() -> None:
    assert WorkflowBackfillStateMachine.partition_blocked_reason("pending", None) == "concurrency_limit"
    assert WorkflowBackfillStateMachine.partition_blocked_reason("skipped", {"reason": "existing_run"}) == "existing_run"
    assert WorkflowBackfillStateMachine.partition_blocked_reason("submitted", None) is None
