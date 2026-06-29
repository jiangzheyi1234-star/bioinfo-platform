from __future__ import annotations

from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    RUN_EXECUTION_CONTEXT_READ,
    RUN_FAILURE_LOCATOR_READ,
    RUN_RULES_READ,
    RemoteEndpointContractError,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_runner_execution_proxy_exposes_retry_run_path() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    assert "def retry_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/retry", kwargs["payload"])["data"]' in proxy_source


def test_remote_runner_execution_proxy_exposes_rule_retry_and_resume_paths() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    proxy_source = _source("core/remote_runner/reexecution_proxy.py")

    assert "from core.remote_runner.reexecution_proxy import RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "class RemoteRunnerReexecutionProxyMixin:" in proxy_source
    assert "def retry_run_rules(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/rules/retry", kwargs["payload"])["data"]' in proxy_source
    assert "def apply_rule_output_invalidation(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/output-invalidation/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/adoption/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/adoption/apply"' in proxy_source
    assert "def resume_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/resume", kwargs["payload"])["data"]' in proxy_source


def test_run_read_model_endpoints_are_contract_rendered() -> None:
    assert set(REMOTE_ENDPOINTS) >= {
        RUN_EXECUTION_CONTEXT_READ,
        RUN_RULES_READ,
        RUN_FAILURE_LOCATOR_READ,
    }
    assert render_remote_endpoint_path(
        RUN_EXECUTION_CONTEXT_READ,
        {"run_id": "run with/slash"},
    ) == "/api/v1/runs/run%20with%2Fslash/execution-context"
    assert render_remote_endpoint_path(RUN_RULES_READ, {"run_id": "run_1"}) == "/api/v1/runs/run_1/rules"
    assert render_remote_endpoint_path(
        RUN_FAILURE_LOCATOR_READ,
        {"run_id": "run_1"},
    ) == "/api/v1/runs/run_1/failure-locator"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].operation_id == "getRunRules"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].response_schema == "run-rules.v1"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].cache_scope == "run-read-model"


def test_run_read_model_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in (RUN_EXECUTION_CONTEXT_READ, RUN_RULES_READ, RUN_FAILURE_LOCATOR_READ):
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_run_read_model_endpoint_contracts_match_openapi_operation_ids() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in (RUN_EXECUTION_CONTEXT_READ, RUN_RULES_READ, RUN_FAILURE_LOCATOR_READ):
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id


def test_remote_endpoint_contracts_fail_loudly_on_missing_path_param() -> None:
    try:
        render_remote_endpoint_path(RUN_RULES_READ, {})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_PATH_PARAM_REQUIRED"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("missing run_id should fail")


def test_remote_endpoint_caller_unwraps_data_and_records_path() -> None:
    client = FakeEndpointClient()

    data = call_remote_endpoint(client, RUN_RULES_READ, path_values={"run_id": "run_1"})

    assert data == {"path": "/api/v1/runs/run_1/rules"}
    assert client.calls == [("GET", "/api/v1/runs/run_1/rules")]


def test_remote_runner_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    context = proxy.call_remote_endpoint(**_runner_kwargs(RUN_EXECUTION_CONTEXT_READ, "run_1"))
    rules = proxy.call_remote_endpoint(**_runner_kwargs(RUN_RULES_READ, "run_1"))
    locator = proxy.call_remote_endpoint(**_runner_kwargs(RUN_FAILURE_LOCATOR_READ, "run_1"))

    assert context == {"path": "/api/v1/runs/run_1/execution-context"}
    assert rules == {"path": "/api/v1/runs/run_1/rules"}
    assert locator == {"path": "/api/v1/runs/run_1/failure-locator"}
    assert proxy.client.calls == [
        ("GET", "/api/v1/runs/run_1/execution-context"),
        ("GET", "/api/v1/runs/run_1/rules"),
        ("GET", "/api/v1/runs/run_1/failure-locator"),
    ]


def test_execution_manager_calls_generic_remote_endpoint_for_run_read_models() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.get_run_execution_context("run_1") == {
        "data": {"endpointId": RUN_EXECUTION_CONTEXT_READ, "pathValues": {"run_id": "run_1"}}
    }
    assert manager.get_run_rules("run_1") == {
        "data": {"endpointId": RUN_RULES_READ, "pathValues": {"run_id": "run_1"}}
    }
    assert manager.get_run_failure_locator("run_1") == {
        "data": {"endpointId": RUN_FAILURE_LOCATOR_READ, "pathValues": {"run_id": "run_1"}}
    }
    assert service.remote_runner_manager.calls == [
        (RUN_EXECUTION_CONTEXT_READ, {"run_id": "run_1"}),
        (RUN_RULES_READ, {"run_id": "run_1"}),
        (RUN_FAILURE_LOCATOR_READ, {"run_id": "run_1"}),
    ]


def test_remote_runner_http_client_does_not_keep_migrated_semantic_methods() -> None:
    assert not hasattr(RemoteRunnerHttpClient, "get_run_execution_context")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_rules")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_failure_locator")


class FakeEndpointClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.calls.append(("GET", path))
        return {"data": {"path": path}}


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeEndpointClient()

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

    def _require_runner_ready(self, *, preferred_server_id=None):
        assert preferred_server_id is None
        return "srv_1", object(), {"server_id": "srv_1"}

    def _call_remote_runner(self, method, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        assert "endpoint_id" in kwargs
        return method(**kwargs)


class FakeRemoteEndpointManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        path_values = dict(kwargs["path_values"])
        self.calls.append((str(kwargs["endpoint_id"]), path_values))
        return {"endpointId": kwargs["endpoint_id"], "pathValues": path_values}


def _runner_kwargs(endpoint_id: str, run_id: str) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {"run_id": run_id},
    }
