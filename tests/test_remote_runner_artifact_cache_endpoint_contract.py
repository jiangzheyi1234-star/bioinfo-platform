from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    ARTIFACT_CACHE_LOOKUP,
    ARTIFACT_CACHE_PIN_RELEASE,
    ARTIFACT_CACHE_PIN_RETAIN,
    REMOTE_ENDPOINTS,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ARTIFACT_CACHE_COMMAND_ENDPOINTS = (
    ARTIFACT_CACHE_PIN_RETAIN,
    ARTIFACT_CACHE_PIN_RELEASE,
    ARTIFACT_CACHE_LOOKUP,
)


def test_artifact_cache_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(
        ARTIFACT_CACHE_PIN_RETAIN,
        {"cache_entry_id": "ace/1"},
    ) == "/api/v1/artifacts/cache/entries/ace%2F1/retain"
    assert render_remote_endpoint_path(
        ARTIFACT_CACHE_PIN_RELEASE,
        {"cache_pin_id": "acp/1"},
    ) == "/api/v1/artifacts/cache/pins/acp%2F1/release"
    assert render_remote_endpoint_path(ARTIFACT_CACHE_LOOKUP, {}) == "/api/v1/artifacts/cache/lookup"

    for endpoint_id in ARTIFACT_CACHE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.response_key == "data"
        assert endpoint.invalidates == ("artifact-cache-read-model",)


def test_artifact_cache_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in ARTIFACT_CACHE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_artifact_cache_command_endpoint_contracts_match_openapi_operation_ids() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in ARTIFACT_CACHE_COMMAND_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id


def test_artifact_cache_command_endpoint_caller_posts_payload() -> None:
    client = FakeCommandClient()

    retained = call_remote_endpoint(
        client,
        ARTIFACT_CACHE_PIN_RETAIN,
        path_values={"cache_entry_id": "ace_1"},
        payload={"reason": "retain"},
    )
    released = call_remote_endpoint(
        client,
        ARTIFACT_CACHE_PIN_RELEASE,
        path_values={"cache_pin_id": "acp_1"},
        payload={"confirmation": "release-artifact-cache-policy-pin"},
    )
    lookup = call_remote_endpoint(
        client,
        ARTIFACT_CACHE_LOOKUP,
        path_values={},
        payload={"workflowRevisionId": "wf_rev_1"},
    )

    assert retained == {"path": "/api/v1/artifacts/cache/entries/ace_1/retain", "payload": {"reason": "retain"}}
    assert released == {
        "path": "/api/v1/artifacts/cache/pins/acp_1/release",
        "payload": {"confirmation": "release-artifact-cache-policy-pin"},
    }
    assert lookup == {"path": "/api/v1/artifacts/cache/lookup", "payload": {"workflowRevisionId": "wf_rev_1"}}
    assert client.calls == [
        ("POST", "/api/v1/artifacts/cache/entries/ace_1/retain", {"reason": "retain"}),
        ("POST", "/api/v1/artifacts/cache/pins/acp_1/release", {"confirmation": "release-artifact-cache-policy-pin"}),
        ("POST", "/api/v1/artifacts/cache/lookup", {"workflowRevisionId": "wf_rev_1"}),
    ]


def test_artifact_cache_command_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    retained = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_CACHE_PIN_RETAIN,
            path_values={"cache_entry_id": "ace_1"},
            payload={"reason": "retain"},
        )
    )
    released = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_CACHE_PIN_RELEASE,
            path_values={"cache_pin_id": "acp_1"},
            payload={"confirmation": "release-artifact-cache-policy-pin"},
        )
    )
    lookup = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_CACHE_LOOKUP,
            payload={"workflowRevisionId": "wf_rev_1"},
        )
    )

    assert retained == {"path": "/api/v1/artifacts/cache/entries/ace_1/retain", "payload": {"reason": "retain"}}
    assert released == {
        "path": "/api/v1/artifacts/cache/pins/acp_1/release",
        "payload": {"confirmation": "release-artifact-cache-policy-pin"},
    }
    assert lookup == {"path": "/api/v1/artifacts/cache/lookup", "payload": {"workflowRevisionId": "wf_rev_1"}}
    assert proxy.client.calls == [
        ("POST", "/api/v1/artifacts/cache/entries/ace_1/retain", {"reason": "retain"}),
        ("POST", "/api/v1/artifacts/cache/pins/acp_1/release", {"confirmation": "release-artifact-cache-policy-pin"}),
        ("POST", "/api/v1/artifacts/cache/lookup", {"workflowRevisionId": "wf_rev_1"}),
    ]


