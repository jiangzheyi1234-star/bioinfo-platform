from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    remote_endpoint_success_status,
    render_remote_endpoint_path,
)
from core.contracts.workflow_design_remote_endpoints import (
    WORKFLOW_DESIGN_DRAFT_COMPILE,
    WORKFLOW_DESIGN_DRAFT_CREATE,
    WORKFLOW_DESIGN_DRAFT_DELETE,
    WORKFLOW_DESIGN_DRAFT_FORK,
    WORKFLOW_DESIGN_DRAFT_LIST,
    WORKFLOW_DESIGN_DRAFT_PLAN,
    WORKFLOW_DESIGN_DRAFT_READ,
    WORKFLOW_DESIGN_DRAFT_UPDATE,
)
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DESIGN_ENDPOINTS = (
    WORKFLOW_DESIGN_DRAFT_LIST,
    WORKFLOW_DESIGN_DRAFT_CREATE,
    WORKFLOW_DESIGN_DRAFT_READ,
    WORKFLOW_DESIGN_DRAFT_UPDATE,
    WORKFLOW_DESIGN_DRAFT_FORK,
    WORKFLOW_DESIGN_DRAFT_DELETE,
    WORKFLOW_DESIGN_DRAFT_PLAN,
    WORKFLOW_DESIGN_DRAFT_COMPILE,
)
WORKFLOW_DESIGN_PROXY_METHODS = (
    "list_workflow_design_drafts",
    "create_workflow_design_draft",
    "get_workflow_design_draft",
    "update_workflow_design_draft",
    "fork_workflow_design_draft",
    "delete_workflow_design_draft",
    "plan_workflow_design_draft",
    "compile_workflow_design_draft",
)


def test_workflow_design_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(WORKFLOW_DESIGN_DRAFT_LIST, {}) == "/api/v1/workflow-design-drafts"
    assert (
        render_remote_endpoint_path(WORKFLOW_DESIGN_DRAFT_READ, {"draft_id": "wfd/1"})
        == "/api/v1/workflow-design-drafts/wfd%2F1"
    )
    assert (
        render_remote_endpoint_path(WORKFLOW_DESIGN_DRAFT_FORK, {"draft_id": "wfd/1"})
        == "/api/v1/workflow-design-drafts/wfd%2F1/fork"
    )
    assert (
        render_remote_endpoint_path(WORKFLOW_DESIGN_DRAFT_COMPILE, {"draft_id": "wfd/1"})
        == "/api/v1/workflow-design-drafts/wfd%2F1/compile"
    )

    assert REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_LIST].response_item_key == "items"
    assert REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_CREATE].accepted_statuses == (201,)
    assert REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_FORK].accepted_statuses == (201,)
    assert remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_CREATE) == 201
    assert remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_FORK) == 201
    assert REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_UPDATE].method == "PATCH"
    assert REMOTE_ENDPOINTS[WORKFLOW_DESIGN_DRAFT_DELETE].method == "DELETE"
    for endpoint_id in WORKFLOW_DESIGN_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.path_template.startswith("/api/v1/workflow-design-drafts")


def test_workflow_design_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in WORKFLOW_DESIGN_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_workflow_design_route_success_statuses_are_contract_owned() -> None:
    local_route_source = (ROOT / "apps" / "api" / "workflow_design_routes.py").read_text(encoding="utf-8")
    remote_route_source = (ROOT / "apps" / "remote_runner" / "workflow_design_routes.py").read_text(encoding="utf-8")

    for route_source in (local_route_source, remote_route_source):
        assert "remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_CREATE)" in route_source
        assert "remote_endpoint_success_status(WORKFLOW_DESIGN_DRAFT_FORK)" in route_source
        assert "status_code=201" not in route_source


