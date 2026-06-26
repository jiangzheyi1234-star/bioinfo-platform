from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.trigger_read_model import (
    redact_trigger_spec_for_read,
    trigger_for_read_model,
    trigger_list_for_read_model,
)
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request, list_workflow_triggers_from_storage
from apps.remote_runner.trigger_storage import require_workflow_trigger
from tests.helpers.reference_database import make_configured_remote_runner


def test_trigger_read_model_adds_schema_versions_and_enabled_manual_contract() -> None:
    trigger = _trigger_for_contract("manual")
    read = trigger_for_read_model(trigger)
    listed = trigger_list_for_read_model({"items": [trigger]})

    assert read["schemaVersion"] == "workflow-trigger-read.v1"
    assert listed["schemaVersion"] == "workflow-trigger-list.v1"
    assert listed["items"][0]["schemaVersion"] == "workflow-trigger-read.v1"
    assert read["triggerContract"] == {
        "schemaVersion": "workflow-trigger-contract.v1",
        "sourceType": "manual",
        "authoritativeIngress": "manual-event-api",
        "provenanceStamped": True,
        "immutableTriggerEventRequired": True,
        "rawPayloadExported": False,
        "supportedOperatorActions": ["submit-manual-event"],
        "blockers": [],
    }


@pytest.mark.parametrize(
    "source_type",
    ["manual", "cron", "webhook", "dataset", "file", "database_ready", "backfill"],
)
def test_trigger_read_model_disabled_trigger_contract_blocks_actions(source_type: str) -> None:
    read = trigger_for_read_model(_trigger_for_contract(source_type, enabled=False))

    assert read["triggerContract"]["authoritativeIngress"] != ""
    assert read["triggerContract"]["supportedOperatorActions"] == []
    assert read["triggerContract"]["blockers"] == ["trigger-disabled"]


@pytest.mark.parametrize(
    ("source_type", "ingress", "actions", "blockers"),
    [
        ("manual", "manual-event-api", ["submit-manual-event"], []),
        ("cron", "cron-scheduler", [], ["cron-scheduler-owned"]),
        ("webhook", "webhook-inbox", [], ["webhook-inbox-owned"]),
        ("dataset", "readiness-api", [], ["readiness-api-owned"]),
        ("file", "readiness-api", [], ["readiness-api-owned"]),
        ("database_ready", "readiness-api", [], ["readiness-api-owned"]),
        ("backfill", "backfill-launch", ["preview-backfill"], ["backfill-launch-owned"]),
    ],
)
def test_trigger_read_model_contract_source_boundaries(
    source_type: str,
    ingress: str,
    actions: list[str],
    blockers: list[str],
) -> None:
    read = trigger_for_read_model(_trigger_for_contract(source_type))

    assert read["triggerContract"]["sourceType"] == source_type
    assert read["triggerContract"]["authoritativeIngress"] == ingress
    assert read["triggerContract"]["supportedOperatorActions"] == actions
    assert read["triggerContract"]["blockers"] == blockers


def test_trigger_read_model_unknown_source_contract_is_explicitly_unsupported() -> None:
    read = trigger_for_read_model(_trigger_for_contract("legacy_queue"))

    assert read["triggerContract"]["sourceType"] == "legacy_queue"
    assert read["triggerContract"]["authoritativeIngress"] == "unsupported"
    assert read["triggerContract"]["supportedOperatorActions"] == []
    assert read["triggerContract"]["blockers"] == ["unknown-trigger-source"]


def test_trigger_contract_does_not_leak_redacted_specs() -> None:
    raw_secret_ref = "secret://webhooks/github/main"
    raw_token = "run-template-token"

    read = trigger_for_read_model(
        _trigger_for_contract(
            "webhook",
            trigger_spec={"signature": {"secretRef": raw_secret_ref}},
            run_spec={"params": {"token": raw_token}},
        )
    )

    assert read["triggerContract"] == {
        "schemaVersion": "workflow-trigger-contract.v1",
        "sourceType": "webhook",
        "authoritativeIngress": "webhook-inbox",
        "provenanceStamped": True,
        "immutableTriggerEventRequired": True,
        "rawPayloadExported": False,
        "supportedOperatorActions": [],
        "blockers": ["webhook-inbox-owned"],
    }
    assert raw_secret_ref not in repr(read["triggerContract"])
    assert raw_token not in repr(read["triggerContract"])
    assert raw_secret_ref not in repr(read)
    assert raw_token not in repr(read)


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


def _trigger_for_contract(
    source_type: str,
    *,
    enabled: bool = True,
    trigger_spec: dict[str, object] | None = None,
    run_spec: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "triggerId": "wtr_contract",
        "name": "Contract trigger",
        "sourceType": source_type,
        "serverId": "srv_primary",
        "pipelineId": "file-summary-standard-v1",
        "enabled": enabled,
        "triggerSpec": trigger_spec or {},
        "runSpec": run_spec or {},
    }
