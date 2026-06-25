from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.remote_runner import control_service
from apps.remote_runner import route_utils
from apps.remote_runner import trigger_observability_governance as trigger_governance
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


TRIGGER_READ_ACTIONS = (
    "workflow_trigger.list",
    "workflow_trigger.events.read",
    "workflow_trigger.readiness_observation.read",
    "workflow_trigger.inbox.read",
    "workflow_trigger.scheduler_ticks.read",
    "workflow_trigger.backfill_launch.list",
    "workflow_trigger.backfill_launch.read",
)


@pytest.mark.parametrize("action", TRIGGER_READ_ACTIONS)
def test_workflow_trigger_observability_read_actions_allow_operator_and_auditor(
    tmp_path,
    action: str,
) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    operator = make_configured_remote_runner(
        tmp_path / "operator",
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    auditor = make_configured_remote_runner(
        tmp_path / "auditor",
        token="rbac-token",
        api_token_roles=("auditor",),
    )

    try:
        authorize_action(denied, action)
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError(f"{action} must require workflow-operator or auditor")

    deny_events = list_governance_audit_events(denied, action=action)["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["workflow-operator", "auditor"]
    assert deny_events[-1]["details"]["providedRoles"] == ["artifact-curator"]
    assert authorize_action(operator, action).roles == ("workflow-operator",)
    assert authorize_action(auditor, action).roles == ("auditor",)


@pytest.mark.parametrize(
    ("path", "action", "function_name", "subject_kind"),
    (
        (
            "/api/v1/workflow-triggers",
            "workflow_trigger.list",
            "list_governed_workflow_triggers",
            "workflow_trigger",
        ),
        (
            "/api/v1/workflow-triggers/wtr_denied/events",
            "workflow_trigger.events.read",
            "list_governed_workflow_trigger_events",
            "workflow_trigger_event",
        ),
        (
            "/api/v1/workflow-triggers/wtr_denied/readiness-observation",
            "workflow_trigger.readiness_observation.read",
            "get_governed_workflow_trigger_readiness_observation",
            "workflow_trigger_readiness_observation",
        ),
        (
            "/api/v1/workflow-triggers/wtr_denied/inbox",
            "workflow_trigger.inbox.read",
            "list_governed_workflow_trigger_inbox_events",
            "workflow_trigger_inbox_event",
        ),
        (
            "/api/v1/workflow-trigger-scheduler/ticks",
            "workflow_trigger.scheduler_ticks.read",
            "list_governed_workflow_trigger_scheduler_ticks",
            "workflow_trigger_scheduler",
        ),
        (
            "/api/v1/workflow-backfill-launches",
            "workflow_trigger.backfill_launch.list",
            "list_governed_workflow_backfill_launches",
            "workflow_backfill_launch",
        ),
        (
            "/api/v1/workflow-backfill-launches/bfl_denied",
            "workflow_trigger.backfill_launch.read",
            "get_governed_workflow_backfill_launch",
            "workflow_backfill_launch",
        ),
    ),
)
def test_workflow_trigger_observability_routes_deny_wrong_role_before_read(
    tmp_path,
    monkeypatch,
    path: str,
    action: str,
    function_name: str,
    subject_kind: str,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_read(*_args, **_kwargs):
        raise AssertionError("workflow trigger read must not run before authorization")

    monkeypatch.setattr(control_service, function_name, fail_read)

    response = TestClient(app).get(
        path,
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action=action)["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == subject_kind
    assert events[0]["subjectId"] == "authorization"


def test_workflow_trigger_observability_routes_record_safe_allow_audit(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        trigger_governance,
        "list_workflow_triggers_from_storage",
        lambda _cfg: {
            "data": {
                "items": [
                    {"triggerId": "wtr_audit", "enabled": True},
                    {"triggerId": "wtr_disabled", "enabled": False},
                ]
            }
        },
    )
    monkeypatch.setattr(
        trigger_governance,
        "list_workflow_trigger_events_from_storage",
        lambda _cfg, _trigger_id: {
            "data": {
                "items": [
                    {
                        "triggerEventId": "wte_raw_canary",
                        "runId": "run_raw_canary",
                        "payloadHash": "payload_hash_raw_canary",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        trigger_governance,
        "get_workflow_trigger_readiness_observation_from_storage",
        lambda _cfg, _trigger_id: {
            "data": {
                "triggerId": "wtr_audit",
                "sourceType": "dataset",
                "observation": {
                    "resourceType": "file",
                    "observedState": "ready",
                    "dispatchState": "submitted",
                    "resourceUriPresent": True,
                    "resourceUri": "file:///raw_canary/dataset.fastq",
                },
            }
        },
    )
    monkeypatch.setattr(
        trigger_governance,
        "list_workflow_trigger_inbox_events_from_storage",
        lambda _cfg, _trigger_id, *, state=None, limit=100: {
            "data": {
                "items": [
                    {
                        "inboxEventId": "inbox_raw_canary",
                        "source": "webhook_raw_canary",
                        "state": state or "submitted",
                        "payloadHash": "inbox_payload_hash_raw_canary",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        trigger_governance,
        "list_workflow_backfill_launches_from_storage",
        lambda _cfg, *, trigger_id=None, limit=100: {
            "data": {
                "items": [
                    {
                        "launchId": "bfl_audit",
                        "triggerId": trigger_id,
                        "state": "running",
                        "runSpec": {"raw": "run_spec_raw_canary"},
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        trigger_governance,
        "get_workflow_backfill_launch_from_storage",
        lambda _cfg, _launch_id: {
            "data": {
                "launchId": "bfl_audit",
                "state": "running",
                "runSpec": {"raw": "run_spec_raw_canary"},
                "partitionSummary": {
                    "partitionCount": 3,
                    "submittedRunCount": 2,
                    "activeRunCount": 1,
                    "pendingPartitionCount": 1,
                    "failedPartitionCount": 0,
                    "cancelRequestedPartitionCount": 0,
                },
            }
        },
    )

    client = TestClient(app)
    headers = {"Authorization": "Bearer rbac-token"}
    responses = [
        client.get("/api/v1/workflow-triggers", headers=headers),
        client.get("/api/v1/workflow-triggers/wtr_audit/events", headers=headers),
        client.get("/api/v1/workflow-triggers/wtr_audit/readiness-observation", headers=headers),
        client.get("/api/v1/workflow-triggers/wtr_audit/inbox?state=submitted&limit=7", headers=headers),
        client.get("/api/v1/workflow-trigger-scheduler/ticks?limit=4", headers=headers),
        client.get("/api/v1/workflow-backfill-launches?triggerId=wtr_audit&limit=3", headers=headers),
        client.get("/api/v1/workflow-backfill-launches/bfl_audit", headers=headers),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200, 200, 200]
    assert _latest_details(cfg, "workflow_trigger.list") == {
        "returnedCount": 2,
        "enabledCount": 1,
    }
    assert _latest_details(cfg, "workflow_trigger.events.read") == {"returnedCount": 1}
    assert _latest_details(cfg, "workflow_trigger.readiness_observation.read") == {
        "hasObservation": True,
        "sourceType": "dataset",
        "resourceType": "file",
        "observedState": "ready",
        "dispatchState": "submitted",
        "resourceUriPresent": True,
    }
    assert _latest_details(cfg, "workflow_trigger.inbox.read") == {
        "filteredByState": True,
        "limit": 7,
        "returnedCount": 1,
    }
    assert _latest_details(cfg, "workflow_trigger.scheduler_ticks.read") == {
        "limit": 4,
        "returnedCount": 0,
        "cronSubmittedCount": 0,
        "backfillSubmittedCount": 0,
        "errorTickCount": 0,
        "controlsExposed": False,
    }
    assert _latest_details(cfg, "workflow_trigger.backfill_launch.list") == {
        "filteredByTrigger": True,
        "limit": 3,
        "returnedCount": 1,
    }
    assert _latest_details(cfg, "workflow_trigger.backfill_launch.read") == {
        "state": "running",
        "partitionCount": 3,
        "submittedRunCount": 2,
        "activeRunCount": 1,
        "pendingPartitionCount": 1,
        "failedPartitionCount": 0,
        "cancelRequestedPartitionCount": 0,
    }

    serialized = json.dumps(
        [
            list_governance_audit_events(cfg, action=action)["items"][-1]
            for action in TRIGGER_READ_ACTIONS
        ],
        sort_keys=True,
    )
    assert "raw_canary" not in serialized
    assert "runSpec" not in serialized
    assert "rbac-token" not in serialized
    for action in TRIGGER_READ_ACTIONS:
        assert "payloadHash" not in _latest_details(cfg, action)


def _latest_details(cfg, action: str) -> dict[str, object]:
    return list_governance_audit_events(cfg, action=action)["items"][-1]["details"]
