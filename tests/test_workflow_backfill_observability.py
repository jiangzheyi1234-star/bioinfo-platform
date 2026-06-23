from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerBackfillLaunchRequest, WorkflowTriggerCreateRequest
from apps.remote_runner.errors import RemoteRunnerNotFoundError
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    get_workflow_backfill_launch_from_storage,
    launch_workflow_trigger_backfill_from_request,
    list_workflow_backfill_launches_from_storage,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_backfill_launch_read_model_lists_partition_runs_and_replay_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = create_workflow_trigger_from_request(
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
    request = WorkflowTriggerBackfillLaunchRequest(
        rangeStart="2026-06-01",
        rangeEnd="2026-06-03",
        partitionUnit="day",
        timezone="UTC",
        maxPartitions=2,
        concurrencyLimit=1,
        runOrder="forward",
        reprocessBehavior="none",
        confirmation="launch-backfill",
        actor="operator",
    )

    launched = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)["data"]
    replayed = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)["data"]
    listed = list_workflow_backfill_launches_from_storage(cfg, trigger_id=trigger["triggerId"])["data"]
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert listed["schemaVersion"] == "workflow-backfill-launch-list.v1"
    assert [item["launchId"] for item in listed["items"]] == [launched["launchId"]]
    assert listed["items"][0]["partitionSummary"] == {
        "partitionCount": 2,
        "states": {"replayed": 2},
        "submittedRunCount": 2,
        "failedPartitionCount": 0,
        "pendingPartitionCount": 0,
        "replayedPartitionCount": 2,
    }
    assert detail["schemaVersion"] == "workflow-backfill-launch-detail.v1"
    assert detail["launchId"] == launched["launchId"] == replayed["launchId"]
    assert detail["launchStrategy"] == "one-run-per-partition"
    assert detail["concurrency"] == {"limit": 1, "partitionCount": 2, "enforced": False}
    assert detail["range"]["semantics"] == "half-open"
    assert [item["partitionKey"] for item in detail["partitions"]] == ["2026-06-01", "2026-06-02"]
    assert [item["state"] for item in detail["partitions"]] == ["replayed", "replayed"]
    assert [item["runId"] for item in detail["partitions"]] == [item["runId"] for item in launched["partitions"]]
    assert all(item["run"]["status"] == "queued" for item in detail["partitions"])
    assert all(item["run"]["stage"] == "submitted" for item in detail["partitions"])
    assert all(item["dispatch"]["state"] == "submitted" for item in detail["partitions"])
    assert all(item["triggerEventType"] == "backfill.partition" for item in detail["partitions"])
    assert all(item["runSpecHash"] for item in detail["partitions"])
    assert "runSpecPreview" not in str(detail)


def test_backfill_launch_detail_fails_closed_for_unknown_launch(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(RemoteRunnerNotFoundError, match="WORKFLOW_BACKFILL_LAUNCH_NOT_FOUND"):
        get_workflow_backfill_launch_from_storage(cfg, "bfl_missing")