def test_execution_manager_calls_artifact_cache_commands_via_generic_endpoint() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.retain_artifact_cache_pin(
        "ace_1",
        {"reason": "retain"},
        server_id="srv_artifact",
    ) == {
        "data": {"endpointId": ARTIFACT_CACHE_PIN_RETAIN, "pathValues": {"cache_entry_id": "ace_1"}, "queryValues": {}}
    }
    assert manager.release_artifact_cache_pin(
        "acp_1",
        {"confirmation": "release-artifact-cache-policy-pin"},
        server_id="srv_artifact",
    ) == {
        "data": {"endpointId": ARTIFACT_CACHE_PIN_RELEASE, "pathValues": {"cache_pin_id": "acp_1"}, "queryValues": {}}
    }
    assert manager.lookup_artifact_cache(
        {"workflowRevisionId": "wf_rev_1"},
        server_id="srv_artifact",
    ) == {
        "data": {"endpointId": ARTIFACT_CACHE_LOOKUP, "pathValues": {}, "queryValues": {}}
    }
    assert service.remote_runner_manager.calls == [
        (ARTIFACT_CACHE_PIN_RETAIN, {"cache_entry_id": "ace_1"}, {}),
        (ARTIFACT_CACHE_PIN_RELEASE, {"cache_pin_id": "acp_1"}, {}),
        (ARTIFACT_CACHE_LOOKUP, {}, {}),
    ]
    assert service.remote_runner_manager.payloads == [
        (ARTIFACT_CACHE_PIN_RETAIN, {"reason": "retain"}),
        (ARTIFACT_CACHE_PIN_RELEASE, {"confirmation": "release-artifact-cache-policy-pin"}),
        (ARTIFACT_CACHE_LOOKUP, {"workflowRevisionId": "wf_rev_1"}),
    ]


def test_transport_and_proxy_do_not_keep_artifact_cache_command_methods() -> None:
    for method_name in (
        "retain_artifact_cache_pin",
        "release_artifact_cache_pin",
        "lookup_artifact_cache",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


class FakeCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("POST", path, dict(payload)))
        return {"data": {"path": path, "payload": dict(payload)}}


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeCommandClient()

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return self.client


class FakeRuntimeService:
    def __init__(self) -> None:
        self._lock = RLock()
        self.remote_runner_manager = FakeRemoteEndpointManager()
        self._service_locator = SimpleNamespace(remote_runner_manager=self.remote_runner_manager)

    def _ensure_initialized(self) -> None:
        return None

    def _require_existing_runner_ready(self, *, preferred_server_id=None):
        assert preferred_server_id == "srv_artifact"
        return "srv_1", object(), {"server_id": "srv_1"}

    def _call_remote_runner(self, method, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        assert "endpoint_id" in kwargs
        return method(**kwargs)


class FakeRemoteEndpointManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []
        self.payloads: list[tuple[str, dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        endpoint_id = str(kwargs["endpoint_id"])
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        self.calls.append((endpoint_id, path_values, query_values))
        self.payloads.append((endpoint_id, dict(kwargs.get("payload") or {})))
        return {"endpointId": endpoint_id, "pathValues": path_values, "queryValues": query_values}


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    path_values: dict[str, object] | None = None,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": dict(path_values or {}),
        "query_values": {},
        "payload": dict(payload),
    }
