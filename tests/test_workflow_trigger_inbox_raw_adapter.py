from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest, WorkflowTriggerInboxEventRequest
from apps.remote_runner.control_service import (
    submit_workflow_trigger_inbox_event_envelope_request,
    submit_workflow_trigger_inbox_event_request,
)
from apps.remote_runner.trigger_inbox_service import list_workflow_trigger_inbox_events_from_storage
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from apps.remote_runner.trigger_storage import list_workflow_trigger_events
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
        headers={
            "Authorization": "Bearer route-secret",
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=signature-secret",
        },
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
    assert inbox["rawBodySha256"] == envelope.body_sha256
    assert inbox["rawBodySizeBytes"] == envelope.body_size_bytes
    assert inbox["rawContentType"] == "application/json"
    assert "Content-Type" in inbox["rawHeaderNames"]
    assert "route-secret" not in repr(inbox)
    assert "signature-secret" not in repr(inbox)
    assert inbox["signatureDetails"] == {
        "schemaVersion": "workflow-trigger-inbox-signature-metadata.v1",
        "signatureState": "unsupported",
        "rawBodySha256": envelope.body_sha256,
        "rawBodySizeBytes": envelope.body_size_bytes,
        "contentType": "application/json",
        "receivedAt": envelope.received_at.isoformat(),
        "headerNames": list(envelope.header_names),
    }
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
    raw_body = b'{"source": "instrument-qc", "eventId": "evt_001", "token": "payload-secret"}'
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json"},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            submit_workflow_trigger_inbox_event_envelope_request(
                trigger["triggerId"],
                envelope,
                "Bearer test-token",
            )
        )

    assert str(exc_info.value) == "WORKFLOW_TRIGGER_INBOX_PAYLOAD_INVALID"
    assert "payload-secret" not in repr(exc_info.value)


def test_control_service_plain_inbox_event_path_does_not_require_raw_envelope(
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

    response = asyncio.run(
        submit_workflow_trigger_inbox_event_request(
            trigger["triggerId"],
            WorkflowTriggerInboxEventRequest(
                source="instrument-qc",
                eventId="evt_plain",
                payload={"dataset": "reads.fastq"},
            ),
            "Bearer test-token",
        )
    )

    inbox = response["data"]["inbox"]
    assert inbox["state"] == "submitted"
    assert inbox["rawBodySha256"] == ""
    assert inbox["rawContentType"] == ""
    assert inbox["signatureDetails"] == {
        "schemaVersion": "workflow-trigger-inbox-signature-metadata.v1",
        "signatureState": "unsupported",
    }


def test_control_service_verifies_signed_github_inbox_event_before_dispatch(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    monkeypatch.setenv("H2OMETA_TEST_WEBHOOK_SECRET", "github-secret")

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)
    raw_body = b'{"eventType":"push","source":"github","eventId":"evt_sig_ok","payload":{"ref":"main"}}'
    signature = "sha256=" + hmac.new(b"github-secret", raw_body, hashlib.sha256).hexdigest()
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
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
    details = inbox["signatureDetails"]
    assert inbox["state"] == "submitted"
    assert inbox["signatureState"] == "verified"
    assert inbox["rawBodySha256"] == envelope.body_sha256
    assert details["schemaVersion"] == "workflow-trigger-inbox-signature-metadata.v1"
    assert details["signatureState"] == "verified"
    assert details["policy"]["mode"] == "required"
    assert details["policy"]["verificationProvider"] == "github"
    assert details["verification"]["signedPayloadSha256"] == envelope.body_sha256
    assert details["credentialRef"]["scheme"] == "env"
    assert "refHash" in details["credentialRef"]
    assert "github-secret" not in repr(inbox)
    assert signature not in repr(inbox)


def test_control_service_rejects_bad_signature_without_dispatching_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    monkeypatch.setenv("H2OMETA_TEST_WEBHOOK_SECRET", "github-secret")

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)
    raw_body = b'{"eventType":"push","source":"github","eventId":"evt_sig_bad","payload":{"ref":"main"}}'
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    with pytest.raises(ValueError, match="WEBHOOK_SIGNATURE_MISMATCH"):
        asyncio.run(
            submit_workflow_trigger_inbox_event_envelope_request(
                trigger["triggerId"],
                envelope,
                "Bearer test-token",
            )
        )

    assert list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []


