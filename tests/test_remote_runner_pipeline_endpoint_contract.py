from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.pipeline import PipelineManager
from core.contracts.pipeline_remote_endpoints import PIPELINE_LIST, PIPELINE_READ
from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, render_remote_endpoint_path
from core.remote_runner.endpoint_caller import call_remote_endpoint


def test_pipeline_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(PIPELINE_LIST, {}) == "/api/v1/pipelines"
    assert (
        render_remote_endpoint_path(PIPELINE_READ, {"pipeline_id": "moving/pictures 16s"})
        == "/api/v1/pipelines/moving%2Fpictures%2016s"
    )

    list_endpoint = REMOTE_ENDPOINTS[PIPELINE_LIST]
    read_endpoint = REMOTE_ENDPOINTS[PIPELINE_READ]
    assert list_endpoint.method == "GET"
    assert list_endpoint.operation_id == "listPipelines"
    assert list_endpoint.response_schema == "pipeline-list.v1"
    assert list_endpoint.cache_scope == "pipeline-read-model"
    assert list_endpoint.response_item_key == "items"
    assert read_endpoint.method == "GET"
    assert read_endpoint.operation_id == "getPipeline"
    assert read_endpoint.response_schema == "pipeline.v1"
    assert read_endpoint.cache_scope == "pipeline-read-model"
    assert read_endpoint.response_item_key is None


def test_pipeline_endpoint_contracts_match_remote_openapi_operation_ids() -> None:
    from apps.remote_runner.main import app

    paths = app.openapi()["paths"]
    for endpoint_id in (PIPELINE_LIST, PIPELINE_READ):
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        operation = paths[endpoint.path_template][endpoint.method.lower()]
        assert operation["operationId"] == endpoint.operation_id
        assert "200" in operation["responses"]


def test_pipeline_endpoint_caller_uses_registry_path() -> None:
    client = FakeEndpointClient()

    listed = call_remote_endpoint(client, PIPELINE_LIST, path_values={})
    read = call_remote_endpoint(client, PIPELINE_READ, path_values={"pipeline_id": "moving/pictures 16s"})

    assert listed == []
    assert read == {"path": "/api/v1/pipelines/moving%2Fpictures%2016s"}
    assert client.calls == [
        ("GET", "/api/v1/pipelines"),
        ("GET", "/api/v1/pipelines/moving%2Fpictures%2016s"),
    ]


def test_pipeline_manager_reads_remote_registry_through_endpoint_contract() -> None:
    service = FakeRuntimeService()
    manager = PipelineManager(service)

    assert manager.list_pipelines(server_id="srv_pipeline") == {"data": {"items": [{"pipelineId": "pipe_1"}]}}
    assert manager.get_pipeline("pipe/1", server_id="srv_pipeline") == {
        "data": {
            "endpointId": PIPELINE_READ,
            "pathValues": {"pipeline_id": "pipe/1"},
            "queryValues": {},
        }
    }
    assert service.remote_runner_manager.calls == [
        (PIPELINE_LIST, {}, {}),
        (PIPELINE_READ, {"pipeline_id": "pipe/1"}, {}),
    ]


class FakeEndpointClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, object]:
        assert accepted_statuses == {200}
        self.calls.append(("GET", path))
        if path == "/api/v1/pipelines":
            return {"data": {"items": []}}
        return {"data": {"path": path}}


class FakeRuntimeService:
    def __init__(self) -> None:
        self._lock = RLock()
        self.remote_runner_manager = FakeRemoteEndpointManager()
        self._service_locator = SimpleNamespace(remote_runner_manager=self.remote_runner_manager)

    def _ensure_initialized(self) -> None:
        return None

    def _require_existing_runner_ready(self, *, preferred_server_id=None):
        assert preferred_server_id == "srv_pipeline"
        return "srv_1", object(), {"server_id": "srv_1"}

    def _call_remote_runner(self, method, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return method(**kwargs)


class FakeRemoteEndpointManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> object:
        endpoint_id = str(kwargs["endpoint_id"])
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        self.calls.append((endpoint_id, path_values, query_values))
        if endpoint_id == PIPELINE_LIST:
            return [{"pipelineId": "pipe_1"}]
        return {"endpointId": endpoint_id, "pathValues": path_values, "queryValues": query_values}
