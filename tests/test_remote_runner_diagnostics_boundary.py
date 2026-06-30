from __future__ import annotations

import hashlib
import json
from typing import Any

from core.remote_runner.diagnostics import (
    OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS,
    build_execution_diagnostics,
    build_operator_diagnostics_bundle,
)
from core.remote_runner.proxy import RemoteRunnerProxyMixin


class FakeDiagnosticClient:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.probe_calls: list[tuple[str, list[int]]] = []

    def get_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.get_calls.append(path)
        return {
            "data": {
                "schemaVersion": "execution-diagnostics.v1",
                "readiness": {"ok": True},
            }
        }

    def probe_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.probe_calls.append((path, sorted(accepted_statuses or [])))
        if path == "/health/ready":
            return {
                "httpStatus": 503,
                "body": {"status": "failed", "reasonCode": "RUN_WORKER_UNAVAILABLE"},
            }
        return {"httpStatus": 200, "body": {"status": "ok", "data": {}}}


class UnreachableDiagnosticClient(FakeDiagnosticClient):
    def probe_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.probe_calls.append((path, sorted(accepted_statuses or [])))
        return {
            "httpStatus": None,
            "body": None,
            "error": {
                "reasonCode": "RUNNER_UNREACHABLE",
                "message": "connection refused",
                "errorType": "URLError",
            },
        }


def test_execution_diagnostics_uses_transport_get_json() -> None:
    client = FakeDiagnosticClient()

    diagnostics = build_execution_diagnostics(client)

    assert diagnostics["schemaVersion"] == "execution-diagnostics.v1"
    assert client.get_calls == ["/health/execution-diagnostics"]


def test_operator_diagnostics_bundle_uses_explicit_health_probe_set() -> None:
    client = FakeDiagnosticClient()

    bundle = build_operator_diagnostics_bundle(
        client,
        server_id="srv_1",
        run_id="run_1",
        scenario_id="moving-pictures-16s",
        release_tag="v1.0.0",
        source_commit="abc123",
    )

    assert bundle["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert bundle["identity"] == {
        "serverId": "srv_1",
        "runId": "run_1",
        "scenarioId": "moving-pictures-16s",
    }
    assert bundle["release"] == {"releaseTag": "v1.0.0", "sourceCommit": "abc123"}
    assert bundle["summary"]["remoteRunnerReachable"] is True
    assert bundle["summary"]["readinessOk"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUN_WORKER_UNAVAILABLE"]
    assert bundle["summary"]["endpointStatuses"]["ready"]["httpStatus"] == 503
    expected_hash = _expected_bundle_hash(bundle)
    assert bundle["bundleHash"] == expected_hash
    assert bundle["bundleId"] == f"opdiag_{expected_hash[:16]}"
    assert [path for path, _statuses in client.probe_calls] == list(
        OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
    )
    assert all(statuses == [200, 503] for _path, statuses in client.probe_calls)


def test_operator_diagnostics_bundle_summarizes_unreachable_runner() -> None:
    client = UnreachableDiagnosticClient()

    bundle = build_operator_diagnostics_bundle(client, server_id="srv_down")

    assert bundle["summary"]["remoteRunnerReachable"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUNNER_UNREACHABLE"]
    assert (
        bundle["summary"]["endpointStatuses"]["startup"]["error"]["reasonCode"]
        == "RUNNER_UNREACHABLE"
    )
    assert [path for path, _statuses in client.probe_calls] == list(
        OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
    )


class FakeDiagnosticsProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = object()
        self.client_requests: list[dict[str, Any]] = []

    def _get_client(self, **kwargs: Any) -> object:
        self.client_requests.append(dict(kwargs))
        return self.client


def test_proxy_diagnostics_methods_delegate_after_connection(monkeypatch) -> None:
    proxy = FakeDiagnosticsProxy()
    ssh_service = object()
    record = {
        "bootstrap_version": "fallback-release",
        "bootstrap_metadata": {
            "release": {"releaseTag": "v1.2.3", "sourceCommit": "abc123"}
        },
    }
    captured: dict[str, Any] = {}

    def fake_execution(client: object) -> dict[str, Any]:
        captured["executionClient"] = client
        return {"schemaVersion": "execution-diagnostics.v1"}

    def fake_operator(client: object, **kwargs: Any) -> dict[str, Any]:
        captured["operatorClient"] = client
        captured["operatorKwargs"] = dict(kwargs)
        return {"schemaVersion": "operator-diagnostics-bundle.v1"}

    monkeypatch.setattr(
        "core.remote_runner.proxy.build_execution_diagnostics",
        fake_execution,
    )
    monkeypatch.setattr(
        "core.remote_runner.proxy.build_operator_diagnostics_bundle",
        fake_operator,
    )

    execution = proxy.get_execution_diagnostics(
        server_id="srv_1", ssh_service=ssh_service, server_record=record
    )
    operator = proxy.get_operator_diagnostics(
        server_id="srv_1",
        ssh_service=ssh_service,
        server_record=record,
        run_id="run_1",
        scenario_id="moving-pictures-16s",
    )

    assert execution["schemaVersion"] == "execution-diagnostics.v1"
    assert operator["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert captured["executionClient"] is proxy.client
    assert captured["operatorClient"] is proxy.client
    assert captured["operatorKwargs"] == {
        "server_id": "srv_1",
        "run_id": "run_1",
        "scenario_id": "moving-pictures-16s",
        "release_tag": "v1.2.3",
        "source_commit": "abc123",
    }
    assert proxy.client_requests == [
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record},
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record},
    ]


def _expected_bundle_hash(bundle: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in bundle.items()
        if key not in {"bundleHash", "bundleId"}
    }
    payload = json.dumps(
        comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
