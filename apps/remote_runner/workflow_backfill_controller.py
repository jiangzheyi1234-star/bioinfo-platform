from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import RemoteRunnerConfig
from .workflow_backfill_storage import (
    ADVANCEABLE_LAUNCH_STATES,
    claim_workflow_backfill_partitions_for_admission,
    list_workflow_backfill_advanceable_launch_ids,
    mark_workflow_backfill_launch_finished,
    mark_workflow_backfill_partition_failed,
    require_workflow_backfill_launch,
)
from .trigger_storage import require_workflow_trigger


BackfillPartitionDispatcher = Callable[[RemoteRunnerConfig, dict[str, Any], dict[str, Any], str], bool]


def advance_workflow_backfill_launches(
    cfg: RemoteRunnerConfig,
    *,
    dispatch_partition: BackfillPartitionDispatcher,
    limit: int = 100,
) -> dict[str, Any]:
    checked = 0
    advanced = 0
    submitted = 0
    replayed = 0
    pending = 0
    launches: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for launch_id in list_workflow_backfill_advanceable_launch_ids(cfg, limit=limit):
        checked += 1
        try:
            result = advance_workflow_backfill_launch(
                cfg,
                launch_id,
                dispatch_partition=dispatch_partition,
            )
        except Exception as exc:  # noqa: BLE001 - one broken launch must not stop other launches.
            errors.append({"launchId": launch_id, "errorType": exc.__class__.__name__, "message": str(exc)})
            continue
        launches.append(result)
        submitted += int(result.get("submittedThisTick") or 0)
        replayed += int(result.get("replayedRunCount") or 0)
        pending += int(result.get("pendingPartitionCount") or 0)
        if int(result.get("submittedThisTick") or 0) > 0:
            advanced += 1
    return {
        "checked": checked,
        "advanced": advanced,
        "submitted": submitted,
        "replayed": replayed,
        "pending": pending,
        "launches": launches,
        "errors": errors,
    }


def advance_workflow_backfill_launch(
    cfg: RemoteRunnerConfig,
    launch_id: str,
    *,
    dispatch_partition: BackfillPartitionDispatcher,
) -> dict[str, Any]:
    launch = require_workflow_backfill_launch(cfg, launch_id)
    if not _ensure_backfill_launch_advanceable(launch):
        return _backfill_advance_result(launch, submitted_this_tick=0, replayed_run_count=0)
    trigger = require_workflow_trigger(cfg, str(launch["triggerId"]))
    actor = str(launch.get("actor") or "remote-runner-api")
    advanced = advance_backfill_partitions(
        cfg,
        trigger=trigger,
        launch_id=launch_id,
        actor=actor,
        requested_limit=int(launch.get("concurrency", {}).get("limit") or 1),
        dispatch_partition=dispatch_partition,
    )
    detail = require_workflow_backfill_launch(cfg, launch_id)
    return _backfill_advance_result(
        detail,
        submitted_this_tick=advanced["submittedThisTick"],
        replayed_run_count=advanced["replayedRunCount"],
    )


def advance_backfill_partitions(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    launch_id: str,
    actor: str,
    requested_limit: int,
    dispatch_partition: BackfillPartitionDispatcher,
    plan_partitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail = require_workflow_backfill_launch(cfg, launch_id)
    if not _ensure_backfill_launch_advanceable(detail):
        return {"submittedThisTick": 0, "replayedRunCount": 0}
    summary = detail.get("partitionSummary") if isinstance(detail.get("partitionSummary"), dict) else {}
    occupied = int(summary.get("occupiedConcurrencySlotCount") or 0)
    available = max(0, int(requested_limit or 1) - occupied)
    if available <= 0:
        _mark_backfill_launch_state_from_detail(cfg, detail)
        return {"submittedThisTick": 0, "replayedRunCount": 0}
    submitted_this_tick = 0
    replayed_count = 0
    for _ in range(available):
        pending = claim_workflow_backfill_partitions_for_admission(cfg, launch_id=launch_id, limit=1)
        if not pending:
            break
        partition_record = pending[0]
        partition = (plan_partitions or {}).get(str(partition_record["partitionId"])) or partition_record
        try:
            replayed = dispatch_partition(cfg, trigger, partition, actor)
        except Exception as exc:
            mark_workflow_backfill_partition_failed(
                cfg,
                partition_id=str(partition["partitionId"]),
                error={"errorType": exc.__class__.__name__, "message": str(exc)},
            )
            mark_workflow_backfill_launch_finished(cfg, launch_id=launch_id, state="failed")
            raise
        submitted_this_tick += 1
        if replayed:
            replayed_count += 1
    _mark_backfill_launch_state_from_detail(cfg, require_workflow_backfill_launch(cfg, launch_id))
    return {"submittedThisTick": submitted_this_tick, "replayedRunCount": replayed_count}


def _mark_backfill_launch_state_from_detail(cfg: RemoteRunnerConfig, detail: dict[str, Any]) -> None:
    if str(detail.get("state") or "") not in ADVANCEABLE_LAUNCH_STATES:
        return
    summary = detail.get("partitionSummary") if isinstance(detail.get("partitionSummary"), dict) else {}
    pending = int(summary.get("pendingPartitionCount") or 0)
    state = "running" if pending else "submitted"
    if str(detail.get("state") or "") != state:
        mark_workflow_backfill_launch_finished(cfg, launch_id=str(detail["launchId"]), state=state)


def _ensure_backfill_launch_advanceable(detail: dict[str, Any]) -> bool:
    state = str(detail.get("state") or "")
    if state == "canceling":
        return False
    if state not in ADVANCEABLE_LAUNCH_STATES:
        raise ValueError(f"WORKFLOW_BACKFILL_LAUNCH_STATE_NOT_ADVANCEABLE: {state}")
    summary = detail.get("partitionSummary") if isinstance(detail.get("partitionSummary"), dict) else {}
    expected = int(detail.get("partitionCount") or 0)
    actual = int(summary.get("partitionCount") or 0)
    if expected != actual:
        raise ValueError(f"WORKFLOW_BACKFILL_LAUNCH_INCOMPLETE: expected={expected} actual={actual}")
    return True


def _backfill_advance_result(
    detail: dict[str, Any],
    *,
    submitted_this_tick: int,
    replayed_run_count: int,
) -> dict[str, Any]:
    summary = detail.get("partitionSummary") if isinstance(detail.get("partitionSummary"), dict) else {}
    return {
        "schemaVersion": "workflow-backfill-advance.v1",
        "launchId": detail["launchId"],
        "triggerId": detail["triggerId"],
        "state": detail["state"],
        "concurrency": detail.get("concurrency"),
        "submittedThisTick": submitted_this_tick,
        "submittedRunCount": int(summary.get("submittedRunCount") or 0),
        "pendingPartitionCount": int(summary.get("pendingPartitionCount") or 0),
        "activeRunCount": int(summary.get("activeRunCount") or 0),
        "replayedRunCount": replayed_run_count,
    }
