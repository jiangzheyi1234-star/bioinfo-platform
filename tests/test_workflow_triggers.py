from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerReadinessEventRequest,
)
from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.execution_query_storage import fetch_run, list_runs
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_scheduler import run_workflow_trigger_scheduler_once
from apps.remote_runner.trigger_inbox_service import submit_workflow_trigger_inbox_event_from_request
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    launch_workflow_trigger_backfill_from_request,
    list_workflow_trigger_events_from_storage,
    preview_workflow_trigger_backfill_from_request,
    submit_workflow_trigger_event_from_request,
    submit_workflow_trigger_readiness_event_from_request,
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
    expected_run_summary = response["data"]["event"]["dispatch"]["run"]
    assert expected_run_summary["runId"] == run_id
    assert expected_run_summary["status"] == run["status"]
    assert expected_run_summary["stage"] == run["stage"]
    assert run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": response["data"]["event"]["triggerEventId"],
        "source": "manual",
        "cursor": "ready:reads.fastq",
    }
    events = list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"]
    assert events[0]["dispatch"]["run"] == expected_run_summary

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
    assert replay["data"]["event"]["dispatch"]["run"] == expected_run_summary
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
    assert event["dispatch"]["run"]["runId"] == run_id
    assert event["dispatch"]["run"]["status"] == run["status"]
    assert event["dispatch"]["run"]["stage"] == run["stage"]
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
        trigger_spec=_webhook_trigger_spec(),
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
    assert [item["correlationId"] for item in dispatch_audit_events] == ["batch_42", "batch_42"]
    assert dispatch_audit_events[0]["details"]["eventContext"] == {
        "source": "instrument-qc",
        "eventId": "evt_001",
        "correlationId": "batch_42",
        "actor": "instrument-agent",
    }


def test_generic_trigger_event_route_rejects_webhook_trigger_without_inbox(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec=_webhook_trigger_spec())

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: webhook"):
        submit_workflow_trigger_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="dataset.ready",
                externalEventId="instrument-qc:evt_bypass",
                idempotencyKey="webhook:instrument-qc:evt_bypass",
                payload={"eventContext": {"source": "instrument-qc", "eventId": "evt_bypass"}},
            ),
        )

    assert list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []


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

    webhook_trigger = _create_trigger(cfg, source_type="webhook", trigger_spec=_webhook_trigger_spec())
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            webhook_trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId=" "),
        )


def test_webhook_trigger_creation_requires_event_match_policy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_REQUIRED"):
        _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})


