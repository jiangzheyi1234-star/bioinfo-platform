from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    submit_workflow_trigger_event_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_workflow_trigger_event_dispatches_run_and_records_lineage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            payload={"dataset": "reads.fastq"},
        ),
    )

    run_id = response["data"]["run"]["runId"]
    run = fetch_run(cfg, run_id)

    assert response["location"] == f"/api/v1/runs/{run_id}"
    assert response["data"]["event"]["dispatch"]["state"] == "submitted"
    assert response["data"]["event"]["dispatch"]["runId"] == run_id
    assert run is not None
    assert run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": response["data"]["event"]["triggerEventId"],
        "source": "manual",
        "cursor": "ready:reads.fastq",
    }

    replay = submit_workflow_trigger_event_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerEventRequest(
            eventType="manual",
            externalEventId="evt_reads_ready",
            idempotencyKey="manual:reads-ready",
            cursor="ready:reads.fastq",
            payload={"dataset": "reads.fastq"},
        ),
    )
    assert replay["data"]["replayed"] is True
    assert replay["data"]["run"]["runId"] == run_id
    create_audit_events = list_governance_audit_events(
        cfg,
        subject_kind="workflow_trigger",
        subject_id=trigger["triggerId"],
        action="workflow_trigger.create",
    )["items"]
    dispatch_audit_events = list_governance_audit_events(
        cfg,
        action="workflow_trigger.dispatch",
    )["items"]
    assert create_audit_events[0]["actor"] == "pytest"
    assert create_audit_events[0]["details"]["sourceType"] == "manual"
    assert [item["details"]["replayed"] for item in dispatch_audit_events] == [False, True]
    assert {item["details"]["runId"] for item in dispatch_audit_events} == {run_id}


def test_dataset_trigger_launch_fails_loudly_until_sensor_dispatch_exists(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: dataset"):
        create_workflow_trigger_from_request(
            cfg,
            WorkflowTriggerCreateRequest(
                name="Dataset-ready FASTQ summary",
                sourceType="dataset",
                serverId="srv_primary",
                runSpec={
                    "pipelineId": "file-summary-standard-v1",
                    "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
                },
                triggerSpec={"assetKey": "reads.fastq"},
                enabled=True,
            ),
            actor="pytest",
        )
