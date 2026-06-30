from __future__ import annotations

from pathlib import Path

from core.contracts.remote_endpoints import (
    GOVERNANCE_AUDIT_EVENTS_READ,
    REMOTE_ENDPOINTS,
    SECRET_PROVIDER_READINESS_READ,
    WORKFLOW_BACKFILL_LAUNCH_CANCEL,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH,
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW,
    WORKFLOW_TRIGGER_CREATE,
    WORKFLOW_TRIGGER_EVENT_SUBMIT,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_INBOX_REPLAY,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_INBOX_SUBMIT,
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_READINESS_SUBMIT,
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    remote_endpoint_success_status,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]
TRIGGER_READ_ENDPOINTS = (
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    GOVERNANCE_AUDIT_EVENTS_READ,
    SECRET_PROVIDER_READINESS_READ,
)
TRIGGER_COMMAND_ENDPOINTS = (
    WORKFLOW_TRIGGER_CREATE,
    WORKFLOW_TRIGGER_EVENT_SUBMIT,
    WORKFLOW_TRIGGER_INBOX_SUBMIT,
    WORKFLOW_TRIGGER_INBOX_REPLAY,
    WORKFLOW_TRIGGER_READINESS_SUBMIT,
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE,
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW,
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH,
    WORKFLOW_BACKFILL_LAUNCH_CANCEL,
)
DISPATCH_ENDPOINTS = (
    WORKFLOW_TRIGGER_EVENT_SUBMIT,
    WORKFLOW_TRIGGER_INBOX_SUBMIT,
    WORKFLOW_TRIGGER_INBOX_REPLAY,
    WORKFLOW_TRIGGER_READINESS_SUBMIT,
)
TRIGGER_COMMAND_METHODS = (
    "create_workflow_trigger",
    "submit_workflow_trigger_event",
    "submit_workflow_trigger_inbox_event",
    "replay_workflow_trigger_inbox_event",
    "submit_workflow_trigger_readiness_event",
    "run_workflow_trigger_scheduler_once",
    "preview_workflow_trigger_backfill",
    "launch_workflow_trigger_backfill",
    "cancel_workflow_backfill_launch",
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_trigger_read_endpoints_are_registry_owned() -> None:
    assert render_remote_endpoint_path(WORKFLOW_TRIGGER_LIST, {}) == "/api/v1/workflow-triggers"
    assert render_remote_endpoint_path(
        WORKFLOW_TRIGGER_INBOX_READ,
        {"trigger_id": "wtr_demo"},
        query_values={"state": "submitted", "limit": 5},
    ) == "/api/v1/workflow-triggers/wtr_demo/inbox?state=submitted&limit=5"
    assert render_remote_endpoint_path(
        GOVERNANCE_AUDIT_EVENTS_READ,
        {},
        query_values={"subjectKind": "run", "subjectId": "run_demo", "action": "run.submit", "limit": 25},
    ) == "/api/v1/audit/events?subjectKind=run&subjectId=run_demo&action=run.submit&limit=25"
    assert render_remote_endpoint_path(SECRET_PROVIDER_READINESS_READ, {}) == "/api/v1/secrets/provider-readiness"

    for endpoint_id in TRIGGER_READ_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "GET"
        assert endpoint.response_item_key is None


def test_trigger_read_methods_do_not_reappear_on_transport_or_proxy() -> None:
    for method_name in (
        "list_workflow_triggers",
        "list_workflow_trigger_events",
        "get_workflow_trigger_readiness_observation",
        "list_workflow_trigger_inbox_events",
        "list_workflow_trigger_scheduler_ticks",
        "list_workflow_backfill_launches",
        "get_workflow_backfill_launch",
        "list_governance_audit_events",
        "get_secret_provider_readiness",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def test_trigger_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(WORKFLOW_TRIGGER_CREATE, {}) == "/api/v1/workflow-triggers"
    assert (
        render_remote_endpoint_path(WORKFLOW_TRIGGER_INBOX_REPLAY, {"trigger_id": "wtr/1", "inbox_event_id": "evt/1"})
        == "/api/v1/workflow-triggers/wtr%2F1/inbox/evt%2F1/replay"
    )
    assert (
        render_remote_endpoint_path(WORKFLOW_BACKFILL_LAUNCH_CANCEL, {"launch_id": "bfl/1"})
        == "/api/v1/workflow-backfill-launches/bfl%2F1/cancel"
    )

    for endpoint_id in TRIGGER_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.cache_scope == "workflow-trigger-command"
        if endpoint_id in DISPATCH_ENDPOINTS:
            assert endpoint.response_key == ""
        else:
            assert endpoint.response_key == "data"

    assert REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_CREATE].accepted_statuses == (201,)
    assert remote_endpoint_success_status(WORKFLOW_TRIGGER_CREATE) == 201
    assert REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_BACKFILL_PREVIEW].accepted_statuses == (200,)
    for endpoint_id in set(TRIGGER_COMMAND_ENDPOINTS) - {WORKFLOW_TRIGGER_CREATE, WORKFLOW_TRIGGER_BACKFILL_PREVIEW}:
        assert REMOTE_ENDPOINTS[endpoint_id].accepted_statuses == (202,)
        assert remote_endpoint_success_status(endpoint_id) == 202


