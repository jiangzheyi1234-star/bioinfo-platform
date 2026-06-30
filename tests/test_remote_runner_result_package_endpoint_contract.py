from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    render_remote_endpoint_path,
)
from core.contracts.result_package_remote_endpoints import (
    RESULT_PACKAGE_BYTE_GC_PREVIEW,
    RESULT_PACKAGE_BYTE_GC_RUN,
    RESULT_PACKAGE_DOWNLOAD,
    RESULT_PACKAGE_EXPORT,
    RESULT_PACKAGE_RETIRE,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin
from core.remote_runner.result_package_proxy import RemoteRunnerResultPackageProxyMixin


RESULT_PACKAGE_COMMAND_ENDPOINTS = (
    RESULT_PACKAGE_EXPORT,
    RESULT_PACKAGE_RETIRE,
    RESULT_PACKAGE_BYTE_GC_PREVIEW,
    RESULT_PACKAGE_BYTE_GC_RUN,
)

RESULT_PACKAGE_GOVERNED_ENDPOINTS = (
    *RESULT_PACKAGE_COMMAND_ENDPOINTS,
    RESULT_PACKAGE_DOWNLOAD,
)


def test_result_package_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_EXPORT,
        {"result_id": "res/1"},
    ) == "/api/v1/results/res%2F1/export"
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_RETIRE,
        {"result_id": "res/1", "package_export_id": "rpex/1"},
    ) == "/api/v1/results/res%2F1/exports/rpex%2F1/retire"
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_BYTE_GC_PREVIEW,
        {},
    ) == "/api/v1/result-package-exports/bytes/gc/preview"
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_BYTE_GC_RUN,
        {},
    ) == "/api/v1/result-package-exports/bytes/gc/run"

    for endpoint_id in RESULT_PACKAGE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.response_key == "data"
        assert endpoint.cache_scope.endswith("-command")
        assert endpoint.query_params == ()

    assert REMOTE_ENDPOINTS[RESULT_PACKAGE_EXPORT].invalidates == ("result-package-export-read-model",)
    assert REMOTE_ENDPOINTS[RESULT_PACKAGE_RETIRE].invalidates == (
        "result-package-export-read-model",
        "artifact-lifecycle-read-model",
    )
    assert REMOTE_ENDPOINTS[RESULT_PACKAGE_BYTE_GC_PREVIEW].invalidates == ()
    assert REMOTE_ENDPOINTS[RESULT_PACKAGE_BYTE_GC_RUN].invalidates == (
        "result-package-export-read-model",
        "artifact-lifecycle-read-model",
    )


def test_result_package_download_endpoint_is_contract_rendered() -> None:
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_DOWNLOAD,
        {"result_id": "res/1", "package_export_id": "rpex/1"},
    ) == "/api/v1/results/res%2F1/exports/rpex%2F1/download"

    endpoint = REMOTE_ENDPOINTS[RESULT_PACKAGE_DOWNLOAD]
    assert endpoint.method == "GET"
    assert endpoint.governance_action == "result.package.download"
    assert endpoint.request_schema is None
    assert endpoint.response_schema == "h2ometa.result-package-download.v1"
    assert endpoint.cache_scope == "result-package-download"
    assert endpoint.invalidates == ()


def test_result_package_governed_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in RESULT_PACKAGE_GOVERNED_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_result_package_governed_endpoint_contracts_match_openapi_operation_ids() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in RESULT_PACKAGE_GOVERNED_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            assert "200" in operation["responses"]
            assert "202" not in operation["responses"]


