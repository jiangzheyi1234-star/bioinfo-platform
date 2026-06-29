from __future__ import annotations

import asyncio
from pathlib import Path

from apps.api.secret_routes import get_secret_provider_readiness
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    SECRET_PROVIDER_READINESS_READ,
    render_remote_endpoint_path,
)


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_secret_provider_readiness_route_is_authorized_and_service_owned() -> None:
    main_source = _source("apps/remote_runner/main.py")
    route_source = _source("apps/remote_runner/secret_routes.py")
    service_source = _source("apps/remote_runner/secret_service.py")
    readiness_source = _source("apps/remote_runner/secret_provider_readiness.py")

    assert "from .secret_routes import router as secret_router" in main_source
    assert "app.include_router(secret_router)" in main_source
    assert "operation_id=REMOTE_ENDPOINTS[SECRET_PROVIDER_READINESS_READ].operation_id" in route_source
    assert "AuthorizationHeader" in route_source
    assert "authorized_config" in service_source
    assert '_authorized_config_from_request(authorization, action="secret.provider_readiness.read")' in service_source
    assert "record_governance_audit_event" in service_source
    assert "data_response(readiness)" in service_source
    assert "rawReferenceExposure" in service_source
    assert "valueExposure" in service_source
    assert "individualReferenceProbe" in service_source
    assert "build_secret_provider_readiness" in readiness_source
    assert "secretValuesExposed" in readiness_source
    assert "payload" not in route_source


def test_local_secret_provider_readiness_route_delegates_to_runtime_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/secret_routes.py")
    service_source = _source("apps/api/secret_service.py")

    assert "from apps.api.secret_routes import router as secret_router" in main_source
    assert "app.include_router(secret_router)" in main_source
    assert "operation_id=REMOTE_ENDPOINTS[SECRET_PROVIDER_READINESS_READ].operation_id" in route_source
    assert "runtime_service()" not in route_source
    assert "get_secret_provider_readiness_from_request" in route_source
    assert "runtime_service().get_secret_provider_readiness(" in service_source


def test_runtime_proxy_and_client_use_existing_runner_without_secret_payloads() -> None:
    execution_ops_source = _source("core/app_runtime/runner_execution_ops.py")
    execution_manager_source = _source("core/app_runtime/managers/execution.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    client_source = _source("core/remote_runner/client.py")

    assert render_remote_endpoint_path(SECRET_PROVIDER_READINESS_READ, {}) == "/api/v1/secrets/provider-readiness"
    assert REMOTE_ENDPOINTS[SECRET_PROVIDER_READINESS_READ].query_params == ()
    assert "def get_secret_provider_readiness(" in execution_ops_source
    assert "self.execution.get_secret_provider_readiness(" in execution_ops_source
    assert "def get_secret_provider_readiness(" in execution_manager_source
    assert "SECRET_PROVIDER_READINESS_READ" in execution_manager_source
    assert "self.read_remote_endpoint(" in execution_manager_source
    assert "require_existing_runner=True" in execution_manager_source
    assert '"get_secret_provider_readiness"' not in execution_manager_source
    assert "def get_secret_provider_readiness(self, **kwargs) -> dict[str, Any]:" not in proxy_source
    assert 'client.get_json("/api/v1/secrets/provider-readiness")["data"]' not in proxy_source
    assert "def get_secret_provider_readiness(self) -> dict[str, Any]:" not in client_source
    assert 'self.get_json("/api/v1/secrets/provider-readiness")["data"]' not in client_source


def test_local_secret_provider_readiness_route_preserves_runtime_wrapper(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.secret_service.runtime_service", lambda: FakeSecretRuntime())

    response = asyncio.run(get_secret_provider_readiness(serverId="srv_secret"))

    assert response == {
        "data": {
            "schemaVersion": "remote-runner-secret-provider-readiness.v1",
            "providers": [
                {
                    "scheme": "env",
                    "state": "available",
                }
            ],
        }
    }


class FakeSecretRuntime:
    def get_secret_provider_readiness(self, **kwargs):
        assert kwargs == {"server_id": "srv_secret"}
        return {
            "data": {
                "schemaVersion": "remote-runner-secret-provider-readiness.v1",
                "providers": [
                    {
                        "scheme": "env",
                        "state": "available",
                    }
                ],
            }
        }
