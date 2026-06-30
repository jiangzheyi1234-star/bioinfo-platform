from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
    ARTIFACT_LIFECYCLE_GC_PREVIEW,
    ARTIFACT_LIFECYCLE_GC_RUN,
    ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
    REMOTE_ENDPOINTS,
    remote_endpoint_success_status,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ARTIFACT_LIFECYCLE_COMMAND_ENDPOINTS = (
    ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
    ARTIFACT_LIFECYCLE_GC_PREVIEW,
    ARTIFACT_LIFECYCLE_GC_RUN,
)


def test_artifact_lifecycle_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(
        ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
        {},
    ) == "/api/v1/artifacts/lifecycle/controller/run-once"
    assert render_remote_endpoint_path(
        ARTIFACT_LIFECYCLE_GC_PREVIEW,
        {},
    ) == "/api/v1/artifacts/lifecycle/gc/preview"
    assert render_remote_endpoint_path(
        ARTIFACT_LIFECYCLE_GC_RUN,
        {},
    ) == "/api/v1/artifacts/lifecycle/gc/run"
    assert render_remote_endpoint_path(
        ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
        {},
    ) == "/api/v1/artifacts/storage/readiness/smoke"

    for endpoint_id in ARTIFACT_LIFECYCLE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.response_key == "data"
        assert endpoint.cache_scope == "artifact-lifecycle-command"
    assert REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE].accepted_statuses == (202,)
    assert remote_endpoint_success_status(ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE) == 202
    for endpoint_id in (ARTIFACT_LIFECYCLE_GC_PREVIEW, ARTIFACT_LIFECYCLE_GC_RUN):
        assert REMOTE_ENDPOINTS[endpoint_id].accepted_statuses == (200,)
    storage_smoke = REMOTE_ENDPOINTS[ARTIFACT_STORAGE_READINESS_SMOKE_RUN]
    assert storage_smoke.method == "POST"
    assert storage_smoke.response_key == "data"
    assert storage_smoke.cache_scope == "artifact-storage-readiness-command"
    assert storage_smoke.invalidates == ("artifact-storage-readiness-read-model",)


def test_artifact_lifecycle_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in ARTIFACT_LIFECYCLE_COMMAND_ENDPOINTS + (ARTIFACT_STORAGE_READINESS_SMOKE_RUN,):
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_artifact_lifecycle_command_endpoint_contracts_match_openapi_operation_ids() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in ARTIFACT_LIFECYCLE_COMMAND_ENDPOINTS + (ARTIFACT_STORAGE_READINESS_SMOKE_RUN,):
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_artifact_lifecycle_command_endpoint_caller_posts_payload() -> None:
    client = FakeCommandClient()

    controller = call_remote_endpoint(
        client,
        ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
        path_values={},
        payload={"confirmation": "run-artifact-lifecycle-controller-once"},
    )
    preview = call_remote_endpoint(
        client,
        ARTIFACT_LIFECYCLE_GC_PREVIEW,
        path_values={},
        payload={"retentionDays": 30},
    )
    run = call_remote_endpoint(
        client,
        ARTIFACT_LIFECYCLE_GC_RUN,
        path_values={},
        payload={"confirmation": "delete-artifact-payloads"},
    )
    smoke = call_remote_endpoint(
        client,
        ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
        path_values={},
    )

    assert controller == {
        "path": "/api/v1/artifacts/lifecycle/controller/run-once",
        "payload": {"confirmation": "run-artifact-lifecycle-controller-once"},
    }
    assert preview == {"path": "/api/v1/artifacts/lifecycle/gc/preview", "payload": {"retentionDays": 30}}
    assert run == {
        "path": "/api/v1/artifacts/lifecycle/gc/run",
        "payload": {"confirmation": "delete-artifact-payloads"},
    }
    assert smoke == {"path": "/api/v1/artifacts/storage/readiness/smoke", "payload": {}}
    assert client.calls == [
        (
            "POST",
            "/api/v1/artifacts/lifecycle/controller/run-once",
            {"confirmation": "run-artifact-lifecycle-controller-once"},
            [202],
        ),
        ("POST", "/api/v1/artifacts/lifecycle/gc/preview", {"retentionDays": 30}, [200]),
        ("POST", "/api/v1/artifacts/lifecycle/gc/run", {"confirmation": "delete-artifact-payloads"}, [200]),
        ("POST", "/api/v1/artifacts/storage/readiness/smoke", {}, [200]),
    ]