def test_result_package_command_endpoint_caller_posts_payload() -> None:
    client = FakeCommandClient()

    exported = call_remote_endpoint(
        client,
        RESULT_PACKAGE_EXPORT,
        path_values={"result_id": "res_1"},
        payload={"includeArtifacts": False, "actor": "operator"},
    )
    retired = call_remote_endpoint(
        client,
        RESULT_PACKAGE_RETIRE,
        path_values={"result_id": "res_1", "package_export_id": "rpex_1"},
        payload={"confirmation": "retire-result-package-export"},
    )
    preview = call_remote_endpoint(
        client,
        RESULT_PACKAGE_BYTE_GC_PREVIEW,
        path_values={},
        payload={"retentionDays": 14},
    )
    run = call_remote_endpoint(
        client,
        RESULT_PACKAGE_BYTE_GC_RUN,
        path_values={},
        payload={"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
    )

    assert exported == {
        "path": "/api/v1/results/res_1/export",
        "payload": {"includeArtifacts": False, "actor": "operator"},
    }
    assert retired == {
        "path": "/api/v1/results/res_1/exports/rpex_1/retire",
        "payload": {"confirmation": "retire-result-package-export"},
    }
    assert preview == {
        "path": "/api/v1/result-package-exports/bytes/gc/preview",
        "payload": {"retentionDays": 14},
    }
    assert run == {
        "path": "/api/v1/result-package-exports/bytes/gc/run",
        "payload": {"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
    }
    assert client.calls == [
        ("POST", "/api/v1/results/res_1/export", {"includeArtifacts": False, "actor": "operator"}),
        ("POST", "/api/v1/results/res_1/exports/rpex_1/retire", {"confirmation": "retire-result-package-export"}),
        ("POST", "/api/v1/result-package-exports/bytes/gc/preview", {"retentionDays": 14}),
        (
            "POST",
            "/api/v1/result-package-exports/bytes/gc/run",
            {"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
        ),
    ]


def test_result_package_command_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    exported = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RESULT_PACKAGE_EXPORT,
            path_values={"result_id": "res_1"},
            payload={"includeArtifacts": False},
        )
    )
    retired = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RESULT_PACKAGE_RETIRE,
            path_values={"result_id": "res_1", "package_export_id": "rpex_1"},
            payload={"confirmation": "retire-result-package-export"},
        )
    )
    preview = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RESULT_PACKAGE_BYTE_GC_PREVIEW,
            payload={"retentionDays": 14},
        )
    )
    run = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RESULT_PACKAGE_BYTE_GC_RUN,
            payload={"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
        )
    )

    assert exported == {"path": "/api/v1/results/res_1/export", "payload": {"includeArtifacts": False}}
    assert retired == {
        "path": "/api/v1/results/res_1/exports/rpex_1/retire",
        "payload": {"confirmation": "retire-result-package-export"},
    }
    assert preview == {
        "path": "/api/v1/result-package-exports/bytes/gc/preview",
        "payload": {"retentionDays": 14},
    }
    assert run == {
        "path": "/api/v1/result-package-exports/bytes/gc/run",
        "payload": {"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
    }
    assert proxy.timeouts == [5, 5, 5, 5]


def test_execution_manager_calls_result_package_commands_via_generic_endpoint() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.export_result_package(
        "res_1",
        payload={"includeArtifacts": False},
        server_id="srv_result",
    ) == {"data": {"endpointId": RESULT_PACKAGE_EXPORT, "pathValues": {"result_id": "res_1"}, "queryValues": {}}}
    assert manager.retire_result_package(
        "res_1",
        "rpex_1",
        payload={"confirmation": "retire-result-package-export"},
        server_id="srv_result",
    ) == {
        "data": {
            "endpointId": RESULT_PACKAGE_RETIRE,
            "pathValues": {"result_id": "res_1", "package_export_id": "rpex_1"},
            "queryValues": {},
        }
    }
    assert manager.preview_result_package_byte_gc(
        {"retentionDays": 14},
        server_id="srv_result",
    ) == {"data": {"endpointId": RESULT_PACKAGE_BYTE_GC_PREVIEW, "pathValues": {}, "queryValues": {}}}
    assert manager.run_result_package_byte_gc(
        {"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"},
        server_id="srv_result",
    ) == {"data": {"endpointId": RESULT_PACKAGE_BYTE_GC_RUN, "pathValues": {}, "queryValues": {}}}
    assert service.remote_runner_manager.calls == [
        (RESULT_PACKAGE_EXPORT, {"result_id": "res_1"}, {}),
        (RESULT_PACKAGE_RETIRE, {"result_id": "res_1", "package_export_id": "rpex_1"}, {}),
        (RESULT_PACKAGE_BYTE_GC_PREVIEW, {}, {}),
        (RESULT_PACKAGE_BYTE_GC_RUN, {}, {}),
    ]
    assert service.remote_runner_manager.payloads == [
        (RESULT_PACKAGE_EXPORT, {"includeArtifacts": False}),
        (RESULT_PACKAGE_RETIRE, {"confirmation": "retire-result-package-export"}),
        (RESULT_PACKAGE_BYTE_GC_PREVIEW, {"retentionDays": 14}),
        (RESULT_PACKAGE_BYTE_GC_RUN, {"confirmation": "run-result-package-byte-gc", "planFingerprint": "fp_1"}),
    ]


def test_transport_and_result_package_proxy_keep_only_download_semantics() -> None:
    for method_name in (
        "export_result_package",
        "retire_result_package",
        "preview_result_package_byte_gc",
        "run_result_package_byte_gc",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerResultPackageProxyMixin, method_name)

    assert not hasattr(RemoteRunnerHttpClient, "download_result_package")
    assert hasattr(RemoteRunnerHttpClient, "download_bytes")
    assert hasattr(RemoteRunnerResultPackageProxyMixin, "download_result_package")


def test_transport_download_accepts_rendered_path_only() -> None:
    client = FakeDownloadClient("http://example.test", "token")

    assert client.download_bytes("/api/v1/results/res%2F1/exports/rpex%2F1/download") == {
        "method": "GET",
        "path": "/api/v1/results/res%2F1/exports/rpex%2F1/download",
    }
    assert client.calls == [("GET", "/api/v1/results/res%2F1/exports/rpex%2F1/download")]


def test_result_package_proxy_download_uses_registry_rendered_path() -> None:
    proxy = FakeDownloadProxy()

    assert proxy.download_result_package(
        server_id="srv_1",
        ssh_service=object(),
        server_record={"server_id": "srv_1"},
        result_id="res/1",
        package_export_id="rpex/1",
    ) == {
        "method": "GET",
        "path": "/api/v1/results/res%2F1/exports/rpex%2F1/download",
    }
    assert proxy.client.calls == [("GET", "/api/v1/results/res%2F1/exports/rpex%2F1/download")]
    assert proxy.timeouts == [60]


class FakeCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        assert accepted_statuses == {200}
        self.calls.append(("POST", path, dict(payload)))
        return {"data": {"path": path, "payload": dict(payload)}}


class FakeDownloadClient(RemoteRunnerHttpClient):
    def __init__(self, base_url: str, token: str) -> None:
        super().__init__(base_url, token)
        self.calls: list[tuple[str, str]] = []

    def _request_bytes(self, method: str, path: str) -> dict[str, object]:
        self.calls.append((method, path))
        return {"method": method, "path": path}


class FakeDownloadProxy(RemoteRunnerResultPackageProxyMixin):
    def __init__(self) -> None:
        self.client = FakeDownloadClient("http://example.test", "token")
        self.timeouts: list[int] = []

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        self.timeouts.append(int(kwargs["timeout"]))
        return self.client


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
        assert preferred_server_id == "srv_result"
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
