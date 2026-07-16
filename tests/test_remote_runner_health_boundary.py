from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.runner_protocol_runtime import (
    build_runner_protocol_runtime_self_attestation,
)
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    RUNNER_HEALTH_EXECUTION_DIAGNOSTICS,
    RUNNER_HEALTH_LIVE,
    RUNNER_HEALTH_META,
    RUNNER_HEALTH_READY,
    RUNNER_HEALTH_STARTUP,
    RUNNER_HEALTH_WORKERS,
    render_remote_endpoint_path,
)
from core.remote_runner.diagnostics import OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.health import build_runner_health
from core.remote_runner.proxy import RemoteRunnerProxyMixin


class FakeHealthClient:
    def __init__(self, ready: dict[str, Any] | None = None) -> None:
        self.ready = ready or {
            "status": "ok",
            "workflowRuntime": {
                "ok": True,
                "provider": "conda-pack",
                "source": "artifact",
                "version": "v1",
                "snakemakeCommand": "snakemake",
                "snakemakeVersion": "9.1.0",
            },
            "pipelineRegistry": {
                "ok": True,
                "count": 1,
                "items": [{"id": "moving-pictures-16s"}],
            },
        }
        self.calls: list[tuple[str, list[int]]] = []

    def get_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.calls.append((path, sorted(accepted_statuses or [])))
        if path == "/health/startup":
            return {"status": "ok"}
        if path == "/health/live":
            return {
                "status": "ok",
                "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
            }
        if path == "/health/ready":
            return self.ready
        raise AssertionError(f"unexpected path: {path}")


def test_runner_health_uses_transport_json_endpoints() -> None:
    client = FakeHealthClient()

    health = build_runner_health(client)

    assert health["startup"]["ok"] is True
    assert health["live"]["ok"] is True
    assert health["ready"] == {
        "ok": True,
        "message": "Remote runner control plane is ready.",
    }
    assert health["workflowRuntime"]["provider"] == "conda-pack"
    assert health["pipelineRegistry"]["items"] == [{"id": "moving-pictures-16s"}]
    assert health["reasonCode"] == ""
    assert client.calls == [
        ("/health/startup", [200, 503]),
        ("/health/live", [200]),
        ("/health/ready", [200, 503]),
    ]


def test_runner_health_reports_not_ready_subsystems() -> None:
    client = FakeHealthClient(
        ready={
            "status": "failed",
            "workflowRuntime": {"ok": False, "message": "missing snakemake"},
            "pipelineRegistry": {"ok": False, "message": "catalog unavailable"},
        }
    )

    health = build_runner_health(client)

    assert health["ready"] == {
        "ok": False,
        "message": "workflow runtime: missing snakemake; pipeline registry: catalog unavailable",
    }
    assert health["workflowRuntime"]["ok"] is False
    assert health["pipelineRegistry"]["ok"] is False
    assert health["reasonCode"] == "WORKFLOW_RUNTIME_NOT_READY"


class FakeHealthProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeHealthClient()
        self.requests: list[dict[str, Any]] = []

    def _get_client_connection(self, **kwargs: Any) -> tuple[object, int, int]:
        self.requests.append(dict(kwargs))
        return self.client, 43127, 19001


def test_proxy_health_resync_path_delegates_to_health_helper() -> None:
    proxy = FakeHealthProxy()
    ssh_service = object()
    record = {"service_port": 43127, "token_ref": "runner://srv_1"}

    health = proxy.get_health(
        server_id="srv_1", ssh_service=ssh_service, server_record=record
    )

    assert health["ready"]["ok"] is True
    assert health["servicePort"] == 43127
    assert health["tunnelPort"] == 19001
    assert proxy.client.calls == [
        ("/health/startup", [200, 503]),
        ("/health/live", [200]),
        ("/health/ready", [200, 503]),
    ]
    assert proxy.requests == [
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record}
    ]


def test_runner_health_helpers_use_endpoint_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    health_source = (root / "core/remote_runner/health.py").read_text(encoding="utf-8")
    diagnostics_source = (root / "core/remote_runner/diagnostics.py").read_text(encoding="utf-8")

    assert render_remote_endpoint_path(RUNNER_HEALTH_STARTUP, {}) == "/health/startup"
    assert render_remote_endpoint_path(RUNNER_HEALTH_LIVE, {}) == "/health/live"
    assert render_remote_endpoint_path(RUNNER_HEALTH_READY, {}) == "/health/ready"
    assert render_remote_endpoint_path(RUNNER_HEALTH_META, {}) == "/health/meta"
    assert render_remote_endpoint_path(RUNNER_HEALTH_WORKERS, {}) == "/health/workers"
    assert render_remote_endpoint_path(RUNNER_HEALTH_EXECUTION_DIAGNOSTICS, {}) == "/health/execution-diagnostics"
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_STARTUP].accepted_statuses == (200, 503)
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_LIVE].accepted_statuses == (200,)
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_READY].accepted_statuses == (200, 503)
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_STARTUP].response_key is None
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_META].response_key == "data"
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_WORKERS].response_key == "data"
    assert REMOTE_ENDPOINTS[RUNNER_HEALTH_EXECUTION_DIAGNOSTICS].response_key == "data"
    assert OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS == (
        "/health/startup",
        "/health/live",
        "/health/ready",
        "/health/meta",
        "/health/workers",
        "/health/execution-diagnostics",
    )
    assert 'client.get_json("/health' not in health_source
    assert 'client.get_json("/health' not in diagnostics_source
    assert 'client.probe_json("/health' not in diagnostics_source


def test_runner_health_meta_and_workers_unwrap_data_envelopes() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[int]]] = []

        def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
            self.calls.append((path, sorted(accepted_statuses or [])))
            if path == "/health/meta":
                return {"data": {"service": "h2ometa-remote", "version": "v1"}}
            if path == "/health/workers":
                return {"data": {"summary": {"runningSlots": 0}}}
            raise AssertionError(f"unexpected path: {path}")

    client = FakeClient()

    meta = call_remote_endpoint(client, RUNNER_HEALTH_META, path_values={})
    workers = call_remote_endpoint(client, RUNNER_HEALTH_WORKERS, path_values={})

    assert meta == {"service": "h2ometa-remote", "version": "v1"}
    assert workers == {"summary": {"runningSlots": 0}}
    assert client.calls == [("/health/meta", [200]), ("/health/workers", [200])]
