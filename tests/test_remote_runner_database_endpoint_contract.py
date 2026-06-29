from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.database_remote_endpoints import (
    DATABASE_CHECK,
    DATABASE_CREATE,
    DATABASE_DELETE,
    DATABASE_LIST,
    DATABASE_PACK_LIST,
    DATABASE_PACK_READY_SCAN,
    DATABASE_TEMPLATE_LIST,
    DATABASE_UPDATE,
)
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, render_remote_endpoint_path
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.manager import RemoteRunnerManager


ROOT = Path(__file__).resolve().parents[1]
DATABASE_ENDPOINTS = (
    DATABASE_LIST,
    DATABASE_TEMPLATE_LIST,
    DATABASE_PACK_LIST,
    DATABASE_PACK_READY_SCAN,
    DATABASE_CREATE,
    DATABASE_UPDATE,
    DATABASE_DELETE,
    DATABASE_CHECK,
)
DATABASE_COMMAND_ENDPOINTS = (
    DATABASE_PACK_READY_SCAN,
    DATABASE_CREATE,
    DATABASE_UPDATE,
    DATABASE_DELETE,
    DATABASE_CHECK,
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_database_endpoints_are_registry_owned() -> None:
    assert render_remote_endpoint_path(DATABASE_LIST, {}) == "/api/v1/databases"
    assert render_remote_endpoint_path(DATABASE_TEMPLATE_LIST, {}) == "/api/v1/database-templates"
    assert render_remote_endpoint_path(DATABASE_PACK_LIST, {}) == "/api/v1/database-packs"
    assert render_remote_endpoint_path(DATABASE_PACK_READY_SCAN, {}) == "/api/v1/database-pack-ready-scans"
    assert (
        render_remote_endpoint_path(DATABASE_UPDATE, {"database_id": "kraken/2"})
        == "/api/v1/databases/kraken%2F2"
    )
    assert (
        render_remote_endpoint_path(DATABASE_CHECK, {"database_id": "kraken/2"})
        == "/api/v1/databases/kraken%2F2/check"
    )

    assert REMOTE_ENDPOINTS[DATABASE_LIST].response_item_key == "items"
    assert REMOTE_ENDPOINTS[DATABASE_TEMPLATE_LIST].response_item_key == "items"
    assert REMOTE_ENDPOINTS[DATABASE_CREATE].accepted_statuses == (201,)
    for endpoint_id in DATABASE_COMMAND_ENDPOINTS:
        assert REMOTE_ENDPOINTS[endpoint_id].cache_scope.endswith("command")


def test_database_command_contracts_match_governance_policy() -> None:
    governance_by_route = {
        (policy.method, policy.route): policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }
    for endpoint_id in DATABASE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_route[(endpoint.method, endpoint.path_template)]
        assert policy.action == endpoint.governance_action


def test_database_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in DATABASE_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_database_endpoint_caller_unwraps_catalog_and_command_shapes() -> None:
    client = FakeDatabaseClient()

    databases = call_remote_endpoint(client, DATABASE_LIST, path_values={})
    templates = call_remote_endpoint(client, DATABASE_TEMPLATE_LIST, path_values={})
    packs = call_remote_endpoint(client, DATABASE_PACK_LIST, path_values={})
    scan = call_remote_endpoint(client, DATABASE_PACK_READY_SCAN, path_values={}, payload={"packId": "gtdbtk"})
    created = call_remote_endpoint(client, DATABASE_CREATE, path_values={}, payload={"id": "db_1"})
    updated = call_remote_endpoint(client, DATABASE_UPDATE, path_values={"database_id": "db_1"}, payload={"status": "available"})
    deleted = call_remote_endpoint(client, DATABASE_DELETE, path_values={"database_id": "db_1"})
    checked = call_remote_endpoint(client, DATABASE_CHECK, path_values={"database_id": "db_1"})

    assert databases == [{"id": "db_1"}]
    assert templates == [{"id": "kraken2"}]
    assert packs == {"items": [{"packId": "gtdbtk"}]}
    assert scan == {"packId": "gtdbtk", "status": "ready"}
    assert created == {"id": "db_1"}
    assert updated == {"id": "db_1", "status": "available"}
    assert deleted == {"id": "db_1", "deleted": True}
    assert checked == {"id": "db_1", "status": "available"}
    assert client.calls == [
        ("GET", "/api/v1/databases", [200]),
        ("GET", "/api/v1/database-templates", [200]),
        ("GET", "/api/v1/database-packs", [200]),
        ("POST", "/api/v1/database-pack-ready-scans", [200]),
        ("POST", "/api/v1/databases", [201]),
        ("PATCH", "/api/v1/databases/db_1", [200]),
        ("DELETE", "/api/v1/databases/db_1", [200]),
        ("POST", "/api/v1/databases/db_1/check", [200]),
    ]


def test_database_runtime_manager_uses_generic_endpoint_registry() -> None:
    manager_source = _source("core/app_runtime/managers/database.py")
    remote_manager_source = _source("core/remote_runner/manager.py")
    readiness_source = _source("core/remote_runner/readiness.py")

    assert not (ROOT / "core/remote_runner/catalog.py").exists()
    assert "RemoteRunnerCatalogMixin" not in remote_manager_source
    assert "DATABASE_TEMPLATE_LIST" in readiness_source
    assert 'client.get_json("/api/v1/database-templates")' not in readiness_source
    for endpoint_name in (
        "DATABASE_LIST",
        "DATABASE_TEMPLATE_LIST",
        "DATABASE_PACK_LIST",
        "DATABASE_PACK_READY_SCAN",
        "DATABASE_CREATE",
        "DATABASE_UPDATE",
        "DATABASE_DELETE",
        "DATABASE_CHECK",
    ):
        assert endpoint_name in manager_source
    assert "call_remote_endpoint(" in manager_source
    assert "call_existing_runner(" not in manager_source


def test_database_methods_do_not_reappear_on_transport_or_remote_manager() -> None:
    for method_name in (
        "list_database_templates",
        "list_database_packs",
        "scan_database_pack_ready",
        "list_databases",
        "add_database",
        "update_database",
        "delete_database",
        "check_database",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerManager, method_name)


class FakeDatabaseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[int]]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("GET", path, sorted(accepted_statuses or [])))
        if path == "/api/v1/databases":
            return {"data": {"items": [{"id": "db_1"}]}}
        if path == "/api/v1/database-templates":
            return {"data": {"items": [{"id": "kraken2"}]}}
        return {"data": {"items": [{"packId": "gtdbtk"}]}}

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("POST", path, sorted(accepted_statuses or [])))
        if path == "/api/v1/database-pack-ready-scans":
            return {"data": {"packId": payload["packId"], "status": "ready"}}
        if path == "/api/v1/databases":
            return {"data": {"id": payload["id"]}}
        return {"data": {"id": "db_1", "status": "available"}}

    def patch_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("PATCH", path, sorted(accepted_statuses or [])))
        return {"data": {"id": "db_1", "status": payload["status"]}}

    def delete_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("DELETE", path, sorted(accepted_statuses or [])))
        return {"data": {"id": "db_1", "deleted": True}}