def test_workflow_design_endpoint_caller_preserves_item_and_data_unwraps() -> None:
    client = FakeWorkflowDesignClient()

    listed = call_remote_endpoint(client, WORKFLOW_DESIGN_DRAFT_LIST, path_values={})
    created = call_remote_endpoint(
        client,
        WORKFLOW_DESIGN_DRAFT_CREATE,
        path_values={},
        payload={"draft": {"contractVersion": "workflow-design-draft-v1"}},
    )
    updated = call_remote_endpoint(
        client,
        WORKFLOW_DESIGN_DRAFT_UPDATE,
        path_values={"draft_id": "wfd_demo"},
        payload={"expectedRevision": 1},
    )
    forked = call_remote_endpoint(
        client,
        WORKFLOW_DESIGN_DRAFT_FORK,
        path_values={"draft_id": "wfd_demo"},
        payload={"name": "Forked draft"},
    )
    planned = call_remote_endpoint(
        client,
        WORKFLOW_DESIGN_DRAFT_PLAN,
        path_values={"draft_id": "wfd_demo"},
        payload={},
    )
    compiled = call_remote_endpoint(client, WORKFLOW_DESIGN_DRAFT_COMPILE, path_values={"draft_id": "wfd_demo"})
    deleted = call_remote_endpoint(client, WORKFLOW_DESIGN_DRAFT_DELETE, path_values={"draft_id": "wfd_demo"})

    assert listed == [{"draftId": "wfd_demo"}]
    assert created == {"draftId": "wfd_created"}
    assert updated == {"draftId": "wfd_demo", "revision": 2}
    assert forked == {"draftId": "wfd_forked", "parentDraftId": "wfd_demo"}
    assert planned == {"valid": True}
    assert compiled == {"layout": {"snakefile": "workflow/Snakefile"}}
    assert deleted == {"draftId": "wfd_demo", "deleted": True}
    assert client.calls == [
        ("GET", "/api/v1/workflow-design-drafts", None, [200]),
        ("POST", "/api/v1/workflow-design-drafts", {"draft": {"contractVersion": "workflow-design-draft-v1"}}, [201]),
        ("PATCH", "/api/v1/workflow-design-drafts/wfd_demo", {"expectedRevision": 1}, [200]),
        ("POST", "/api/v1/workflow-design-drafts/wfd_demo/fork", {"name": "Forked draft"}, [201]),
        ("POST", "/api/v1/workflow-design-drafts/wfd_demo/plan", {}, [200]),
        ("POST", "/api/v1/workflow-design-drafts/wfd_demo/compile", {}, [200]),
        ("DELETE", "/api/v1/workflow-design-drafts/wfd_demo", None, [200]),
    ]


def test_workflow_design_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    listed = proxy.call_remote_endpoint(**_endpoint_kwargs(WORKFLOW_DESIGN_DRAFT_LIST))
    fetched = proxy.call_remote_endpoint(
        **_endpoint_kwargs(WORKFLOW_DESIGN_DRAFT_READ, path_values={"draft_id": "wfd_demo"})
    )
    compiled = proxy.call_remote_endpoint(
        **_endpoint_kwargs(WORKFLOW_DESIGN_DRAFT_COMPILE, path_values={"draft_id": "wfd_demo"})
    )

    assert listed == [{"draftId": "wfd_demo"}]
    assert fetched == {"draftId": "wfd_demo"}
    assert compiled == {"layout": {"snakefile": "workflow/Snakefile"}}
    assert proxy.client.calls == [
        ("GET", "/api/v1/workflow-design-drafts", None, [200]),
        ("GET", "/api/v1/workflow-design-drafts/wfd_demo", None, [200]),
        ("POST", "/api/v1/workflow-design-drafts/wfd_demo/compile", {}, [200]),
    ]


def test_workflow_design_methods_do_not_reappear_on_proxy() -> None:
    for method_name in WORKFLOW_DESIGN_PROXY_METHODS:
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    path_values: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"serverId": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": dict(path_values or {}),
        "query_values": {},
    }
    if payload is not None:
        kwargs["payload"] = payload
    return kwargs


class FakeWorkflowDesignClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, list[int]]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("GET", path, None, sorted(accepted_statuses or [])))
        if path == "/api/v1/workflow-design-drafts/wfd_demo":
            return {"data": {"draftId": "wfd_demo"}}
        return {"data": {"items": [{"draftId": "wfd_demo"}]}}

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("POST", path, dict(payload), sorted(accepted_statuses or [])))
        if path == "/api/v1/workflow-design-drafts/wfd_demo/fork":
            return {"data": {"draftId": "wfd_forked", "parentDraftId": "wfd_demo"}}
        if path == "/api/v1/workflow-design-drafts/wfd_demo/plan":
            return {"data": {"valid": True}}
        if path == "/api/v1/workflow-design-drafts/wfd_demo/compile":
            return {"data": {"layout": {"snakefile": "workflow/Snakefile"}}}
        return {"data": {"draftId": "wfd_created"}}

    def patch_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("PATCH", path, dict(payload), sorted(accepted_statuses or [])))
        return {"data": {"draftId": "wfd_demo", "revision": 2}}

    def delete_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("DELETE", path, None, sorted(accepted_statuses or [])))
        return {"data": {"draftId": "wfd_demo", "deleted": True}}


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeWorkflowDesignClient()

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return self.client
