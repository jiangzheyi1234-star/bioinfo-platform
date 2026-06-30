from __future__ import annotations

from typing import Any

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
            return {"status": "ok"}
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
        ("/health/live", []),
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
        ("/health/live", []),
        ("/health/ready", [200, 503]),
    ]
    assert proxy.requests == [
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record}
    ]