def test_artifact_lifecycle_command_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    controller = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
            payload={"confirmation": "run-artifact-lifecycle-controller-once"},
            timeout=20,
        )
    )
    preview = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_LIFECYCLE_GC_PREVIEW,
            payload={"retentionDays": 30},
        )
    )
    run = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_LIFECYCLE_GC_RUN,
            payload={"confirmation": "delete-artifact-payloads"},
        )
    )
    smoke = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
            payload={},
        )
    )

    assert controller == {
        "path": "/api/v1/artifacts/lifecycle/controller/run-once",
        "payload": {"confirmation": "run-artifact-lifecycle-controller-once"},
    }
    assert preview == {"path": "/api/v1/artifacts/lifecycle/gc/preview", "payload": {"retentionDays": 30}}
    assert run == {
        "path": "/api/v1/artifacts/lifecycle/gc/run",
        "payload": {"confirmation": "delete-artifact-payloads"},
    }
    assert smoke == {"path": "/api/v1/artifacts/storage/readiness/smoke", "payload": {}}
    assert proxy.client.calls == [
        (
            "POST",
            "/api/v1/artifacts/lifecycle/controller/run-once",
            {"confirmation": "run-artifact-lifecycle-controller-once"},
            [202],
        ),
        ("POST", "/api/v1/artifacts/lifecycle/gc/preview", {"retentionDays": 30}, [200]),
        ("POST", "/api/v1/artifacts/lifecycle/gc/run", {"confirmation": "delete-artifact-payloads"}, [200]),
        ("POST", "/api/v1/artifacts/storage/readiness/smoke", {}, [200]),
    ]
    assert proxy.timeouts == [20, 5, 5, 5]


def test_execution_manager_calls_artifact_lifecycle_commands_via_generic_endpoint() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.run_artifact_lifecycle_controller_once(
        {"confirmation": "run-artifact-lifecycle-controller-once"},
        server_id="srv_artifact",
    ) == {"data": {"endpointId": ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE, "pathValues": {}, "queryValues": {}}}
    assert manager.preview_artifact_gc(
        {"retentionDays": 30},
        server_id="srv_artifact",
    ) == {"data": {"endpointId": ARTIFACT_LIFECYCLE_GC_PREVIEW, "pathValues": {}, "queryValues": {}}}
    assert manager.run_artifact_gc(
        {"confirmation": "delete-artifact-payloads"},
        server_id="srv_artifact",
    ) == {"data": {"endpointId": ARTIFACT_LIFECYCLE_GC_RUN, "pathValues": {}, "queryValues": {}}}
    assert manager.run_artifact_storage_readiness_smoke(server_id="srv_artifact") == {
        "data": {"endpointId": ARTIFACT_STORAGE_READINESS_SMOKE_RUN, "pathValues": {}, "queryValues": {}}
    }
    assert service.remote_runner_manager.calls == [
        (ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE, {}, {}, 20),
        (ARTIFACT_LIFECYCLE_GC_PREVIEW, {}, {}, None),
        (ARTIFACT_LIFECYCLE_GC_RUN, {}, {}, None),
        (ARTIFACT_STORAGE_READINESS_SMOKE_RUN, {}, {}, None),
    ]
    assert service.remote_runner_manager.payloads == [
        (ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE, {"confirmation": "run-artifact-lifecycle-controller-once"}),
        (ARTIFACT_LIFECYCLE_GC_PREVIEW, {"retentionDays": 30}),
        (ARTIFACT_LIFECYCLE_GC_RUN, {"confirmation": "delete-artifact-payloads"}),
        (ARTIFACT_STORAGE_READINESS_SMOKE_RUN, {}),
    ]


def test_transport_and_proxy_do_not_keep_artifact_lifecycle_command_methods() -> None:
    for method_name in (
        "run_artifact_lifecycle_controller_once",
        "preview_artifact_gc",
        "run_artifact_gc",
        "run_artifact_storage_readiness_smoke",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


class FakeCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object], list[int]]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        assert accepted_statuses in ({200}, {202})
        self.calls.append(("POST", path, dict(payload), sorted(accepted_statuses or [])))
        return {"data": {"path": path, "payload": dict(payload)}}


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeCommandClient()
        self.timeouts: list[int] = []

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        self.timeouts.append(int(kwargs["timeout"]))
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
        self.calls: list[tuple[str, dict[str, object], dict[str, object], int | None]] = []
        self.payloads: list[tuple[str, dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        endpoint_id = str(kwargs["endpoint_id"])
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        self.calls.append((endpoint_id, path_values, query_values, kwargs.get("timeout")))
        self.payloads.append((endpoint_id, dict(kwargs.get("payload") or {})))
        return {"endpointId": endpoint_id, "pathValues": path_values, "queryValues": query_values}


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    payload: dict[str, object],
    timeout: int | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {},
        "query_values": {},
        "payload": dict(payload),
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs
