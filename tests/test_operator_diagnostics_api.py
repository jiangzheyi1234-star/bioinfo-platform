from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from apps.api.response_cache import invalidate_response_cache
from apps.api.ssh_routes import get_server_operator_diagnostics, list_servers
from core.app_runtime.service import RuntimeService, ServiceLocator


def _service(_tmp_path: Path) -> RuntimeService:
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    return service


def _patch_runtime_service(monkeypatch, service: RuntimeService) -> None:
    asyncio.run(invalidate_response_cache("servers", "ssh_status", prefixes=("runs", "tools")))
    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: service)


def test_server_operator_diagnostics_contract(monkeypatch, tmp_path: Path) -> None:
    service = _service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeRemoteRunnerManager:
        def get_operator_diagnostics(self, **kwargs):
            return {
                "schemaVersion": "operator-diagnostics-bundle.v1",
                "identity": {
                    "serverId": kwargs["server_id"],
                    "runId": kwargs["run_id"],
                    "scenarioId": kwargs["scenario_id"],
                },
                "remoteRunner": {
                    "/health/execution-diagnostics": {
                        "httpStatus": 200,
                        "body": {"data": {"schemaVersion": "execution-diagnostics.v1"}},
                    }
                },
                "summary": {"remoteRunnerReachable": True, "reasonCodes": []},
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        "bootstrap_version": "phase-operator-diagnostics-test",
        "runner_mode": "background_process",
        "service_port": 43127,
        "token_ref": "runner://srv_test",
    }

    payload = asyncio.run(
        get_server_operator_diagnostics(
            server_id,
            run_id="run_operator_1",
            scenario_id="resource-wait",
        )
    )

    data = payload["data"]
    assert data["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert data["identity"] == {
        "serverId": server_id,
        "runId": "run_operator_1",
        "scenarioId": "resource-wait",
    }
    assert (
        data["remoteRunner"]["/health/execution-diagnostics"]["body"]["data"]["schemaVersion"]
        == "execution-diagnostics.v1"
    )
