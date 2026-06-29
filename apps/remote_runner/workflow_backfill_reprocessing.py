from __future__ import annotations

from typing import Any

from .api_models import WorkflowTriggerBackfillPreviewRequest
from .config import RemoteRunnerConfig
from .run_execution_state_machine import RunExecutionStateMachine
from .workflow_backfill_planner import build_backfill_plan
from .workflow_backfill_storage import latest_workflow_backfill_partitions_by_window


ACTIVE_PARTITION_STATES = {"pending", "admitting", "submitted", "replayed", "cancel_requested"}
COMPLETED_RUN_STATUSES = {"completed"}
FAILED_RUN_STATUSES = {"failed"}


def build_backfill_plan_with_reprocessing_policy(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerBackfillPreviewRequest,
) -> dict[str, Any]:
    plan = build_backfill_plan(trigger=trigger, request=request)
    windows = [
        (str(partition["window"]["start"]), str(partition["window"]["end"]))
        for partition in plan.get("partitions", [])
        if isinstance(partition.get("window"), dict)
    ]
    existing = latest_workflow_backfill_partitions_by_window(
        cfg,
        trigger_id=str(trigger["triggerId"]),
        windows=windows,
    )
    return apply_backfill_reprocessing_policy(plan, existing_partitions=existing)


def backfill_partition_policy_metadata(partition: dict[str, Any]) -> dict[str, Any]:
    decision = partition.get("reprocessDecision") if isinstance(partition.get("reprocessDecision"), dict) else {}
    return {
        "action": str(partition.get("action") or "create"),
        "reason": str(partition.get("skipReason") or decision.get("reason") or "unspecified"),
        "existingState": partition.get("existingState"),
        "reprocessDecision": decision,
    }


def apply_backfill_reprocessing_policy(
    plan: dict[str, Any],
    *,
    existing_partitions: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    reprocess_behavior = str(plan.get("reprocessBehavior") or "none")
    preview_id = str(plan.get("previewId") or "")
    partitions = [
        _partition_with_policy(
            partition,
            existing=existing_partitions.get(_window_key(partition)),
            preview_id=preview_id,
            reprocess_behavior=reprocess_behavior,
        )
        for partition in plan.get("partitions", [])
    ]
    create_count = sum(1 for partition in partitions if partition["action"] == "create")
    skip_count = len(partitions) - create_count
    blocked_count = sum(
        1
        for partition in partitions
        if partition["action"] == "skip" and partition["reprocessDecision"]["reason"] == "existing-active-run"
    )
    return {
        **plan,
        "partitions": partitions,
        "returnedRunCount": len(partitions),
        "creationRunCount": create_count,
        "skippedRunCount": skip_count,
        "blockedActiveRunCount": blocked_count,
    }


def _partition_with_policy(
    partition: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    preview_id: str,
    reprocess_behavior: str,
) -> dict[str, Any]:
    logical_partition_id = str(partition["partitionId"])
    decision = _reprocess_decision(existing, reprocess_behavior=reprocess_behavior)
    updated = {
        **partition,
        "logicalPartitionId": logical_partition_id,
        "action": decision["action"],
        "existingState": decision["existingState"],
        "reprocessDecision": {
            "behavior": reprocess_behavior,
            "reason": decision["reason"],
        },
    }
    if decision["action"] == "create":
        if existing is not None:
            updated["partitionId"] = f"{logical_partition_id}:reprocess:{reprocess_behavior}:{preview_id}"
            updated["idempotencyKey"] = updated["partitionId"]
        return updated

    updated["partitionId"] = f"{logical_partition_id}:skip:{preview_id}"
    updated["idempotencyKey"] = updated["partitionId"]
    updated["skipReason"] = decision["reason"]
    return updated


def _reprocess_decision(existing: dict[str, Any] | None, *, reprocess_behavior: str) -> dict[str, Any]:
    if existing is None:
        return {"action": "create", "reason": "missing-run", "existingState": None}
    existing_state = _existing_state(existing)
    if _existing_is_active(existing_state):
        return {"action": "skip", "reason": "existing-active-run", "existingState": existing_state}
    if reprocess_behavior == "none":
        return {"action": "skip", "reason": "existing-run", "existingState": existing_state}
    if reprocess_behavior == "failed":
        if existing_state["runStatus"] in FAILED_RUN_STATUSES or existing_state["state"] == "failed":
            return {"action": "create", "reason": "existing-failed-run", "existingState": existing_state}
        return {"action": "skip", "reason": "existing-run-not-failed", "existingState": existing_state}
    if reprocess_behavior == "completed":
        if existing_state["runStatus"] in COMPLETED_RUN_STATUSES | FAILED_RUN_STATUSES:
            return {"action": "create", "reason": "existing-terminal-run", "existingState": existing_state}
        return {"action": "skip", "reason": "existing-run-not-completed-or-failed", "existingState": existing_state}
    raise ValueError(f"WORKFLOW_BACKFILL_REPROCESS_BEHAVIOR_UNSUPPORTED: {reprocess_behavior}")


def _existing_is_active(existing_state: dict[str, Any]) -> bool:
    run_status = str(existing_state.get("runStatus") or "").strip().lower()
    state = str(existing_state.get("state") or "").strip().lower()
    if run_status:
        return not RunExecutionStateMachine.is_terminal_run_status(run_status)
    return state in ACTIVE_PARTITION_STATES


def _existing_state(existing: dict[str, Any]) -> dict[str, Any]:
    run = existing.get("run") if isinstance(existing.get("run"), dict) else {}
    return {
        "partitionId": existing.get("partitionId"),
        "launchId": existing.get("launchId"),
        "partitionKey": existing.get("partitionKey"),
        "state": existing.get("state"),
        "runId": existing.get("runId"),
        "runStatus": run.get("status"),
        "runStage": run.get("stage"),
        "updatedAt": existing.get("updatedAt"),
    }


def _window_key(partition: dict[str, Any]) -> tuple[str, str]:
    window = partition.get("window") if isinstance(partition.get("window"), dict) else {}
    return str(window.get("start") or ""), str(window.get("end") or "")