def test_signed_control_service_plain_inbox_event_path_requires_raw_envelope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SIGNATURE_RAW_ENVELOPE_REQUIRED"):
        asyncio.run(
            submit_workflow_trigger_inbox_event_request(
                trigger["triggerId"],
                WorkflowTriggerInboxEventRequest(source="github", eventId="evt_plain_signed"),
                "Bearer test-token",
            )
        )

    assert list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []


def test_bad_signature_duplicate_does_not_mutate_existing_verified_inbox(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    monkeypatch.setenv("H2OMETA_TEST_WEBHOOK_SECRET", "github-secret")

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)
    raw_body = b'{"eventType":"push","source":"github","eventId":"evt_sig_replay","payload":{"ref":"main"}}'
    signature = "sha256=" + hmac.new(b"github-secret", raw_body, hashlib.sha256).hexdigest()
    good_envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )
    bad_envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64},
        received_at=datetime.fromtimestamp(1_700_000_001, tz=timezone.utc),
    )

    asyncio.run(submit_workflow_trigger_inbox_event_envelope_request(trigger["triggerId"], good_envelope, None))
    with pytest.raises(ValueError, match="WEBHOOK_SIGNATURE_MISMATCH"):
        asyncio.run(submit_workflow_trigger_inbox_event_envelope_request(trigger["triggerId"], bad_envelope, None))

    inbox = list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"][0]
    assert inbox["state"] == "submitted"
    assert inbox["signatureState"] == "verified"
    assert inbox["deliveryCount"] == 1
    assert len(list_workflow_trigger_events(cfg, trigger["triggerId"])["items"]) == 1


def test_signed_invalid_payload_verifies_signature_before_payload_validation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    monkeypatch.setenv("H2OMETA_TEST_WEBHOOK_SECRET", "github-secret")

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)
    raw_body = b'{"source": "github", "eventId": "evt_invalid", "token": "payload-secret"}'
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    with pytest.raises(ValueError, match="WEBHOOK_SIGNATURE_MISMATCH") as exc_info:
        asyncio.run(submit_workflow_trigger_inbox_event_envelope_request(trigger["triggerId"], envelope, None))

    assert "payload-secret" not in repr(exc_info.value)
    assert list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []


def test_signed_inbox_missing_env_secret_fails_without_inbox_row_or_ref_leak(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    monkeypatch.delenv("H2OMETA_TEST_WEBHOOK_SECRET", raising=False)

    async def authorized_config(_authorization: str | None, *, action: str | None = None):
        assert action == "workflow_trigger.dispatch"
        return cfg

    monkeypatch.setattr("apps.remote_runner.control_service._authorized_config_from_request", authorized_config)
    trigger = _create_signed_trigger(cfg)
    raw_body = b'{"eventType":"push","source":"github","eventId":"evt_missing_secret"}'
    signature = "sha256=" + hmac.new(b"github-secret", raw_body, hashlib.sha256).hexdigest()
    envelope = build_webhook_raw_request_envelope(
        raw_body=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SIGNATURE_SECRET_RESOLUTION_FAILED") as exc_info:
        asyncio.run(submit_workflow_trigger_inbox_event_envelope_request(trigger["triggerId"], envelope, None))

    assert "H2OMETA_TEST_WEBHOOK_SECRET" not in repr(exc_info.value)
    assert "github-secret" not in repr(exc_info.value)
    assert list_workflow_trigger_inbox_events_from_storage(cfg, trigger["triggerId"])["data"]["items"] == []
    assert list_workflow_trigger_events(cfg, trigger["triggerId"])["items"] == []


def _create_signed_trigger(cfg) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Signed GitHub webhook",
            sourceType="webhook",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "provider": "github",
                "signature": {"secretRef": "env://H2OMETA_TEST_WEBHOOK_SECRET"},
            },
        ),
        actor="pytest",
    )["data"]


def _skip_runtime_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
