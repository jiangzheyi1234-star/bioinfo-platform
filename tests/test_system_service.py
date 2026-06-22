from __future__ import annotations

import asyncio

import pytest

from apps.api import system_service
from core.deployment_mode import DeploymentModeError, UnsupportedDeploymentModeError


def test_service_info_exposes_local_identity_version_readiness(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "desktop")
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
        "status": "degraded",
        "checks": {
            "process": True,
            "systemRoutes": True,
            "remoteRunner": False,
        },
    }
    assert item["stateCounts"] == {
        "localApiProcesses": 1,
        "remoteRunnerConnected": False,
        "activeSshSessions": 0,
    }


def test_service_info_requires_explicit_deployment_mode(monkeypatch) -> None:
    monkeypatch.delenv("H2OMETA_DEPLOYMENT_MODE", raising=False)

    with pytest.raises(DeploymentModeError, match="H2OMETA_DEPLOYMENT_MODE is required"):
        asyncio.run(system_service.service_info_from_request())


def test_service_info_rejects_unimplemented_multi_user(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "server-multi-user")

    with pytest.raises(UnsupportedDeploymentModeError, match="server-multi-user"):
        asyncio.run(system_service.service_info_from_request())
