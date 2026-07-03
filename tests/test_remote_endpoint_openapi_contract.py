from __future__ import annotations

from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, RemoteEndpoint


def test_remote_endpoint_registry_matches_remote_runner_openapi() -> None:
    from apps.remote_runner.main import app

    paths = app.openapi()["paths"]

    for endpoint_id, endpoint in REMOTE_ENDPOINTS.items():
        operation = _operation(paths, endpoint)
        assert operation["operationId"] == endpoint.operation_id, endpoint_id
        for status in endpoint.accepted_statuses:
            assert str(status) in operation["responses"], endpoint_id
        _assert_parameters(endpoint_id, endpoint, operation)


def _operation(paths: dict[str, Any], endpoint: RemoteEndpoint) -> dict[str, Any]:
    path_item = paths.get(endpoint.path_template)
    assert path_item is not None, endpoint.endpoint_id
    operation = path_item.get(endpoint.method.lower())
    assert operation is not None, endpoint.endpoint_id
    return operation


def _assert_parameters(endpoint_id: str, endpoint: RemoteEndpoint, operation: dict[str, Any]) -> None:
    parameters = operation.get("parameters", [])
    query_parameters = {
        param.get("name")
        for param in parameters
        if param.get("in") == "query"
    }
    path_parameters = {
        param.get("name")
        for param in parameters
        if param.get("in") == "path"
    }

    for name in endpoint.query_params:
        assert name in query_parameters, endpoint_id
    for name in endpoint.path_params:
        assert name in path_parameters, endpoint_id
