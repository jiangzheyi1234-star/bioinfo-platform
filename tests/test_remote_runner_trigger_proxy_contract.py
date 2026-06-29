from __future__ import annotations

from pathlib import Path

from core.contracts.remote_endpoints import (
    GOVERNANCE_AUDIT_EVENTS_READ,
    REMOTE_ENDPOINTS,
    SECRET_PROVIDER_READINESS_READ,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    render_remote_endpoint_path,
)
from core.remote_runner.client import RemoteRunnerHttpClient
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


def test_trigger_commands_keep_specialized_transport_paths() -> None:
    client_source = _source("core/remote_runner/client.py")
    proxy_source = _source("core/remote_runner/proxy.py")

    assert 'def create_workflow_trigger(self, payload: dict[str, Any]) -> dict[str, Any]:' in client_source
    assert 'return self.post_json("/api/v1/workflow-triggers", payload)["data"]' in client_source
    assert "def submit_workflow_trigger_event(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/events", payload)' in client_source
    assert "def post_bytes_json(" in client_source
    assert "raw_body: bytes | None = None" in client_source
    assert "headers: dict[str, str] | None = None" in client_source
    assert "return self.post_bytes_json(path, raw_body, extra_headers=headers)" in client_source
    assert "def replay_workflow_trigger_inbox_event(" in client_source
    assert 'f"/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay"' in client_source
    assert "def submit_workflow_trigger_readiness_event(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/readiness", payload)' in client_source
    assert "def preview_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/preview", payload)' in client_source
    assert "def launch_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/launch", payload)' in client_source
    assert "def cancel_workflow_backfill_launch(self, launch_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-backfill-launches/{launch_id}/cancel", payload)["data"]' in client_source
    assert "def run_workflow_trigger_scheduler_once(self, payload: dict[str, Any])" in client_source
    assert 'return self.post_json("/api/v1/workflow-trigger-scheduler/run-once", payload)["data"]' in client_source

    assert "def create_workflow_trigger(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_inbox_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def replay_workflow_trigger_inbox_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_readiness_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def preview_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def launch_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def cancel_workflow_backfill_launch(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def run_workflow_trigger_scheduler_once(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "client.submit_workflow_trigger_inbox_event(" in proxy_source
    assert '"/api/v1/workflow-trigger-scheduler/run-once"' in proxy_source
