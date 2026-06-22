from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest
from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_scheduler import run_workflow_trigger_scheduler_once
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_events_from_storage,
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


def test_cron_scheduler_due_tick_dispatches_once_and_records_lineage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="cron",
        trigger_spec={"cron": "0 2 * * *", "timezone": "UTC"},
    )

    first = run_workflow_trigger_scheduler_once(
        cfg,
        now="2026-06-23T02:00:39Z",
    )

    assert first["errors"] == []
    assert first["checked"] == 1
    assert first["due"] == 1
    assert first["submitted"] == 1
    assert first["replayed"] == 0
    event = first["events"][0]
    run_id = event["dispatch"]["runId"]
    expected_key = f"cron:{trigger['triggerId']}:2026-06-23T02:00:00Z"
    assert event["eventType"] == "cron"
    assert event["externalEventId"] == expected_key
    assert event["idempotencyKey"] == expected_key
    assert event["cursor"] == "2026-06-23T02:00:00Z"
    assert event["payload"]["scheduledAt"] == "2026-06-23T02:00:00Z"
    assert event["payload"]["schedule"] == {"cron": "0 2 * * *", "timezone": "UTC"}

    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": event["triggerEventId"],
        "source": "cron",
        "cursor": "2026-06-23T02:00:00Z",
    }

    replay = run_workflow_trigger_scheduler_once(
        cfg,
        now="2026-06-23T02:00:59Z",
    )

    assert replay["errors"] == []
    assert replay["due"] == 1
    assert replay["submitted"] == 0
    assert replay["replayed"] == 1
    assert replay["events"][0]["triggerEventId"] == event["triggerEventId"]
    assert replay["events"][0]["dispatch"]["runId"] == run_id

    later = run_workflow_trigger_scheduler_once(
        cfg,
        now="2026-06-23T02:01:00Z",
    )
    assert later["due"] == 0
    assert later["submitted"] == 0
    assert later["skipped"] == 1


def test_cron_scheduler_ignores_disabled_triggers_and_direct_submit_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="cron",
        trigger_spec={"cron": "0 2 * * *", "timezone": "UTC"},
        enabled=False,
    )

    result = run_workflow_trigger_scheduler_once(
        cfg,
        now="2026-06-23T02:00:00Z",
    )

    assert result["checked"] == 0
    assert result["events"] == []
    assert list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_DISABLED"):
        submit_workflow_trigger_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="cron",
                externalEventId=f"cron:{trigger['triggerId']}:2026-06-23T02:00:00Z",
                idempotencyKey=f"cron:{trigger['triggerId']}:2026-06-23T02:00:00Z",
                cursor="2026-06-23T02:00:00Z",
                payload={"scheduledAt": "2026-06-23T02:00:00Z"},
            ),
        )


def test_trigger_event_dedupe_key_rejects_different_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(cfg, source_type="cron", trigger_spec={"cron": "0 2 * * *", "timezone": "UTC"})
    request = WorkflowTriggerEventRequest(
        eventType="cron",
        externalEventId=f"cron:{trigger['triggerId']}:2026-06-23T02:00:00Z",
        idempotencyKey=f"cron:{trigger['triggerId']}:2026-06-23T02:00:00Z",
        cursor="2026-06-23T02:00:00Z",
        payload={"scheduledAt": "2026-06-23T02:00:00Z"},
    )
    submit_workflow_trigger_event_from_request(cfg, trigger["triggerId"], request)

    with pytest.raises(IdempotencyKeyReusedError, match="TRIGGER_EVENT_DEDUPE_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"):
        submit_workflow_trigger_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="cron",
                externalEventId=request.externalEventId,
                idempotencyKey=request.idempotencyKey,
                cursor=request.cursor,
                payload={"scheduledAt": "2026-06-23T02:00:00Z", "changed": True},
            ),
        )


@pytest.mark.parametrize("source_type", ["dataset", "file", "database_ready"])
def test_unsupported_ready_trigger_launch_fails_loudly_until_sensor_dispatch_exists(
    source_type: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match=f"WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: {source_type}"):
        create_workflow_trigger_from_request(
            cfg,
            WorkflowTriggerCreateRequest(
                name="Ready FASTQ summary",
                sourceType=source_type,
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


def _create_trigger(
    cfg,
    *,
    source_type: str,
    trigger_spec: dict[str, object],
    enabled: bool = True,
) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="FASTQ summary trigger",
            sourceType=source_type,
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec=trigger_spec,
            enabled=enabled,
        ),
        actor="pytest",
    )["data"]
