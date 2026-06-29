from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, render_remote_endpoint_path
from core.contracts.tool_remote_endpoints import TOOL_INDEX_READ, TOOL_LIST
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]
TOOL_READ_ENDPOINTS = (TOOL_LIST, TOOL_INDEX_READ)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tool_read_endpoints_are_registry_owned() -> None:
    assert render_remote_endpoint_path(TOOL_LIST, {}) == "/api/v1/tools"
    assert (
        render_remote_endpoint_path(
            TOOL_INDEX_READ,
            {},
            query_values={"query": "fastqc", "limit": 25, "offset": 5, "source": "bioconda", "state": "ready"},
        )
        == "/api/v1/tools/index?query=fastqc&limit=25&offset=5&source=bioconda&state=ready"
    )

    listed = REMOTE_ENDPOINTS[TOOL_LIST]
    indexed = REMOTE_ENDPOINTS[TOOL_INDEX_READ]
    assert listed.method == "GET"
    assert listed.response_item_key == "items"
    assert listed.cache_scope == "tool-read-model"
    assert indexed.method == "GET"
    assert indexed.query_params == ("query", "limit", "offset", "source", "state")
    assert indexed.cache_scope == "tool-read-model"


def test_tool_read_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in TOOL_READ_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_tool_read_endpoint_caller_unwraps_list_items_and_index_data() -> None:
    client = FakeToolReadClient()

    listed = call_remote_endpoint(client, TOOL_LIST, path_values={})
    indexed = call_remote_endpoint(
        client,
        TOOL_INDEX_READ,
        path_values={},
        query_values={"query": "fastqc", "limit": 2, "offset": 1},
    )

    assert listed == [{"id": "bioconda::fastqc"}]
    assert indexed == {"items": [{"id": "bioconda::fastqc"}], "total": 1}
    assert client.calls == [
        ("/api/v1/tools", [200]),
        ("/api/v1/tools/index?query=fastqc&limit=2&offset=1", [200]),
    ]


def test_tool_read_proxy_uses_generic_endpoint_call() -> None:
    proxy = FakeToolReadProxy()

    listed = proxy.call_remote_endpoint(**_endpoint_kwargs(TOOL_LIST))
    indexed = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            TOOL_INDEX_READ,
            query_values={"limit": 50, "offset": 0, "source": "profile"},
        )
    )

    assert listed == [{"id": "bioconda::fastqc"}]
    assert indexed == {"items": [{"id": "bioconda::fastqc"}], "total": 1}
    assert proxy.client.calls == [
        ("/api/v1/tools", [200]),
        ("/api/v1/tools/index?limit=50&offset=0&source=profile", [200]),
    ]


def test_tool_read_manager_delegates_to_endpoint_registry() -> None:
    manager_source = _source("core/app_runtime/managers/tool.py")
    proxy_source = _source("core/remote_runner/proxy.py")

    assert "TOOL_LIST" in manager_source
    assert "TOOL_INDEX_READ" in manager_source
    assert "call_remote_endpoint(" in manager_source
    assert 'call_existing_runner("list_tools"' not in manager_source
    assert 'call_existing_runner("list_tool_index"' not in manager_source
    assert 'client.get_json("/api/v1/tools")' not in proxy_source
    assert 'client.get_json(f"/api/v1/tools/index?' not in proxy_source


def test_tool_read_methods_do_not_reappear_on_transport_or_proxy() -> None:
    for method_name in ("list_tools", "list_tool_index"):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    query_values: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"serverId": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {},
        "query_values": dict(query_values or {}),
    }


class FakeToolReadClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[int]]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append((path, sorted(accepted_statuses or [])))
        if path == "/api/v1/tools":
            return {"data": {"items": [{"id": "bioconda::fastqc"}]}}
        return {"data": {"items": [{"id": "bioconda::fastqc"}], "total": 1}}


class FakeToolReadProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeToolReadClient()

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return self.client
