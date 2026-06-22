from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
)
from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.execution_query_storage import fetch_run, list_runs
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_scheduler import run_workflow_trigger_scheduler_once
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_events_from_storage,
    preview_workflow_trigger_backfill_from_request,
    submit_workflow_trigger_event_from_request,
    submit_workflow_trigger_inbox_event_from_request,
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


def test_webhook_inbox_event_dispatches_run_with_context_and_dedupes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="webhook",
        trigger_spec={"provider": "instrument-qc"},
    )
    request = WorkflowTriggerInboxEventRequest(
        eventType="dataset.ready",
        source="instrument-qc",
        eventId="evt_001",
        correlationId="batch_42",
        actor="instrument-agent",
        cursor="batch_42:evt_001",
        payload={"dataset": "reads.fastq"},
    )

    first = submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], request)
    event = first["data"]["event"]
    run_id = first["data"]["run"]["runId"]

    assert first["data"]["replayed"] is False
    assert event["sourceType"] == "webhook"
    assert event["eventType"] == "dataset.ready"
    assert event["externalEventId"] == "instrument-qc:evt_001"
    assert event["idempotencyKey"] == "webhook:instrument-qc:evt_001"
    assert event["cursor"] == "batch_42:evt_001"
    assert event["payload"] == {
        "eventContext": {
            "source": "instrument-qc",
            "eventId": "evt_001",
            "correlationId": "batch_42",
            "actor": "instrument-agent",
        },
        "payload": {"dataset": "reads.fastq"},
    }
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": event["triggerEventId"],
        "source": "webhook",
        "cursor": "batch_42:evt_001",
    }

    replay = submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], request)
    assert replay["data"]["replayed"] is True
    assert replay["data"]["event"]["triggerEventId"] == event["triggerEventId"]
    assert replay["data"]["run"]["runId"] == run_id

    dispatch_audit_events = list_governance_audit_events(cfg, action="workflow_trigger.dispatch")["items"]
    assert [item["actor"] for item in dispatch_audit_events] == ["instrument-agent", "instrument-agent"]
    assert [item["details"]["replayed"] for item in dispatch_audit_events] == [False, True]
    assert dispatch_audit_events[0]["details"]["eventContext"] == {
        "source": "instrument-qc",
        "eventId": "evt_001",
        "correlationId": "batch_42",
        "actor": "instrument-agent",
    }


@pytest.mark.parametrize(
    ("source_type", "trigger_spec"),
    [
        ("manual", {"mode": "manual"}),
        ("cron", {"cron": "0 2 * * *", "timezone": "UTC"}),
    ],
)
def test_webhook_inbox_rejects_non_webhook_trigger(
    source_type: str,
    trigger_spec: dict[str, object],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    trigger = _create_trigger(cfg, source_type=source_type, trigger_spec=trigger_spec)
    with pytest.raises(ValueError, match=f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {source_type}"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_001"),
        )


def test_webhook_inbox_rejects_missing_identity(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    webhook_trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            webhook_trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId=" "),
        )


