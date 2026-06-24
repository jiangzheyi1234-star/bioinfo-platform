from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
)
from apps.remote_runner.execution_query_storage import list_runs
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.trigger_scheduler import run_workflow_trigger_scheduler_once
from apps.remote_runner.trigger_service import (
    cancel_workflow_backfill_launch_from_request,
    create_workflow_trigger_from_request,
    get_workflow_backfill_launch_from_storage,
    launch_workflow_trigger_backfill_from_request,
    list_workflow_trigger_events_from_storage,
    preview_workflow_trigger_backfill_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_scheduler_advances_backfill_pending_partitions_with_concurrency_limit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    launched = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(cfg, trigger, range_end="2026-06-04"),
    )["data"]

    assert launched["state"] == "running"
    assert launched["launchedRunCount"] == 1
    assert launched["submittedThisTick"] == 1
    assert launched["pendingPartitionCount"] == 2
    assert [item["state"] for item in launched["partitions"]] == ["submitted", "pending", "pending"]
    assert launched["concurrency"]["blockedPartitionCount"] == 2
    assert len(list_runs(cfg)) == 1

    _mark_run_completed(cfg, launched["partitions"][0]["runId"])
    first_tick = run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:00:00Z")
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert first_tick["backfills"]["checked"] == 1
    assert first_tick["backfills"]["advanced"] == 1
    assert first_tick["backfills"]["submitted"] == 1
    assert first_tick["backfills"]["errors"] == []
    assert detail["state"] == "running"
    assert detail["partitionSummary"]["submittedRunCount"] == 2
    assert detail["partitionSummary"]["activeRunCount"] == 1
    assert detail["partitionSummary"]["blockedPartitionCount"] == 1
    assert [item["state"] for item in detail["partitions"]] == ["submitted", "submitted", "pending"]
    assert len(list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"]) == 2

    no_slot_tick = run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:01:00Z")
    assert no_slot_tick["backfills"]["checked"] == 1
    assert no_slot_tick["backfills"]["advanced"] == 0
    assert no_slot_tick["backfills"]["submitted"] == 0

    _mark_run_completed(cfg, detail["partitions"][1]["runId"])
    second_tick = run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:02:00Z")
    final_detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert second_tick["backfills"]["advanced"] == 1
    assert second_tick["backfills"]["submitted"] == 1
    assert final_detail["state"] == "submitted"
    assert final_detail["partitionSummary"]["submittedRunCount"] == 3
    assert final_detail["partitionSummary"]["pendingPartitionCount"] == 0
    assert final_detail["partitionSummary"]["blockedPartitionCount"] == 0
    assert [item["state"] for item in final_detail["partitions"]] == ["submitted", "submitted", "submitted"]


def test_backfill_cancel_marks_pending_partitions_and_blocks_future_admission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)
    launched = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(cfg, trigger, range_end="2026-06-04"),
    )["data"]

    canceled = cancel_workflow_backfill_launch_from_request(
        cfg,
        launched["launchId"],
        WorkflowBackfillCancelRequest(confirmation="cancel-backfill", actor="operator"),
    )["data"]
    tick = run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:00:00Z")
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert canceled["requestedCancelCount"] == 1
    assert canceled["pendingCancelRequestedCount"] == 2
    assert canceled["skippedPartitionCount"] == 0
    assert tick["backfills"]["checked"] == 0
    assert detail["state"] == "canceling"
    assert detail["partitionSummary"]["states"] == {"cancel_requested": 3}
    assert [item["runId"] for item in detail["partitions"]].count(None) == 2
    assert len(list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"]) == 1


def test_backfill_admission_respects_backward_run_order(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)
    launched = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(cfg, trigger, range_end="2026-06-04", run_order="backward"),
    )["data"]

    assert [item["partitionKey"] for item in launched["partitions"]] == [
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
    ]
    assert [item["state"] for item in launched["partitions"]] == ["pending", "pending", "submitted"]

    _mark_run_completed(cfg, launched["partitions"][2]["runId"])
    run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:00:00Z")
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert [item["state"] for item in detail["partitions"]] == ["pending", "submitted", "submitted"]
    assert detail["partitions"][1]["partitionKey"] == "2026-06-02"


def _create_backfill_trigger(cfg) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Backfill FASTQ summary",
            sourceType="backfill",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={"partitionUnit": "day"},
        ),
        actor="pytest",
    )["data"]


def _preview_request(*, range_end: str, run_order: str = "forward") -> WorkflowTriggerBackfillPreviewRequest:
    return WorkflowTriggerBackfillPreviewRequest(
        rangeStart="2026-06-01",
        rangeEnd=range_end,
        partitionUnit="day",
        timezone="UTC",
        maxPartitions=3,
        concurrencyLimit=1,
        runOrder=run_order,
        reprocessBehavior="none",
    )


def _launch_request(
    cfg,
    trigger: dict[str, object],
    *,
    range_end: str,
    run_order: str = "forward",
) -> WorkflowTriggerBackfillLaunchRequest:
    preview_request = _preview_request(range_end=range_end, run_order=run_order)
    preview = preview_workflow_trigger_backfill_from_request(
        cfg,
        str(trigger["triggerId"]),
        preview_request,
    )["data"]
    return WorkflowTriggerBackfillLaunchRequest(
        **preview_request.model_dump(),
        previewId=str(preview["previewId"]),
        confirmation="launch-backfill",
        actor="operator",
    )


def _mark_run_completed(cfg, run_id: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                message = 'Completed by test.',
                finished_at = '2026-06-23T10:00:00Z',
                last_updated_at = '2026-06-23T10:00:00Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = '2026-06-23T10:00:00Z' WHERE run_id = ?",
            (run_id,),
        )
        connection.commit()


def _disable_submission_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
