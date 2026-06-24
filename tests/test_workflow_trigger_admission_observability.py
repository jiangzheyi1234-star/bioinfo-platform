from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_events_from_storage,
    submit_workflow_trigger_event_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_trigger_dispatch_read_model_exposes_allowlisted_admission_wait(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Manual FASTQ summary",
            sourceType="manual",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={"mode": "manual"},
        ),
        actor="pytest",
    )["data"]
    response = submit_workflow_trigger_event_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerEventRequest(
            eventType="manual",
            externalEventId="evt_reads_ready",
            idempotencyKey="manual:reads-ready",
            cursor="ready:reads.fastq",
        ),
    )
    run = fetch_run(cfg, response["data"]["run"]["runId"])
    assert run is not None

    claim = claim_next_run_job(
        cfg,
        worker_id="worker-limited",
        slot_id="slot-0",
        resource_request=ResourceRequest(cpu=8),
        resource_capacity=ResourceRequest(cpu=1),
        max_active_slots=1,
        now=str(run["submittedAt"]),
    )
    waited_events = list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"]
    admission = waited_events[0]["dispatch"]["run"]["admission"]

    assert claim is None
    assert admission["schemaVersion"] == "run-admission-summary.v1"
    assert admission["jobState"] == "queued"
    assert admission["queueName"] == "default"
    assert admission["availableAt"] == run["submittedAt"]
    assert admission["attemptCount"] == 0
    assert admission["maxAttempts"] == 3
    assert admission["waitReasonCode"] == "ADMISSION_RESOURCES_UNAVAILABLE"
    assert admission["waitReason"] == {
        "code": "ADMISSION_RESOURCES_UNAVAILABLE",
        "resource": "cpu",
        "available": 1,
        "requested": 8,
    }
    assert admission["updatedAt"] == run["submittedAt"]