def test_backfill_preview_returns_partition_plan_without_launching(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "day"},
        enabled=False,
    )

    response = preview_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerBackfillPreviewRequest(
            rangeStart="2026-06-01",
            rangeEnd="2026-06-04",
            partitionUnit="day",
            timezone="UTC",
            maxPartitions=2,
            concurrencyLimit=2,
            runOrder="forward",
            reprocessBehavior="none",
            params={"sampleBatch": "batch_42"},
        ),
    )

    data = response["data"]
    assert data["schemaVersion"] == "workflow-trigger-backfill-preview.v1"
    assert data["triggerId"] == trigger["triggerId"]
    assert data["sourceType"] == "backfill"
    assert data["triggerEnabled"] is False
    assert data["launchSupported"] is False
    assert data["reason"] == "BACKFILL_PREVIEW_ONLY"
    assert data["launchDisabledReason"] == "WORKFLOW_BACKFILL_LAUNCH_UNSUPPORTED_UNTIL_PROVENANCE_STABLE"
    assert data["range"] == {
        "start": "2026-06-01T00:00:00Z",
        "end": "2026-06-04T00:00:00Z",
        "timezone": "UTC",
        "partitionUnit": "day",
        "semantics": "half-open",
        "runOrder": "forward",
    }
    assert data["estimatedRunCount"] == 3
    assert data["returnedRunCount"] == 2
    assert data["truncated"] is True
    assert data["concurrency"] == {"limit": 2, "partitionCount": 3, "estimatedBatches": 2}

    first = data["partitions"][0]
    expected_identity = f"backfill:{trigger['triggerId']}:day:2026-06-01T00:00:00Z:2026-06-02T00:00:00Z"
    assert first["partitionId"] == expected_identity
    assert first["partitionKey"] == "2026-06-01"
    assert first["index"] == 0
    assert first["window"] == {
        "start": "2026-06-01T00:00:00Z",
        "end": "2026-06-02T00:00:00Z",
        "timezone": "UTC",
        "semantics": "half-open",
    }
    assert first["cursor"] == expected_identity
    assert first["idempotencyKey"] == expected_identity
    assert first["provenance"] == {
        "triggerId": trigger["triggerId"],
        "pipelineId": trigger["pipelineId"],
        "sourceType": "backfill",
        "partitionUnit": "day",
        "partitionKey": "2026-06-01",
    }
    assert first["runSpecPreview"]["params"]["sampleBatch"] == "batch_42"
    assert first["runSpecPreview"]["params"]["backfill"] == {
        "partitionKey": "2026-06-01",
        "windowStart": "2026-06-01T00:00:00Z",
        "windowEnd": "2026-06-02T00:00:00Z",
        "timezone": "UTC",
        "reprocessBehavior": "none",
    }
    assert list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []
    assert list_runs(cfg) == []

    preview_audit_events = list_governance_audit_events(
        cfg,
        subject_kind="workflow_trigger",
        subject_id=trigger["triggerId"],
        action="workflow_trigger.backfill_preview",
    )["items"]
    assert preview_audit_events[0]["details"]["estimatedRunCount"] == 3
    assert preview_audit_events[0]["details"]["launchSupported"] is False


def test_backfill_preview_supports_backward_hourly_windows(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "hour"},
        enabled=False,
    )

    response = preview_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerBackfillPreviewRequest(
            rangeStart="2026-06-01T00:00:00Z",
            rangeEnd="2026-06-01T03:00:00Z",
            partitionUnit="hour",
            timezone="UTC",
            maxPartitions=2,
            runOrder="backward",
        ),
    )

    assert [item["partitionKey"] for item in response["data"]["partitions"]] == [
        "2026-06-01T02",
        "2026-06-01T01",
    ]
    assert [item["index"] for item in response["data"]["partitions"]] == [2, 1]


def test_backfill_preview_rejects_wrong_source_and_invalid_range(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    manual_trigger = _create_trigger(cfg, source_type="manual", trigger_spec={"mode": "manual"})
    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_PREVIEW_SOURCE_MISMATCH: manual"):
        preview_workflow_trigger_backfill_from_request(
            cfg,
            manual_trigger["triggerId"],
            WorkflowTriggerBackfillPreviewRequest(rangeStart="2026-06-01", rangeEnd="2026-06-02"),
        )

    backfill_trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "day"},
        enabled=False,
    )
    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_RANGE_INVALID"):
        preview_workflow_trigger_backfill_from_request(
            cfg,
            backfill_trigger["triggerId"],
            WorkflowTriggerBackfillPreviewRequest(rangeStart="2026-06-02", rangeEnd="2026-06-01"),
        )


@pytest.mark.parametrize("source_type", ["dataset", "file", "database_ready", "backfill"])
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
