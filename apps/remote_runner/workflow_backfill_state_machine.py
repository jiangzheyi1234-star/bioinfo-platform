from __future__ import annotations

from typing import Any

from .run_execution_state_machine import RunExecutionStateMachine


BACKFILL_RUN_ORDERS = frozenset({"forward", "backward"})
ADVANCEABLE_LAUNCH_STATES = frozenset({"launching", "running", "submitted"})
BACKFILL_PARTITION_CANCELABLE_STATES = frozenset({"pending", "admitting", "submitted", "replayed"})
ADMITTING_PARTITION_STATES = frozenset({"admitting"})
PENDING_PARTITION_STATES = frozenset({"pending", "admitting"})


class WorkflowBackfillStateMachine:
    @staticmethod
    def initial_launch_state() -> str:
        return "launching"

    @staticmethod
    def canceling_launch_state() -> str:
        return "canceling"

    @staticmethod
    def advanceable_launch_states() -> tuple[str, ...]:
        return tuple(sorted(ADVANCEABLE_LAUNCH_STATES))

    @staticmethod
    def cancelable_partition_states() -> tuple[str, ...]:
        return tuple(sorted(BACKFILL_PARTITION_CANCELABLE_STATES))

    @staticmethod
    def submitted_partition_state(*, replayed: bool) -> str:
        return "replayed" if replayed else "submitted"

    @staticmethod
    def failed_partition_state() -> str:
        return "failed"

    @staticmethod
    def cancel_requested_partition_state() -> str:
        return "cancel_requested"

    @staticmethod
    def admitting_partition_state() -> str:
        return "admitting"

    @staticmethod
    def normalize_run_order(value: Any) -> str:
        run_order = str(value or "").strip().lower()
        if run_order not in BACKFILL_RUN_ORDERS:
            raise ValueError(f"WORKFLOW_BACKFILL_RUN_ORDER_UNSUPPORTED: {value}")
        return run_order

    @staticmethod
    def partition_order_direction(value: Any) -> str:
        if WorkflowBackfillStateMachine.normalize_run_order(value) == "backward":
            return "DESC"
        return "ASC"

    @staticmethod
    def is_launch_state_advanceable(state: str) -> bool:
        return _normalize(state) in ADVANCEABLE_LAUNCH_STATES

    @staticmethod
    def ensure_controller_advanceable(detail: dict[str, Any]) -> bool:
        state = _normalize(detail.get("state"))
        if state == WorkflowBackfillStateMachine.canceling_launch_state():
            return False
        if state not in ADVANCEABLE_LAUNCH_STATES:
            raise ValueError(f"WORKFLOW_BACKFILL_LAUNCH_STATE_NOT_ADVANCEABLE: {state}")
        summary = detail.get("partitionSummary") if isinstance(detail.get("partitionSummary"), dict) else {}
        expected = int(detail.get("partitionCount") or 0)
        actual = int(summary.get("partitionCount") or 0)
        if expected != actual:
            raise ValueError(f"WORKFLOW_BACKFILL_LAUNCH_INCOMPLETE: expected={expected} actual={actual}")
        return True

    @staticmethod
    def next_launch_state(summary: dict[str, Any]) -> str:
        pending = int(summary.get("pendingPartitionCount") or 0)
        return "running" if pending else "submitted"

    @staticmethod
    def can_request_cancel_without_run(partition_state: str) -> bool:
        return _normalize(partition_state) in PENDING_PARTITION_STATES

    @staticmethod
    def should_skip_run_cancel(status: str) -> bool:
        normalized = _normalize(status)
        return normalized == "canceling" or RunExecutionStateMachine.is_terminal_run_status(normalized)

    @staticmethod
    def partition_has_active_run(partition: dict[str, Any]) -> bool:
        run = partition.get("run") if isinstance(partition.get("run"), dict) else {}
        run_id = str((run or {}).get("runId") or partition.get("runId") or "").strip()
        status = _normalize((run or {}).get("status"))
        return bool(run_id and (not status or not RunExecutionStateMachine.is_terminal_run_status(status)))

    @staticmethod
    def partition_occupies_concurrency_slot(partition: dict[str, Any]) -> bool:
        state = _normalize(partition.get("state"))
        return state in ADMITTING_PARTITION_STATES or WorkflowBackfillStateMachine.partition_has_active_run(partition)

    @staticmethod
    def partition_has_cancellable_run(partition: dict[str, Any]) -> bool:
        run = partition.get("run") if isinstance(partition.get("run"), dict) else {}
        run_id = str((run or {}).get("runId") or partition.get("runId") or "").strip()
        status = _normalize((run or {}).get("status"))
        return bool(run_id and (not status or not WorkflowBackfillStateMachine.should_skip_run_cancel(status)))

    @staticmethod
    def partition_blocked_reason(state: str, error: Any) -> str | None:
        normalized = _normalize(state)
        if normalized == "pending":
            return "concurrency_limit"
        if normalized == "skipped" and isinstance(error, dict):
            return str(error.get("reason") or "skipped")
        return None


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()
