from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.trigger_read_model import redact_trigger_spec_for_read
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request, list_workflow_triggers_from_storage
from apps.remote_runner.trigger_storage import require_workflow_trigger
from tests.helpers.reference_database import make_configured_remote_runner


def test_webhook_trigger_read_model_redacts_secret_ref_on_create_and_list(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    raw_secret_ref = "secret://webhooks/github/main"

    created = create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="GitHub webhook",
            sourceType="webhook",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
                "params": {"token": "run-template-token"},
            },
            triggerSpec={
                "provider": "github",
                "eventMatch": {"eventTypes": ["push"]},
                "signature": {
                    "secretRef": raw_secret_ref,
                },
            },
        ),
        actor="pytest",
    )["data"]
    listed = list_workflow_triggers_from_storage(cfg)["data"]["items"][0]

    for trigger in (created, listed):
        signature = trigger["triggerSpec"]["signature"]
        assert signature["secretRef"]["redacted"] is True
        assert signature["secretRef"]["reason"] == "secret-ref"
        assert signature["secretRef"]["scheme"] == "secret"
        assert signature["secretRef"]["providerKind"] == "remote-runner-secret"
        assert signature["secretRef"]["purpose"] == "webhook-signing-secret"
        assert "refHash" in signature["secretRef"]
        assert trigger["triggerSpecRedactions"] == [
            {
                "path": "triggerSpec.signature.secretRef",
                "reason": "secret-ref",
                "refHash": signature["secretRef"]["refHash"],
                "scheme": "secret",
                "providerKind": "remote-runner-secret",
                "purpose": "webhook-signing-secret",
            }
        ]
        assert trigger["runSpec"]["params"]["token"] == {"redacted": True, "reason": "secret-like-field"}
        assert trigger["runSpecRedactions"] == [
            {
                "path": "runSpec.params.token",
                "reason": "secret-like-field",
            }
        ]
        assert "run-template-token" not in repr(trigger)
        assert raw_secret_ref not in repr(trigger)


def test_trigger_storage_keeps_raw_trigger_spec_for_internal_scheduler_and_verification(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    raw_secret_ref = "secret://webhooks/slack/main"

    created = create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Slack webhook",
            sourceType="webhook",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={
                "provider": "slack",
                "eventMatch": {"eventTypes": ["app_mention"]},
                "signature": {
                    "secretRef": raw_secret_ref,
                },
            },
        ),
        actor="pytest",
    )["data"]

    internal = require_workflow_trigger(cfg, created["triggerId"])

    assert internal["triggerSpec"]["signature"]["secretRef"] == raw_secret_ref
    assert raw_secret_ref not in repr(created)


def test_trigger_read_model_redacts_nested_secret_like_fields_without_hashing_secret_values() -> None:
    raw_secret = "super-secret-value"

    redacted = redact_trigger_spec_for_read(
        {
            "provider": "instrument-qc",
            "eventMatch": {"eventTypes": ["dataset.ready"]},
            "headers": {
                "Authorization": raw_secret,
                "bearer": raw_secret,
                "accessKey": raw_secret,
                "identityRef": raw_secret,
                "keyFile": raw_secret,
                "nested": [{"apiKey": raw_secret}],
            },
        }
    )

    assert redacted["headers"]["Authorization"] == {"redacted": True, "reason": "secret-like-field"}
    assert redacted["headers"]["bearer"] == {"redacted": True, "reason": "secret-like-field"}
    assert redacted["headers"]["accessKey"] == {"redacted": True, "reason": "secret-like-field"}
    assert redacted["headers"]["identityRef"] == {"redacted": True, "reason": "secret-like-field"}
    assert redacted["headers"]["keyFile"] == {"redacted": True, "reason": "secret-like-field"}
    assert redacted["headers"]["nested"][0]["apiKey"] == {"redacted": True, "reason": "secret-like-field"}
    assert raw_secret not in repr(redacted)
    assert "refHash" not in repr(redacted)


def test_trigger_read_model_redacts_malformed_secret_ref_without_raw_ref_leak() -> None:
    raw_secret_ref = "inline://bad-secret-value"

    redacted = redact_trigger_spec_for_read({"signature": {"secretRef": raw_secret_ref}})

    secret_ref = redacted["signature"]["secretRef"]
    assert secret_ref["redacted"] is True
    assert secret_ref["reason"] == "secret-ref"
    assert "refHash" not in secret_ref
    assert "scheme" not in secret_ref
    assert raw_secret_ref not in repr(redacted)


def _skip_runtime_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
