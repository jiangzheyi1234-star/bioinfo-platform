from __future__ import annotations

import pytest

from apps.remote_runner.evidence_storage import append_evidence_event
from apps.remote_runner.governance_audit import (
    GOVERNANCE_AUDIT_EVENT_TYPE,
    GOVERNANCE_AUDIT_SCHEMA_NAME,
    list_governance_audit_events,
    record_governance_audit_event,
)
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_governance_audit_promotes_request_project_and_tenant_context(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    event = record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id="run_context",
        details={
            "requestId": "req_context_001",
            "projectId": "proj_context",
            "tenantId": "tenant_context",
            "pipelineId": "file-summary-v1",
        },
    )

    assert event["requestId"] == "req_context_001"
    assert event["projectId"] == "proj_context"
    assert event["tenantId"] == "tenant_context"
    assert event["correlationId"] == ""
    assert event["details"]["requestId"] == "req_context_001"

    listed = list_governance_audit_events(cfg, action="run.submit")["items"][0]
    assert listed["requestId"] == "req_context_001"
    assert listed["projectId"] == "proj_context"
    assert listed["tenantId"] == "tenant_context"


def test_governance_audit_records_machine_token_actor_roles(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("workflow-operator", "auditor"))

    event = record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id="run_actor_roles",
        details={"requestId": "req_actor_roles"},
    )

    assert event["actorRoles"] == ["auditor", "workflow-operator"]
    listed = list_governance_audit_events(cfg, action="run.submit")["items"][0]
    assert listed["actorRoles"] == ["auditor", "workflow-operator"]


def test_governance_audit_explicit_actor_roles_override_config_roles(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("workflow-operator",))

    event = record_governance_audit_event(
        cfg,
        action="artifact.gc.preview",
        subject_kind="artifact_gc",
        subject_id="gc_actor_roles",
        actor_roles=("auditor", "auditor", "artifact-curator"),
        details={"requestId": "req_gc_actor_roles"},
    )

    assert event["actorRoles"] == ["artifact-curator", "auditor"]


def test_governance_audit_does_not_promote_roles_from_details(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path, api_token_roles=("auditor",))

    event = record_governance_audit_event(
        cfg,
        action="workflow_trigger.dispatch",
        subject_kind="workflow_trigger_event",
        subject_id="trig_evt_roles",
        details={
            "actorRoles": ["platform-admin"],
            "eventContext": {"actorRoles": ["platform-admin"], "correlationId": "batch_roles"},
        },
    )

    assert event["actorRoles"] == ["auditor"]
    assert event["correlationId"] == "batch_roles"


def test_governance_audit_promotes_nested_event_context_correlation_id(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    event = record_governance_audit_event(
        cfg,
        action="workflow_trigger.dispatch",
        subject_kind="workflow_trigger_event",
        subject_id="trig_evt_context",
        details={
            "triggerId": "trig_context",
            "eventContext": {
                "source": "instrument-qc",
                "eventId": "evt_context",
                "correlationId": "batch_context",
            },
        },
    )

    assert event["correlationId"] == "batch_context"
    assert event["requestId"] == ""
    assert event["details"]["eventContext"]["correlationId"] == "batch_context"


def test_governance_audit_does_not_promote_nested_event_context_identity_fields(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    event = record_governance_audit_event(
        cfg,
        action="workflow_trigger.dispatch",
        subject_kind="workflow_trigger_event",
        subject_id="trig_evt_context_identity",
        details={
            "eventContext": {
                "requestId": "req_untrusted",
                "correlationId": "batch_context",
                "projectId": "proj_untrusted",
                "tenantId": "tenant_untrusted",
            },
        },
    )

    assert event["correlationId"] == "batch_context"
    assert event["requestId"] == ""
    assert event["projectId"] == ""
    assert event["tenantId"] == ""


def test_governance_audit_promotes_only_scalar_context_fields(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    event = record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id="run_non_scalar_context",
        details={
            "requestId": {"id": "req_object"},
            "projectId": ["proj_list"],
            "tenantId": True,
            "correlationId": 42,
        },
    )

    assert event["requestId"] == ""
    assert event["projectId"] == ""
    assert event["tenantId"] == ""
    assert event["correlationId"] == "42"


def test_governance_audit_read_model_defaults_missing_context_fields_for_legacy_payloads(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with get_connection(cfg) as connection:
        append_evidence_event(
            connection,
            event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
            schema_name=GOVERNANCE_AUDIT_SCHEMA_NAME,
            subject_kind="run",
            subject_id="run_legacy_context",
            payload={
                "action": "run.submit",
                "actor": "remote-runner-api",
                "decision": "allow",
                "reasonCode": "",
                "subjectKind": "run",
                "subjectId": "run_legacy_context",
                "details": {"requestId": "req_legacy_detail"},
            },
        )
        connection.commit()

    listed = list_governance_audit_events(cfg, action="run.submit")["items"][0]
    assert listed["requestId"] == ""
    assert listed["correlationId"] == ""
    assert listed["projectId"] == ""
    assert listed["tenantId"] == ""
    assert listed["actorRoles"] == []
    assert listed["details"]["requestId"] == "req_legacy_detail"


def test_governance_audit_read_model_defaults_malformed_legacy_actor_roles(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with get_connection(cfg) as connection:
        append_evidence_event(
            connection,
            event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
            schema_name=GOVERNANCE_AUDIT_SCHEMA_NAME,
            subject_kind="run",
            subject_id="run_legacy_bad_roles",
            payload={
                "action": "run.submit",
                "actor": "remote-runner-api",
                "actorRoles": "platform-admin",
                "decision": "allow",
                "reasonCode": "",
                "subjectKind": "run",
                "subjectId": "run_legacy_bad_roles",
                "details": {},
            },
        )
        append_evidence_event(
            connection,
            event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
            schema_name=GOVERNANCE_AUDIT_SCHEMA_NAME,
            subject_kind="run",
            subject_id="run_legacy_object_roles",
            payload={
                "action": "run.submit",
                "actor": "remote-runner-api",
                "actorRoles": {"role": "platform-admin"},
                "decision": "allow",
                "reasonCode": "",
                "subjectKind": "run",
                "subjectId": "run_legacy_object_roles",
                "details": {},
            },
        )
        connection.commit()

    listed = list_governance_audit_events(cfg, action="run.submit")["items"]
    assert [item["actorRoles"] for item in listed] == [[], []]


def test_governance_audit_explicit_context_overrides_details(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    event = record_governance_audit_event(
        cfg,
        action="artifact.gc.preview",
        subject_kind="artifact_gc",
        subject_id="gc_context",
        request_id="req_explicit",
        correlation_id="corr_explicit",
        project_id="proj_explicit",
        tenant_id="tenant_explicit",
        details={
            "requestId": "req_details",
            "correlationId": "corr_details",
            "projectId": "proj_details",
            "tenantId": "tenant_details",
        },
    )

    assert event["requestId"] == "req_explicit"
    assert event["correlationId"] == "corr_explicit"
    assert event["projectId"] == "proj_explicit"
    assert event["tenantId"] == "tenant_explicit"


def test_governance_audit_context_does_not_weaken_secret_detail_rejection(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="GOVERNANCE_AUDIT_SECRET_FIELD_FORBIDDEN: details.eventContext.secretRef"):
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.dispatch",
            subject_kind="workflow_trigger_event",
            subject_id="trig_evt_secret_context",
            details={
                "eventContext": {
                    "correlationId": "batch_context",
                    "secretRef": "env://WEBHOOK_SECRET",
                },
            },
        )
