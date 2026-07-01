from __future__ import annotations

from fastapi.testclient import TestClient

from apps.remote_runner.main import app
from core.contracts.remote_endpoints import (
    EXECUTION_LIFECYCLE_GUARD,
    EXECUTION_LIFECYCLE_GUARD_RELEASE,
    REMOTE_ENDPOINTS,
    remote_endpoint_success_status,
)


def test_execution_lifecycle_endpoint_contracts_match_openapi_operation_ids() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    for endpoint_id in (EXECUTION_LIFECYCLE_GUARD, EXECUTION_LIFECYCLE_GUARD_RELEASE):
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        operation = paths[endpoint.path_template][endpoint.method.lower()]
        assert operation["operationId"] == endpoint.operation_id
        assert remote_endpoint_success_status(endpoint_id) == 200
        assert endpoint.governance_action is not None
