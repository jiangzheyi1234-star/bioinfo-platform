from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
)
from apps.remote_runner.errors import RemoteRunnerNotFoundError
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.trigger_service import (
    cancel_workflow_backfill_launch_from_request,
    create_workflow_trigger_from_request,
    get_workflow_backfill_launch_from_storage,
    launch_workflow_trigger_backfill_from_request,
    list_workflow_backfill_launches_from_storage,
    preview_workflow_trigger_backfill_from_request,
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
    request = _launch_request(cfg, trigger)

    launched = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)["data"]
    replayed = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)["data"]
    listed = list_workflow_backfill_launches_from_storage(cfg, trigger_id=trigger["triggerId"])["data"]
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert listed["schemaVersion"] == "workflow-backfill-launch-list.v1"
    assert [item["launchId"] for item in listed["items"]] == [launched["launchId"]]
    assert listed["items"][0]["partitionSummary"] == {
        "partitionCount": 2,
        "states": {"pending": 1, "submitted": 1},
        "submittedRunCount": 1,
        "activeRunCount": 1,
        "occupiedConcurrencySlotCount": 1,
        "admittingPartitionCount": 0,
        "blockedPartitionCount": 1,
        "failedPartitionCount": 0,
        "pendingPartitionCount": 1,
        "replayedPartitionCount": 0,
        "cancelRequestedPartitionCount": 0,
        "cancellableRunCount": 1,
    }
    assert detail["schemaVersion"] == "workflow-backfill-launch-detail.v1"
    assert detail["launchId"] == launched["launchId"] == replayed["launchId"]
    assert detail["launchStrategy"] == "one-run-per-partition"
    assert detail["concurrency"] == {
        "limit": 1,
        "partitionCount": 2,
        "enforced": True,
        "activeRunCount": 1,
        "occupiedSlotCount": 1,
        "availableSlots": 0,
        "pendingPartitionCount": 1,
        "blockedPartitionCount": 1,
        "admittingPartitionCount": 0,
    }
    assert detail["range"]["semantics"] == "half-open"
    assert [item["partitionKey"] for item in detail["partitions"]] == ["2026-06-01", "2026-06-02"]
    assert [item["state"] for item in detail["partitions"]] == ["submitted", "pending"]
    assert detail["partitions"][1]["blockedReason"] == "concurrency_limit"
    assert [item["runId"] for item in detail["partitions"]] == [item["runId"] for item in launched["partitions"]]
    assert detail["partitions"][0]["run"]["status"] == "queued"
    assert detail["partitions"][0]["run"]["stage"] == "submitted"
    detail_run = fetch_run(cfg, detail["partitions"][0]["runId"])
    assert detail["partitions"][0]["run"]["admission"] == _expected_admission_summary(detail_run)
    assert detail["partitions"][0]["dispatch"]["state"] == "submitted"
    assert detail["partitions"][0]["triggerEventType"] == "backfill.partition"
    assert detail["partitions"][1]["run"] is None
    assert detail["partitions"][1]["dispatch"] is None
    assert detail["partitions"][1]["triggerEventType"] is None
    assert all(item["runSpecHash"] for item in detail["partitions"])
    assert "runSpecPreview" not in str(detail)

    claim_now = str(detail_run["submittedAt"])
    claim = claim_next_run_job(
        cfg,
        worker_id="worker-limited",
        slot_id="slot-0",
        resource_request=ResourceRequest(memory_mb=8192),
        resource_capacity=ResourceRequest(memory_mb=1024),
        max_active_slots=1,
        now=claim_now,
    )
    waited = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]
    waited_admission = waited["partitions"][0]["run"]["admission"]
    assert claim is None
    assert waited_admission["waitReason"] == {
        "code": "ADMISSION_RESOURCES_UNAVAILABLE",
        "resource": "memory_mb",
        "available": 1024,
        "requested": 8192,
    }
    assert waited_admission["waitReasonCode"] == "ADMISSION_RESOURCES_UNAVAILABLE"
    assert waited_admission["updatedAt"] == claim_now


def test_backfill_launch_cancel_requests_active_partition_runs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    request = _launch_request(cfg, trigger)
    launched = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)["data"]

    response = cancel_workflow_backfill_launch_from_request(
        cfg,
        launched["launchId"],
        WorkflowBackfillCancelRequest(confirmation="cancel-backfill", actor="operator"),
    )["data"]
    detail = get_workflow_backfill_launch_from_storage(cfg, launched["launchId"])["data"]

    assert response["schemaVersion"] == "workflow-backfill-cancel.v1"
    assert response["launchId"] == launched["launchId"]
    assert response["state"] == "canceling"
    assert response["requestedCancelCount"] == 1
    assert response["pendingCancelRequestedCount"] == 1
    assert response["skippedPartitionCount"] == 0
    assert {item["previousRunStatus"] for item in response["requested"]} == {"queued"}
    assert {item["status"] for item in response["requested"]} == {"canceling"}
    assert {item["previousState"] for item in response["pendingRequested"]} == {"pending"}
    assert detail["state"] == "canceling"
    assert detail["partitionSummary"]["states"] == {"cancel_requested": 2}
    assert detail["partitionSummary"]["cancelRequestedPartitionCount"] == 2
    assert detail["partitionSummary"]["cancellableRunCount"] == 0
    assert detail["operationCapabilities"]["cancel"] is False
    active, pending = detail["partitions"]
    assert active["state"] == "cancel_requested"
    assert active["run"]["status"] == "canceling"
    assert active["run"]["stage"] == "cancel"
    assert fetch_run(cfg, active["runId"])["status"] == "canceling"
    assert pending["state"] == "cancel_requested"
    assert pending["run"] is None

    backfill_audit = list_governance_audit_events(cfg, action="workflow_trigger.backfill_cancel")["items"]
    run_cancel_audit = list_governance_audit_events(cfg, action="run.cancel")["items"]
    assert backfill_audit[-1]["details"]["requestedCancelCount"] == 1
    assert backfill_audit[-1]["details"]["pendingCancelRequestedCount"] == 1
    assert backfill_audit[-1]["details"]["skippedPartitionCount"] == 0
    assert {item["subjectId"] for item in run_cancel_audit} == {active["runId"]}


def test_backfill_launch_detail_fails_closed_for_unknown_launch(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(RemoteRunnerNotFoundError, match="WORKFLOW_BACKFILL_LAUNCH_NOT_FOUND"):
        get_workflow_backfill_launch_from_storage(cfg, "bfl_missing")


def _launch_request(cfg, trigger: dict[str, object]) -> WorkflowTriggerBackfillLaunchRequest:
    preview_request = WorkflowTriggerBackfillPreviewRequest(
        rangeStart="2026-06-01",
        rangeEnd="2026-06-03",
        partitionUnit="day",
        timezone="UTC",
        maxPartitions=2,
        concurrencyLimit=1,
        runOrder="forward",
        reprocessBehavior="none",
    )
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


def _expected_admission_summary(run: dict[str, object] | None) -> dict[str, object]:
    assert run is not None
    return {
        "schemaVersion": "run-admission-summary.v1",
        "jobState": "queued",
        "queueName": "default",
        "availableAt": run["submittedAt"],
        "attemptCount": 0,
        "maxAttempts": 3,
        "waitReasonCode": "",
        "waitReason": None,
        "deadLetteredAt": None,
        "updatedAt": run["submittedAt"],
    }
