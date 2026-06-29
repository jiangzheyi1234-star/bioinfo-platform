from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY,
    RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE,
    RUN_RULE_CACHE_RESTORE_PINS_APPLY,
    RUN_RULE_CACHE_RESTORE_PINS_PREPARE,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE,
    RUN_RULE_OUTPUT_INVALIDATION_APPLY,
    RUN_RULE_RETRY,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


RULE_COMMAND_ENDPOINTS = (
    RUN_RULE_RETRY,
    RUN_RULE_OUTPUT_INVALIDATION_APPLY,
    RUN_RULE_CACHE_RESTORE_PINS_PREPARE,
    RUN_RULE_CACHE_RESTORE_PINS_APPLY,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY,
    RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE,
    RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY,
)
APPLY_ENDPOINTS = {
    RUN_RULE_RETRY,
    RUN_RULE_OUTPUT_INVALIDATION_APPLY,
    RUN_RULE_CACHE_RESTORE_PINS_APPLY,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY,
    RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY,
}
RULE_COMMAND_METHODS = (
    "retry_run_rules",
    "apply_rule_output_invalidation",
    "prepare_rule_cache_restore_pins",
    "apply_rule_cache_restore_pins",
    "prepare_rule_cache_restore_staged_files",
    "apply_rule_cache_restore_staged_files",
    "prepare_rule_cache_restore_final_outputs",
    "apply_rule_cache_restore_final_outputs",
    "prepare_rule_cache_restore_adoption",
    "apply_rule_cache_restore_adoption",
)


def test_rule_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(RUN_RULE_RETRY, {"run_id": "run/1"}) == "/api/v1/runs/run%2F1/rules/retry"
    assert (
        render_remote_endpoint_path(RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY, {"run_id": "run/1"})
        == "/api/v1/runs/run%2F1/rules/cache-restore/staged-files/apply"
    )

    for endpoint_id in RULE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.response_key == "data"
        assert endpoint.cache_scope == "run-rule-command"
        assert endpoint.query_params == ()
        expected_invalidates = ("run-read-model",) if endpoint_id in APPLY_ENDPOINTS else ()
        assert endpoint.invalidates == expected_invalidates

    assert REMOTE_ENDPOINTS[RUN_RULE_RETRY].accepted_statuses == (202,)
    for endpoint_id in set(RULE_COMMAND_ENDPOINTS) - {RUN_RULE_RETRY}:
        assert REMOTE_ENDPOINTS[endpoint_id].accepted_statuses == (200,)


def test_rule_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in RULE_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_rule_command_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in RULE_COMMAND_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            if endpoint_id == RUN_RULE_RETRY:
                assert "202" in operation["responses"]
                assert "200" not in operation["responses"]
            else:
                assert "200" in operation["responses"]
                assert "202" not in operation["responses"]


def test_rule_command_endpoint_caller_posts_payload_and_accepted_statuses() -> None:
    client = FakeCommandClient()
    payload = {"confirmation": "reviewed", "planHash": "a" * 64}

    for endpoint_id in RULE_COMMAND_ENDPOINTS:
        result = call_remote_endpoint(client, endpoint_id, path_values={"run_id": "run_1"}, payload=payload)
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert result == {
            "path": endpoint.path_template.replace("{run_id}", "run_1"),
            "payload": payload,
            "acceptedStatuses": list(endpoint.accepted_statuses),
        }

    assert [call[3] for call in client.calls] == [tuple(REMOTE_ENDPOINTS[item].accepted_statuses) for item in RULE_COMMAND_ENDPOINTS]


def test_execution_manager_calls_rule_commands_via_generic_endpoint() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)
    payload = {"confirmation": "reviewed", "planHash": "a" * 64}

    for method_name, endpoint_id in zip(RULE_COMMAND_METHODS, RULE_COMMAND_ENDPOINTS):
        result = getattr(manager, method_name)("run_1", payload)
        assert result == {"data": {"endpointId": endpoint_id, "pathValues": {"run_id": "run_1"}, "queryValues": {}}}

    assert service.remote_runner_manager.calls == [(endpoint_id, {"run_id": "run_1"}, {}) for endpoint_id in RULE_COMMAND_ENDPOINTS]
    assert service.remote_runner_manager.payloads == [(endpoint_id, payload) for endpoint_id in RULE_COMMAND_ENDPOINTS]


def test_transport_and_proxy_do_not_keep_rule_command_methods() -> None:
    for method_name in RULE_COMMAND_METHODS:
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


class FakeCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object], tuple[int, ...]]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        assert accepted_statuses is not None
        normalized_statuses = tuple(sorted(accepted_statuses))
        self.calls.append(("POST", path, dict(payload), normalized_statuses))
        return {
            "data": {
                "path": path,
                "payload": dict(payload),
                "acceptedStatuses": list(normalized_statuses),
            }
        }


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
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []
        self.payloads: list[tuple[str, dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        endpoint_id = str(kwargs["endpoint_id"])
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        self.calls.append((endpoint_id, path_values, query_values))
        self.payloads.append((endpoint_id, dict(kwargs.get("payload") or {})))
        return {"endpointId": endpoint_id, "pathValues": path_values, "queryValues": query_values}
