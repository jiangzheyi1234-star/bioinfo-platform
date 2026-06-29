from __future__ import annotations

import asyncio
from pathlib import Path

from apps.api.audit_routes import list_governance_audit_events
from core.contracts.remote_endpoints import (
    GOVERNANCE_AUDIT_EVENTS_READ,
    REMOTE_ENDPOINTS,
    render_remote_endpoint_path,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_governance_audit_route_is_authorized_and_service_owned() -> None:
    main_source = _source("apps/remote_runner/main.py")
    route_source = _source("apps/remote_runner/audit_routes.py")
    service_source = _source("apps/remote_runner/audit_service.py")
    audit_source = _source("apps/remote_runner/governance_audit.py")

    assert "from .audit_routes import router as audit_router" in main_source
    assert "app.include_router(audit_router)" in main_source
    assert '@router.get("/api/v1/audit/events", operation_id=REMOTE_ENDPOINTS[GOVERNANCE_AUDIT_EVENTS_READ].operation_id)' in route_source
    assert "AuthorizationHeader" in route_source
    assert 'alias="subjectKind"' in route_source
    assert 'alias="subjectId"' in route_source
    assert "authorized_config" in service_source
    assert '_authorized_config_from_request(authorization, action="audit.events.read")' in service_source
    assert "data_response(events)" in service_source
    assert "list_governance_audit_events" in service_source
    assert "payload" not in route_source
    assert "GOVERNANCE_AUDIT_SECRET_FIELD_FORBIDDEN" in audit_source


def test_local_governance_audit_route_delegates_to_runtime_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/audit_routes.py")
    service_source = _source("apps/api/audit_service.py")

    assert "from apps.api.audit_routes import router as audit_router" in main_source
    assert "app.include_router(audit_router)" in main_source
    assert '@router.get("/api/v1/audit/events", operation_id=REMOTE_ENDPOINTS[GOVERNANCE_AUDIT_EVENTS_READ].operation_id)' in route_source
    assert "runtime_service()" not in route_source
    assert "list_governance_audit_events_from_request" in route_source
    assert "runtime_service().list_governance_audit_events(" in service_source


def test_runtime_proxy_and_client_use_existing_runner_and_encoded_queries() -> None:
    execution_ops_source = _source("core/app_runtime/runner_execution_ops.py")
    execution_manager_source = _source("core/app_runtime/managers/execution.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    client_source = _source("core/remote_runner/client.py")

    assert REMOTE_ENDPOINTS[GOVERNANCE_AUDIT_EVENTS_READ].query_params == (
        "subjectKind",
        "subjectId",
        "action",
        "limit",
    )
    assert render_remote_endpoint_path(
        GOVERNANCE_AUDIT_EVENTS_READ,
        {},
        query_values={"subjectKind": "run", "subjectId": "run_demo", "action": "run.submit", "limit": 25},
    ) == "/api/v1/audit/events?subjectKind=run&subjectId=run_demo&action=run.submit&limit=25"
    assert "def list_governance_audit_events(" in execution_ops_source
    assert "self.execution.list_governance_audit_events(" in execution_ops_source
    assert "def list_governance_audit_events(" in execution_manager_source
    assert "GOVERNANCE_AUDIT_EVENTS_READ" in execution_manager_source
    assert "self.read_remote_endpoint(" in execution_manager_source
    assert "require_existing_runner=True" in execution_manager_source
    assert '"list_governance_audit_events"' not in execution_manager_source
    assert "def list_governance_audit_events(self, **kwargs) -> dict[str, Any]:" not in proxy_source
    assert 'client.get_json(f"/api/v1/audit/events?{query}")["data"]' not in proxy_source
    assert "def list_governance_audit_events(" not in client_source


def test_local_governance_audit_route_preserves_runtime_wrapper(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.audit_service.runtime_service", lambda: FakeAuditRuntime())

    response = asyncio.run(
        list_governance_audit_events(
            serverId="srv_audit",
            subjectKind="run",
            subjectId="run_demo",
            action="run.submit",
            limit=25,
        )
    )

    assert response == {
        "data": {
            "items": [
                {
                    "eventId": "evid_demo",
                    "action": "run.submit",
                    "subjectKind": "run",
                    "subjectId": "run_demo",
                }
            ]
        }
    }


class FakeAuditRuntime:
    def list_governance_audit_events(self, **kwargs):
        assert kwargs == {
            "server_id": "srv_audit",
            "subject_kind": "run",
            "subject_id": "run_demo",
            "action": "run.submit",
            "limit": 25,
        }
        return {
            "data": {
                "items": [
                    {
                        "eventId": "evid_demo",
                        "action": "run.submit",
                        "subjectKind": "run",
                        "subjectId": "run_demo",
                    }
                ]
            }
        }