@pytest.mark.parametrize(
    ("source_type", "resource_type", "resource_id", "resource_uri"),
    [
        ("dataset", "dataset", "dataset:reads", "s3://lab-bucket/reads.fastq"),
        ("file", "file", "file:/incoming/reads.fastq", "file:///incoming/reads.fastq"),
        ("database_ready", "database", "database:blast-nt", "s3://reference-dbs/blast/nt"),
    ],
)
def test_readiness_event_dispatches_run_with_resource_provenance_and_dedupes(
    source_type: str,
    resource_type: str,
    resource_id: str,
    resource_uri: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type=source_type,
        trigger_spec={
            "resource": {
                "type": resource_type,
                "id": resource_id,
                "uri": resource_uri,
            }
        },
    )
    request = WorkflowTriggerReadinessEventRequest(
        source="lakehouse",
        eventId="evt_dataset_ready_001",
        resourceType=resource_type,
        resourceId=resource_id,
        uri=resource_uri,
        version="2026-06-24",
        checksum="sha256:abc123",
        observedAt="2026-06-24T02:00:00Z",
        actor="lakehouse-agent",
        labels={"assay": "rna-seq"},
        payload={"partition": "2026-06-24"},
    )

    first = submit_workflow_trigger_readiness_event_from_request(cfg, trigger["triggerId"], request)
    event = first["data"]["event"]
    run_id = first["data"]["run"]["runId"]

    assert first["data"]["replayed"] is False
    assert event["sourceType"] == source_type
    assert event["eventType"] == f"{resource_type}.ready"
    assert event["externalEventId"] == f"lakehouse:{resource_id}:evt_dataset_ready_001"
    assert event["idempotencyKey"] == f"readiness:{trigger['triggerId']}:lakehouse:{resource_id}:evt_dataset_ready_001"
    assert event["cursor"] == f"{resource_id}@2026-06-24"
    assert event["payload"] == {
        "eventContext": {
            "source": "lakehouse",
            "eventId": "evt_dataset_ready_001",
            "resourceType": resource_type,
            "resourceId": resource_id,
            "actor": "lakehouse-agent",
        },
        "resource": {
            "type": resource_type,
            "id": resource_id,
            "uri": resource_uri,
            "version": "2026-06-24",
            "checksum": "sha256:abc123",
            "labels": {"assay": "rna-seq"},
        },
        "state": "ready",
        "observedAt": "2026-06-24T02:00:00Z",
        "payload": {"partition": "2026-06-24"},
    }
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": event["triggerEventId"],
        "source": source_type,
        "cursor": f"{resource_id}@2026-06-24",
    }

    replay = submit_workflow_trigger_readiness_event_from_request(cfg, trigger["triggerId"], request)
    assert replay["data"]["replayed"] is True
    assert replay["data"]["event"]["triggerEventId"] == event["triggerEventId"]
    assert replay["data"]["run"]["runId"] == run_id

    dispatch_audit_events = list_governance_audit_events(cfg, action="workflow_trigger.dispatch")["items"]
    assert [item["actor"] for item in dispatch_audit_events] == ["lakehouse-agent", "lakehouse-agent"]
    assert dispatch_audit_events[0]["details"]["eventContext"] == {
        "source": "lakehouse",
        "eventId": "evt_dataset_ready_001",
        "actor": "lakehouse-agent",
        "resourceType": resource_type,
        "resourceId": resource_id,
    }


def test_readiness_event_keeps_generic_event_route_closed_for_resource_sources(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="file",
        trigger_spec={"resource": {"type": "file", "id": "file:/incoming/reads.fastq"}},
    )

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: file"):
        submit_workflow_trigger_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="file.ready",
                externalEventId="evt_file_ready",
                idempotencyKey="file:ready",
                cursor="file:/incoming/reads.fastq",
                payload={"resourceId": "file:/incoming/reads.fastq"},
            ),
        )


