from __future__ import annotations

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


class FakeEndpointClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, object]:
        assert accepted_statuses == {200}
        self.calls.append(("GET", path))
        if path == "/api/v1/pipelines":
            return {"data": {"items": []}}
        return {"data": {"path": path}}
