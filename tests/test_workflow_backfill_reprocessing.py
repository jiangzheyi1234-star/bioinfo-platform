from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerBackfillLaunchRequest, WorkflowTriggerCreateRequest
from apps.remote_runner.execution_query_storage import list_runs
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    launch_workflow_trigger_backfill_from_request,
    preview_workflow_trigger_backfill_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_backfill_failed_reprocessing_creates_new_run_only_for_failed_partition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    first = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="none"),
    )["data"]
    _mark_run_status(cfg, first["partitions"][0]["runId"], status="failed", stage="failed")

    preview = preview_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="failed"),
    )["data"]
    relaunched = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="failed"),
    )["data"]

    assert preview["partitions"][0]["action"] == "create"
    assert preview["partitions"][0]["existingState"]["runStatus"] == "failed"
    assert preview["partitions"][0]["reprocessDecision"]["reason"] == "existing-failed-run"
    assert ":reprocess:failed:" in relaunched["partitions"][0]["partitionId"]
    assert relaunched["launchedRunCount"] == 1
    assert relaunched["submittedThisTick"] == 1
    assert relaunched["partitions"][0]["state"] == "submitted"
    assert len(list_runs(cfg)) == 2


def test_backfill_none_reprocessing_skips_existing_completed_partition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    first = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="completed"),
    )["data"]
    _mark_run_status(cfg, first["partitions"][0]["runId"], status="completed", stage="complete")

    skipped = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="none"),
    )["data"]

    assert skipped["state"] == "submitted"
    assert skipped["launchedRunCount"] == 0
    assert skipped["submittedThisTick"] == 0
    assert skipped["pendingPartitionCount"] == 0
    assert skipped["partitions"][0]["action"] == "skip"
    assert skipped["partitions"][0]["state"] == "skipped"
    assert skipped["partitions"][0]["blockedReason"] == "existing-run"
    assert skipped["partitions"][0]["existingState"]["runStatus"] == "completed"
    assert len(list_runs(cfg)) == 1


def test_backfill_completed_reprocessing_creates_new_run_for_completed_partition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    first = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="none"),
    )["data"]
    _mark_run_status(cfg, first["partitions"][0]["runId"], status="completed", stage="complete")

    relaunched = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="completed"),
    )["data"]

    assert relaunched["partitions"][0]["action"] == "create"
    assert relaunched["partitions"][0]["reprocessDecision"]["reason"] == "existing-terminal-run"
    assert relaunched["partitions"][0]["existingState"]["runStatus"] == "completed"
    assert ":reprocess:completed:" in relaunched["partitions"][0]["partitionId"]
    assert len(list_runs(cfg)) == 2


def test_backfill_failed_reprocessing_skips_completed_partition(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    first = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="none"),
    )["data"]
    _mark_run_status(cfg, first["partitions"][0]["runId"], status="completed", stage="complete")

    skipped = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="failed"),
    )["data"]

    assert skipped["partitions"][0]["action"] == "skip"
    assert skipped["partitions"][0]["blockedReason"] == "existing-run-not-failed"
    assert skipped["partitions"][0]["existingState"]["runStatus"] == "completed"
    assert len(list_runs(cfg)) == 1


def test_backfill_reprocessing_never_duplicates_active_partition_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _disable_submission_guards(monkeypatch)
    trigger = _create_backfill_trigger(cfg)

    launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="none"),
    )
    blocked = launch_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        _launch_request(reprocess_behavior="completed"),
    )["data"]

    assert blocked["launchedRunCount"] == 0
    assert blocked["partitions"][0]["action"] == "skip"
    assert blocked["partitions"][0]["blockedReason"] == "existing-active-run"
    assert blocked["partitions"][0]["existingState"]["runStatus"] == "queued"
    assert len(list_runs(cfg)) == 1


def _create_backfill_trigger(cfg):
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


def _launch_request(*, reprocess_behavior: str) -> WorkflowTriggerBackfillLaunchRequest:
    return WorkflowTriggerBackfillLaunchRequest(
        rangeStart="2026-06-01",
        rangeEnd="2026-06-02",
        partitionUnit="day",
        timezone="UTC",
        maxPartitions=1,
        concurrencyLimit=1,
        runOrder="forward",
        reprocessBehavior=reprocess_behavior,
        confirmation="launch-backfill",
        actor="operator",
    )


def _mark_run_status(cfg, run_id: str, *, status: str, stage: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = ?,
                stage = ?,
                message = 'Updated by backfill reprocessing test.',
                finished_at = '2026-06-23T10:00:00Z',
                last_updated_at = '2026-06-23T10:00:00Z'
            WHERE run_id = ?
            """,
            (status, stage, run_id),
        )
        connection.execute(
            "UPDATE run_jobs SET state = ?, updated_at = '2026-06-23T10:00:00Z' WHERE run_id = ?",
            (status, run_id),
        )
        connection.commit()


def _disable_submission_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
