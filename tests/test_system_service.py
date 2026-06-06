from __future__ import annotations

import asyncio

from apps.api import system_service


def test_service_info_exposes_local_identity_version_readiness(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_RUNTIME_BUILD_ID", "build-test-123")
    monkeypatch.setenv("H2OMETA_BACKEND_SOURCE", "windows-launcher")

    payload = asyncio.run(system_service.service_info_from_request())

    item = payload["item"]
    assert item["service"] == "h2ometa-local-api"
    assert item["kind"] == "local-control-plane"
    assert item["identity"]["service"] == "h2ometa-local-api"
    assert item["identity"]["backendSource"] == "windows-launcher"
    assert item["identity"]["processId"] > 0
    assert item["version"] == {
        "buildId": "build-test-123",
        "terminalRuntimeBuildId": system_service.TERMINAL_RUNTIME_BUILD_ID,
        "terminalTransport": "websocket",
        "backendSource": "windows-launcher",
    }
    assert item["readiness"] == {
        "status": "ready",
        "checks": {
            "process": True,
            "systemRoutes": True,
        },
    }
    assert item["stateCounts"] == {"localApiProcesses": 1}
