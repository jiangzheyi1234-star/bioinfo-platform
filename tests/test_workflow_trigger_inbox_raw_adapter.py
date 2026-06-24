from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.control_service import submit_workflow_trigger_inbox_event_envelope_request
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from apps.remote_runner.webhook_raw_request import build_webhook_raw_request_envelope
from tests.helpers.reference_database import make_configured_remote_runner


def test_control_service_submits_webhook_inbox_event_from_raw_envelope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Instrument webhook",
            sourceType="webhook",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={"provider": "instrument-qc"},
        ),
        actor="pytest",
    )["data"]
    raw_body = b'{\n  "eventType": "dataset.ready",\n  "source": "instrument-qc",\n  "eventId": "evt_001"\n}'
    compact_body = json.dumps(json.loads(raw_body), separators=(",", ":"), sort_keys=True).encode("utf-8")
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json"},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    response = asyncio.run(
        submit_workflow_trigger_inbox_event_envelope_request(
            trigger["triggerId"],
            envelope,
            "Bearer test-token",
        )
    )

    inbox = response["data"]["inbox"]
    assert envelope.raw_body == raw_body
    assert envelope.raw_body != compact_body
    assert inbox["state"] == "submitted"
    assert inbox["signatureState"] == "unsupported"
    assert inbox["dedupeKey"] == f"webhook:{trigger['triggerId']}:instrument-qc:evt_001"
    assert response["data"]["event"]["payload"]["eventContext"] == {
        "source": "instrument-qc",
        "eventId": "evt_001",
    }


def test_control_service_rejects_invalid_raw_envelope_payload_with_safe_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    raw_body = b'{"source": "instrument-qc", "eventId": "evt_001", "token": "payload-secret"}'
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json"},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            submit_workflow_trigger_inbox_event_envelope_request(
                "wtr_missing",
                envelope,
                "Bearer test-token",
            )
        )

    assert str(exc_info.value) == "WORKFLOW_TRIGGER_INBOX_PAYLOAD_INVALID"
    assert "payload-secret" not in repr(exc_info.value)


def _skip_runtime_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