def test_trigger_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_route = {
        (policy.method, policy.route): policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in TRIGGER_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_route[(endpoint.method, endpoint.path_template)]
        assert policy.action == endpoint.governance_action


def test_trigger_command_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in TRIGGER_COMMAND_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_trigger_route_success_statuses_are_contract_owned() -> None:
    local_route_source = _source("apps/api/workflow_trigger_routes.py")
    remote_route_source = _source("apps/remote_runner/workflow_trigger_routes.py")
    contract_owned_successes = (
        "WORKFLOW_TRIGGER_CREATE",
        "WORKFLOW_TRIGGER_EVENT_SUBMIT",
        "WORKFLOW_TRIGGER_INBOX_SUBMIT",
        "WORKFLOW_TRIGGER_INBOX_REPLAY",
        "WORKFLOW_TRIGGER_READINESS_SUBMIT",
        "WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE",
        "WORKFLOW_TRIGGER_BACKFILL_LAUNCH",
        "WORKFLOW_BACKFILL_LAUNCH_CANCEL",
    )

    for route_source in (local_route_source, remote_route_source):
        for endpoint_id in contract_owned_successes:
            assert f"remote_endpoint_success_status({endpoint_id})" in route_source
        assert "status_code=201" not in route_source
        assert "status_code=202" not in route_source


def test_trigger_command_endpoint_caller_supports_json_and_raw_inbox_payloads() -> None:
    json_client = FakeCommandClient()
    dispatch = call_remote_endpoint(
        json_client,
        WORKFLOW_TRIGGER_EVENT_SUBMIT,
        path_values={"trigger_id": "wtr_1"},
        payload={"payload": {"sample": "A"}},
    )
    raw_client = FakeCommandClient()
    inbox = call_remote_endpoint(
        raw_client,
        WORKFLOW_TRIGGER_INBOX_SUBMIT,
        path_values={"trigger_id": "wtr_1"},
        raw_body=b'{"event":"ready"}',
        extra_headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
    )

    assert dispatch == {
        "path": "/api/v1/workflow-triggers/wtr_1/events",
        "payload": {"payload": {"sample": "A"}},
        "acceptedStatuses": [202],
    }
    assert inbox == {
        "path": "/api/v1/workflow-triggers/wtr_1/inbox",
        "rawBody": b'{"event":"ready"}',
        "extraHeaders": {"Content-Type": "application/json", "X-GitHub-Event": "push"},
        "acceptedStatuses": [202],
    }


def test_trigger_command_methods_do_not_reappear_on_transport_or_proxy() -> None:
    for method_name in TRIGGER_COMMAND_METHODS:
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


class FakeCommandClient:
    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        assert accepted_statuses is not None
        return {
            "path": path,
            "payload": dict(payload),
            "acceptedStatuses": sorted(accepted_statuses),
        }

    def post_bytes_json(
        self,
        path: str,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        assert accepted_statuses is not None
        return {
            "path": path,
            "rawBody": bytes(body),
            "extraHeaders": dict(extra_headers or {}),
            "acceptedStatuses": sorted(accepted_statuses),
        }
