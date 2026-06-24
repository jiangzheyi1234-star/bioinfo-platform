from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from apps.remote_runner.api_models import (
    WorkflowTriggerCreateRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerInboxReplayRequest,
)
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_inbox_service import (
    list_workflow_trigger_inbox_events_from_storage,
    submit_workflow_trigger_inbox_event_from_request,
)
from apps.remote_runner.trigger_inbox_replay_service import replay_workflow_trigger_inbox_event_from_request
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from apps.remote_runner.trigger_storage import list_workflow_trigger_events
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.webhook_raw_request import build_webhook_raw_request_envelope
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
    assert inbox["signatureDetails"] == {
        "schemaVersion": "workflow-trigger-inbox-signature-metadata.v1",
        "signatureState": "unsupported",
    }
    assert inbox["rawBodySha256"] == ""
    assert inbox["rawBodySizeBytes"] == 0
    assert inbox["rawContentType"] == ""
    assert inbox["rawHeaderNames"] == []
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


def test_webhook_inbox_rejects_duplicate_identity_with_different_raw_body_hash(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    first_body = b'{"source":"instrument-qc","eventId":"evt_raw","payload":{"dataset":"reads.fastq"}}'
    changed_raw_body = b'{\n  "source": "instrument-qc",\n  "eventId": "evt_raw",\n  "payload": {"dataset": "reads.fastq"}\n}'
    first_request = WorkflowTriggerInboxEventRequest.model_validate(json.loads(first_body))
    replay_request = WorkflowTriggerInboxEventRequest.model_validate(json.loads(changed_raw_body))
    first_envelope = build_webhook_raw_request_envelope(
        raw_body=first_body,
        headers={"Content-Type": "application/json"},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )
    changed_envelope = build_webhook_raw_request_envelope(
        raw_body=changed_raw_body,
        headers={"Content-Type": "application/json"},
        received_at=datetime.fromtimestamp(1_700_000_001, tz=timezone.utc),
    )

    submit_workflow_trigger_inbox_event_from_request(
        cfg,
        trigger["triggerId"],
        first_request,
        raw_envelope=first_envelope,
    )
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_DEDUPE_KEY_REUSED_WITH_DIFFERENT_RAW_BODY"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            replay_request,
            raw_envelope=changed_envelope,
        )

    inbox_list = list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]
    assert len(inbox_list["items"]) == 1
    assert inbox_list["items"][0]["rawBodySha256"] == first_envelope.body_sha256
    assert inbox_list["items"][0]["deliveryCount"] == 1


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


def test_webhook_inbox_replay_resubmits_dead_lettered_dispatch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    closed = {"value": True}
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    def admission(_cfg) -> None:
        if closed["value"]:
            raise ValueError("QUEUE_CLOSED")

    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", admission)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    request = WorkflowTriggerInboxEventRequest(
        eventType="dataset.ready",
        source="instrument-qc",
        eventId="evt_replay",
        actor="instrument-agent",
        payload={"dataset": "reads.fastq"},
    )

    with pytest.raises(ValueError, match="QUEUE_CLOSED"):
        submit_workflow_trigger_inbox_event_from_request(cfg, trigger["triggerId"], request)
    inbox = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]
    trigger_event_id = inbox["triggerEventId"]

    closed["value"] = False
    replayed = replay_workflow_trigger_inbox_event_from_request(
        cfg,
        trigger["triggerId"],
        inbox["inboxEventId"],
        WorkflowTriggerInboxReplayRequest(
            confirmation="replay-dead-lettered-inbox-event",
            actor="operator",
            reason="queue restored",
        ),
    )
    updated = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="submitted",
    )["data"]["items"][0]
    trigger_events = list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]
    replay_audit = list_governance_audit_events(cfg, action="workflow_trigger.inbox_replay")["items"]

    assert replayed["data"]["schemaVersion"] == "workflow-trigger-inbox-replay.v1"
    assert replayed["data"]["inbox"]["state"] == "submitted"
    assert updated["inboxEventId"] == inbox["inboxEventId"]
    assert updated["triggerEventId"] == trigger_event_id
    assert updated["runId"] == replayed["data"]["run"]["runId"]
    assert updated["failureCode"] == ""
    assert updated["deadLetteredAt"] is None
    assert len(trigger_events) == 1
    assert trigger_events[0]["triggerEventId"] == trigger_event_id
    assert trigger_events[0]["dispatch"]["state"] == "submitted"
    assert replay_audit[0]["details"]["reason"] == "queue restored"


def test_webhook_inbox_replay_requires_confirmation_without_changing_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_confirmation"),
        )
    inbox = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_REPLAY_CONFIRMATION_REQUIRED"):
        replay_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            inbox["inboxEventId"],
            WorkflowTriggerInboxReplayRequest.model_construct(confirmation="wrong"),
        )

    unchanged = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]
    assert unchanged["inboxEventId"] == inbox["inboxEventId"]
    assert unchanged["state"] == "dead_lettered"


def test_webhook_inbox_replay_rejects_submitted_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    submitted = submit_workflow_trigger_inbox_event_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_submitted"),
    )

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_REPLAY_STATE_UNSUPPORTED: submitted"):
        replay_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            submitted["data"]["inbox"]["inboxEventId"],
            WorkflowTriggerInboxReplayRequest(confirmation="replay-dead-lettered-inbox-event"),
        )

    inbox = list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"][0]
    assert inbox["state"] == "submitted"


def test_webhook_inbox_replay_fails_loudly_without_trigger_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})
    monkeypatch.setattr(
        "apps.remote_runner.trigger_service.ensure_submission_ready",
        lambda _cfg: (_ for _ in ()).throw(ValueError("SUBMISSION_CLOSED")),
    )

    with pytest.raises(ValueError, match="SUBMISSION_CLOSED"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_missing"),
        )
    inbox = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_INBOX_REPLAY_EVENT_NOT_FOUND"):
        replay_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            inbox["inboxEventId"],
            WorkflowTriggerInboxReplayRequest(confirmation="replay-dead-lettered-inbox-event"),
        )

    assert inbox["triggerEventId"] is None
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []


def test_webhook_inbox_replay_failure_keeps_dead_letter_state(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    queue_state = {"message": "QUEUE_CLOSED"}
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr(
        "apps.remote_runner.trigger_service.ensure_execution_admission_ready",
        lambda _cfg: (_ for _ in ()).throw(ValueError(queue_state["message"])),
    )
    trigger = _create_trigger(cfg, source_type="webhook", trigger_spec={"provider": "instrument-qc"})

    with pytest.raises(ValueError, match="QUEUE_CLOSED"):
        submit_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(source="instrument-qc", eventId="evt_still_closed"),
        )
    inbox = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]

    queue_state["message"] = "QUEUE_STILL_CLOSED"
    with pytest.raises(ValueError, match="QUEUE_STILL_CLOSED"):
        replay_workflow_trigger_inbox_event_from_request(
            cfg,
            trigger["triggerId"],
            inbox["inboxEventId"],
            WorkflowTriggerInboxReplayRequest(confirmation="replay-dead-lettered-inbox-event"),
        )

    failed = list_workflow_trigger_inbox_events_from_storage(
        cfg,
        trigger["triggerId"],
        state="dead_lettered",
    )["data"]["items"][0]
    assert failed["state"] == "dead_lettered"
    assert failed["triggerEventId"] == inbox["triggerEventId"]
    assert failed["failureCode"] == "WORKFLOW_TRIGGER_INBOX_REPLAY_FAILED"
    assert failed["error"]["message"] == "QUEUE_STILL_CLOSED"


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