def test_readiness_event_rejects_wrong_source_and_resource(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    manual_trigger = _create_trigger(cfg, source_type="manual", trigger_spec={"mode": "manual"})
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_READINESS_SOURCE_MISMATCH: manual"):
        submit_workflow_trigger_readiness_event_from_request(
            cfg,
            manual_trigger["triggerId"],
            WorkflowTriggerReadinessEventRequest(
                source="lakehouse",
                eventId="evt_dataset_ready_001",
                resourceType="dataset",
                resourceId="dataset:reads",
            ),
        )

    file_trigger = _create_trigger(
        cfg,
        source_type="file",
        trigger_spec={"resource": {"type": "file", "id": "file:/incoming/reads.fastq"}},
    )
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_READINESS_RESOURCE_MISMATCH: file:/other.fastq"):
        submit_workflow_trigger_readiness_event_from_request(
            cfg,
            file_trigger["triggerId"],
            WorkflowTriggerReadinessEventRequest(
                source="watcher",
                eventId="evt_file_ready_001",
                resourceType="file",
                resourceId="file:/other.fastq",
            ),
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
    assert data["reason"] == "WORKFLOW_TRIGGER_DISABLED"
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


def test_backfill_launch_creates_partition_runs_and_replays(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "day"},
    )
    request = WorkflowTriggerBackfillLaunchRequest(
        rangeStart="2026-06-01",
        rangeEnd="2026-06-03",
        partitionUnit="day",
        timezone="UTC",
        maxPartitions=2,
        concurrencyLimit=1,
        runOrder="forward",
        reprocessBehavior="none",
        params={"sampleBatch": "batch_42"},
        confirmation="launch-backfill",
        actor="operator",
    )

    first = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)
    replay = launch_workflow_trigger_backfill_from_request(cfg, trigger["triggerId"], request)
    events = list_workflow_trigger_events_from_storage(cfg, trigger["triggerId"])["data"]["items"]
    runs = list_runs(cfg)

    data = first["data"]
    assert data["schemaVersion"] == "workflow-trigger-backfill-launch.v1"
    assert data["state"] == "running"
    assert data["launchedRunCount"] == 1
    assert data["submittedThisTick"] == 1
    assert data["pendingPartitionCount"] == 1
    assert data["replayedRunCount"] == 0
    assert len(data["partitions"]) == 2
    assert [item["partitionKey"] for item in data["partitions"]] == ["2026-06-01", "2026-06-02"]
    assert [item["state"] for item in data["partitions"]] == ["submitted", "pending"]
    assert data["partitions"][1]["blockedReason"] == "concurrency_limit"
    assert len({item["runId"] for item in data["partitions"] if item["runId"]}) == 1
    assert len(events) == 1
    assert len(runs) == 1
    assert all(item["dispatch"]["run"]["runId"] == item["dispatch"]["runId"] for item in events)
    assert {item["dispatch"]["run"]["status"] for item in events} == {"queued"}
    assert {item["dispatch"]["run"]["stage"] for item in events} == {"submitted"}

    first_partition = data["partitions"][0]
    first_run = fetch_run(cfg, first_partition["runId"])
    assert first_run is not None
    assert first_run["trigger"] == {
        "triggerId": trigger["triggerId"],
        "triggerEventId": first_partition["triggerEventId"],
        "source": "backfill",
        "cursor": first_partition["cursor"],
    }
    assert first_run["runSpec"]["params"]["backfill"] == {
        "partitionKey": "2026-06-01",
        "windowStart": "2026-06-01T00:00:00Z",
        "windowEnd": "2026-06-02T00:00:00Z",
        "timezone": "UTC",
        "reprocessBehavior": "none",
    }

    replay_data = replay["data"]
    assert replay_data["launchId"] == data["launchId"]
    assert replay_data["replayedRunCount"] == 0
    assert replay_data["submittedThisTick"] == 0
    assert replay_data["pendingPartitionCount"] == 1
    assert [item["state"] for item in replay_data["partitions"]] == ["submitted", "pending"]
    assert [item["runId"] for item in replay_data["partitions"]] == [item["runId"] for item in data["partitions"]]

    launch_audit = list_governance_audit_events(cfg, action="workflow_trigger.backfill_launch")["items"]
    assert launch_audit[-1]["actor"] == "operator"
    assert launch_audit[-1]["details"]["partitionCount"] == 2


@pytest.mark.parametrize(
    ("source_type", "trigger_spec", "message"),
    [
        ("dataset", {"assetKey": "reads.fastq"}, "WORKFLOW_TRIGGER_READINESS_RESOURCE_SPEC_REQUIRED"),
        (
            "database_ready",
            {"resource": {"type": "file", "id": "db:blast"}},
            "WORKFLOW_TRIGGER_READINESS_TRIGGER_RESOURCE_TYPE_MISMATCH: database != file",
        ),
    ],
)
def test_readiness_trigger_creation_requires_explicit_resource_identity(
    source_type: str,
    trigger_spec: dict[str, object],
    message: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match=message):
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
                triggerSpec=trigger_spec,
                enabled=True,
            ),
            actor="pytest",
        )


def _webhook_trigger_spec() -> dict[str, object]:
    return {
        "provider": "instrument-qc",
        "eventMatch": {"eventTypes": ["dataset.ready"]},
    }


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
