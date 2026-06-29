from __future__ import annotations

import json
from threading import RLock
from types import SimpleNamespace

import pytest

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    RUN_CANCEL,
    RUN_RESUME,
    RUN_RETRY,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


RUN_COMMAND_ENDPOINTS = (RUN_CANCEL, RUN_RETRY, RUN_RESUME)


def test_run_command_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(RUN_CANCEL, {"run_id": "run/1"}) == "/api/v1/runs/run%2F1/cancel"
    assert render_remote_endpoint_path(RUN_RETRY, {"run_id": "run/1"}) == "/api/v1/runs/run%2F1/retry"
    assert render_remote_endpoint_path(RUN_RESUME, {"run_id": "run/1"}) == "/api/v1/runs/run%2F1/resume"

    for endpoint_id in RUN_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        assert endpoint.method == "POST"
        assert endpoint.response_key == "data"
        assert endpoint.cache_scope == "run-command"
        assert endpoint.invalidates == ("run-read-model",)
        assert endpoint.query_params == ()

    assert REMOTE_ENDPOINTS[RUN_CANCEL].accepted_statuses == (200,)
    assert REMOTE_ENDPOINTS[RUN_RETRY].accepted_statuses == (202,)
    assert REMOTE_ENDPOINTS[RUN_RESUME].accepted_statuses == (202,)


def test_run_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in RUN_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_run_command_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        cancel = paths[REMOTE_ENDPOINTS[RUN_CANCEL].path_template]["post"]
        retry = paths[REMOTE_ENDPOINTS[RUN_RETRY].path_template]["post"]
        resume = paths[REMOTE_ENDPOINTS[RUN_RESUME].path_template]["post"]

        assert cancel["operationId"] == REMOTE_ENDPOINTS[RUN_CANCEL].operation_id
        assert retry["operationId"] == REMOTE_ENDPOINTS[RUN_RETRY].operation_id
        assert resume["operationId"] == REMOTE_ENDPOINTS[RUN_RESUME].operation_id
        assert "200" in cancel["responses"]
        assert "202" not in cancel["responses"]
        assert "202" in retry["responses"]
        assert "200" not in retry["responses"]
        assert "202" in resume["responses"]
        assert "200" not in resume["responses"]


def test_run_command_endpoint_caller_posts_payload_and_accepted_statuses() -> None:
    client = FakeCommandClient()

    cancelled = call_remote_endpoint(client, RUN_CANCEL, path_values={"run_id": "run_1"})
    retried = call_remote_endpoint(
        client,
        RUN_RETRY,
        path_values={"run_id": "run_1"},
        payload={"scope": "run", "actor": "operator"},
    )
    resumed = call_remote_endpoint(
        client,
        RUN_RESUME,
        path_values={"run_id": "run_1"},
        payload={"confirmation": "resume-run", "planHash": "a" * 64},
    )

    assert cancelled == {"path": "/api/v1/runs/run_1/cancel", "payload": {}, "acceptedStatuses": [200]}
    assert retried == {
        "path": "/api/v1/runs/run_1/retry",
        "payload": {"scope": "run", "actor": "operator"},
        "acceptedStatuses": [202],
    }
    assert resumed == {
        "path": "/api/v1/runs/run_1/resume",
        "payload": {"confirmation": "resume-run", "planHash": "a" * 64},
        "acceptedStatuses": [202],
    }
    assert client.calls == [
        ("POST", "/api/v1/runs/run_1/cancel", {}, (200,)),
        ("POST", "/api/v1/runs/run_1/retry", {"scope": "run", "actor": "operator"}, (202,)),
        (
            "POST",
            "/api/v1/runs/run_1/resume",
            {"confirmation": "resume-run", "planHash": "a" * 64},
            (202,),
        ),
    ]


def test_run_command_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    cancelled = proxy.call_remote_endpoint(**_endpoint_kwargs(RUN_CANCEL, path_values={"run_id": "run_1"}))
    retried = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RUN_RETRY,
            path_values={"run_id": "run_1"},
            payload={"scope": "run", "actor": "operator"},
        )
    )
    resumed = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RUN_RESUME,
            path_values={"run_id": "run_1"},
            payload={"confirmation": "resume-run", "planHash": "a" * 64},
        )
    )

    assert cancelled == {"path": "/api/v1/runs/run_1/cancel", "payload": {}, "acceptedStatuses": [200]}
    assert retried == {
        "path": "/api/v1/runs/run_1/retry",
        "payload": {"scope": "run", "actor": "operator"},
        "acceptedStatuses": [202],
    }
    assert resumed == {
        "path": "/api/v1/runs/run_1/resume",
        "payload": {"confirmation": "resume-run", "planHash": "a" * 64},
        "acceptedStatuses": [202],
    }
    assert proxy.timeouts == [5, 5, 5]


def test_execution_manager_calls_run_commands_via_generic_endpoint() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.cancel_run("run_1") == {
        "data": {"endpointId": RUN_CANCEL, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.retry_run("run_1", {"scope": "run", "actor": "operator"}) == {
        "data": {"endpointId": RUN_RETRY, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.resume_run("run_1", {"confirmation": "resume-run", "planHash": "a" * 64}) == {
        "data": {"endpointId": RUN_RESUME, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert service.remote_runner_manager.calls == [
        (RUN_CANCEL, {"run_id": "run_1"}, {}),
        (RUN_RETRY, {"run_id": "run_1"}, {}),
        (RUN_RESUME, {"run_id": "run_1"}, {}),
    ]
    assert service.remote_runner_manager.payloads == [
        (RUN_CANCEL, {}),
        (RUN_RETRY, {"scope": "run", "actor": "operator"}),
        (RUN_RESUME, {"confirmation": "resume-run", "planHash": "a" * 64}),
    ]


def test_transport_and_proxy_do_not_keep_basic_run_command_methods() -> None:
    for method_name in ("cancel_run", "retry_run", "resume_run"):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
    for method_name in ("cancel_run", "retry_run"):
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def test_transport_rejects_unlisted_contract_success_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(_request, timeout):
        assert timeout == 5
        return FakeHttpResponse(status=200, body={"data": {"queued": True}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = RemoteRunnerHttpClient("http://runner.example", "token")
    with pytest.raises(RemoteRunnerClientError) as exc_info:
        client.post_json("/api/v1/runs/run_1/retry", {}, accepted_statuses={202})

    assert exc_info.value.status_code == 200
    assert exc_info.value.detail == {
        "acceptedStatusCodes": [202],
        "response": {"data": {"queued": True}},
        "statusCode": 200,
    }


class FakeCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object], tuple[int, ...] | None]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, object]:
        normalized_statuses = tuple(sorted(accepted_statuses)) if accepted_statuses else None
        self.calls.append(("POST", path, dict(payload), normalized_statuses))
        return {
            "data": {
                "path": path,
                "payload": dict(payload),
                "acceptedStatuses": list(normalized_statuses) if normalized_statuses else None,
            }
        }


class FakeHttpResponse:
    def __init__(self, *, status: int, body: dict[str, object]) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


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


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    path_values: dict[str, object],
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": dict(path_values),
        "query_values": {},
    }
    if payload is not None:
        kwargs["payload"] = dict(payload)
    return kwargs
