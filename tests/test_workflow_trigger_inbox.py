from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest, WorkflowTriggerInboxEventRequest
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    list_workflow_trigger_inbox_events_from_storage,
    submit_workflow_trigger_inbox_event_from_request,
)
from apps.remote_runner.trigger_storage import list_workflow_trigger_events
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_webhook_inbox_records_delivery_and_links_dispatch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
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
    replay = submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], request)
    inbox_list = list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]
    submitted_list = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="submitted",
    )["data"]

    inbox = first["data"]["inbox"]
    replay_inbox = replay["data"]["inbox"]
    assert inbox["state"] == "submitted"
    assert inbox["signatureState"] == "unsupported"
    assert inbox["dedupeKey"] == f"webhook:{trigger['triggerId']}:instrument-qc:evt_001"
    assert inbox["triggerEventId"] == first["data"]["event"]["triggerEventId"]
    assert inbox["runId"] == first["data"]["run"]["runId"]
    assert inbox["deliveryCount"] == 1
    assert replay["data"]["replayed"] is True
    assert replay_inbox["inboxEventId"] == inbox["inboxEventId"]
    assert replay_inbox["deliveryCount"] == 2
    assert inbox_list["schemaVersion"] == "workflow-trigger-inbox-list.v1"
    assert inbox_list["items"][0]["inboxEventId"] == inbox["inboxEventId"]
    assert submitted_list["items"][0]["state"] == "submitted"
    dispatch_audit_events = list_governance_audit_events(cfg, action="workflow_trigger.dispatch")["items"]
    assert [item["details"]["replayed"] for item in dispatch_audit_events] == [False, True]


def test_webhook_inbox_rejects_duplicate_identity_with_different_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    first = WorkflowTriggerInboxEventRequest(
        source="instrument-qc",
        eventId="evt_001",
        payload={"dataset": "reads.fastq"},
    )
    changed = WorkflowTriggerInboxEventRequest(
        source="instrument-qc",
        eventId="evt_001",
        payload={"dataset": "changed.fastq"},
    )

    submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], first)
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_DEDUPE_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"):
        submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], changed)

    inbox_list = list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]
    assert len(inbox_list["items"]) == 1
    assert inbox_list["items"][0]["deliveryCount"] == 1
    assert len(list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]) == 1


def test_webhook_inbox_dead_letters_dispatch_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr(
        "apps.remote_runner.trigger_service.ensure_execution_admission_ready",
        lambda _cfg: (_ for _ in ()).throw(ValueError("QUEUE_CLOSED")),
    )
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})

    with pytest.raises(ValueError, match="QUEUE_CLOSED"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_001"),
        )

    inbox_list = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]
    assert len(inbox_list["items"]) == 1
    inbox = inbox_list["items"][0]
    assert inbox["state"] == "dead_lettered"
    assert inbox["failureCode"] == "WORKFLOW_TRIGGER_INBOX_DISPATCH_FAILED"
    assert inbox["error"]["message"] == "QUEUE_CLOSED"
    assert inbox["deadLetteredAt"]
    trigger_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]
    assert trigger_events[0]["dispatch"]["state"] == "failed"


def test_webhook_inbox_rejects_non_webhook_without_inbox_row(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="manual", trigger_spec={"mode": "manual"})

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: manual"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_001"),
        )

    with get_connection(cfg) as connection:
        count = connection.execute("SELECT COUNT(*) FROM workflow_trigger_inbox_events").fetchone()[0]
    assert count == 0


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
